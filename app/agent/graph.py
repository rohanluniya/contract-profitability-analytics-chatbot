"""Governed conversational router, slash-command parser, CAT write-back parser, multi-turn memory, and MCP orchestrator."""
from __future__ import annotations

import re
import time
import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.agent import guardrails as G
from app.agent import llm
from app.agent.prompts import ANSWER_WRITER_SYSTEM, TOOL_ROUTER_SYSTEM
from app.cat.store import TEAM_DIRECTORY
from app.config import as_of_date
from app.semantic.access import ALL_BUSINESS_UNITS, get_user_scope
from app.semantic.service import ToolPayload
from mcp_server.server import ALLOWED_TOOLS, TOOL_SCHEMAS, invoke_tool

CONTRACT_ID_RE = re.compile(r"\b((?:FS|TM|SP)-[A-Z]+-\d{3})\b", re.IGNORECASE)
EXCEPTION_ID_RE = re.compile(r"\b(EXC-\d{3})\b", re.IGNORECASE)
TASK_ID_RE = re.compile(r"\b(TSK-\d{4}-\d+)\b", re.IGNORECASE)
BU_ID_RE = re.compile(r"\b(BU-[A-Z]+-\d{2})\b", re.IGNORECASE)
HOURS_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:hrs?|hours?)\b", re.IGNORECASE)
USD_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)

TEAM_NAMES = [t["name"] for t in TEAM_DIRECTORY]

BU_KEYWORDS = {
    "renewable": "BU-RENEW-01",
    "aerospace": "BU-AERO-02",
    "metallurgy": "BU-AERO-02",
    "semiconductor": "BU-ELEC-03",
    "electronics verification": "BU-ELEC-03",
    "environmental": "BU-ENV-04",
    "toxicology": "BU-ENV-04",
    "biopharma": "BU-PHARM-05",
    "medical device": "BU-PHARM-05",
    "offshore": "BU-OFFSHORE-06",
    "marine": "BU-OFFSHORE-06",
    "pipeline": "BU-OFFSHORE-06",
    "food safety": "BU-AGRI-07",
    "agri": "BU-AGRI-07",
    "automotive": "BU-AUTO-08",
    "battery": "BU-AUTO-08",
    "infrastructure": "BU-INFRA-09",
    "bridge": "BU-INFRA-09",
    "consumer": "BU-CONSUM-10",
    "emc": "BU-CONSUM-10",
}

CATEGORY_ALIASES = {
    "setup": "Setup & Integration Gaps",
    "integration": "Setup & Integration Gaps",
    "rate": "Setup & Integration Gaps",
    "orphan": "Setup & Integration Gaps",
    "efl": "Setup & Integration Gaps",
    "labor": "Labor & Timesheet Compliance",
    "timesheet": "Labor & Timesheet Compliance",
    "compliance": "Labor & Timesheet Compliance",
    "utilization": "Labor & Timesheet Compliance",
    "delivery": "Operational Delivery Risks",
    "overdue": "Operational Delivery Risks",
    "operational": "Operational Delivery Risks",
    "financial": "Financial & Margin Decay",
    "margin": "Financial & Margin Decay",
    "burn": "Financial & Margin Decay",
    "runaway": "Financial & Margin Decay",
}

WRITEBACK_TOOLS = {
    "log_remediation_action",
    "add_contract_comment",
    "assign_n1_action_or_task",
    "record_leadership_decision",
}


class AgentAnswer(BaseModel):
    status: str = "ok"
    answer_markdown: str = ""
    table_columns: list[str] = Field(default_factory=list)
    table_records: list[dict[str, Any]] = Field(default_factory=list)
    chart_spec: dict[str, Any] = Field(default_factory=dict)
    filters_used: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    sql_used: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _extract_contract_id(q: str) -> str | None:
    m = CONTRACT_ID_RE.search(q)
    return m.group(1).upper() if m else None


def _extract_exception_id(q: str) -> str | None:
    m = EXCEPTION_ID_RE.search(q)
    return m.group(1).upper() if m else None


def _extract_task_id(q: str) -> str | None:
    m = TASK_ID_RE.search(q)
    return m.group(1).upper() if m else None


def _extract_bu_id(q: str) -> str | None:
    m = BU_ID_RE.search(q)
    if m and m.group(1).upper() in ALL_BUSINESS_UNITS:
        return m.group(1).upper()
    ql = q.lower()
    for kw, code in BU_KEYWORDS.items():
        if kw in ql:
            return code
    return None


def _extract_contract_type(q: str) -> str | None:
    ql = q.lower()
    if any(p in ql for p in ("fixed-scope", "fixed scope", "fixed fee", " fs ")):
        return "FS"
    if any(p in ql for p in ("time & material", "time and material", "t&m", " tm ")):
        return "TM"
    if "sp-rev" in ql or "revenue-only" in ql:
        return "SP-REV"
    if "sp-cost" in ql or "cost-only" in ql or "holding pool" in ql:
        return "SP-COST"
    return None


def _extract_horizon(q: str) -> str | None:
    ql = q.lower()
    if any(p in ql for p in ("this week", "current week", "immediately", "today")):
        return "This Week"
    if any(p in ql for p in ("next month", "upcoming month", "december", "monthly plan")):
        return "Next Month"
    if any(p in ql for p in ("next week", "upcoming week", "weekly plan")):
        return "Next Week"
    return None


def _extract_assignee(q: str) -> str | None:
    ql = q.lower()
    # Check exact directory names first
    for name in sorted(TEAM_NAMES, key=lambda s: -len(s)):
        if name.lower() in ql:
            return name
    # Fallback pattern: "to <First Last>" or "for <First Last>"
    m = re.search(r"\b(?:to|instruct|delegate\s+to|assign\s+to)\s+([A-Z][a-zA-Z.]+(?:\s+[A-Z][a-zA-Z]+)?)", q)
    if m:
        cand = m.group(1).strip()
        if cand.lower() not in ("next", "this", "the", "a", "an", "clear", "freeze", "approve", "review"):
            return cand
    return None


def _extract_category(text: str) -> str | None:
    tl = text.strip().lower()
    if not tl or tl in ("all", "any"):
        return None
    for kw, canon in CATEGORY_ALIASES.items():
        if kw in tl:
            return canon
    return text.strip()


def _extract_impact_numbers(q: str) -> tuple[float, float]:
    hrs = 0.0
    usd = 0.0
    mh = HOURS_RE.search(q)
    if mh:
        hrs = float(mh.group(1))
    mu = USD_RE.search(q)
    if mu:
        usd = float(mu.group(1).replace(",", ""))
    return hrs, usd


def _strip_prefix_instruction(q: str, markers: tuple[str, ...]) -> str:
    if ":" in q:
        after = q.split(":", 1)[1].strip()
        if len(after) >= 6:
            return after
    for pat in markers:
        m = re.search(pat, q, flags=re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return q.strip()


def plan_deterministic(
    question: str,
    memory: dict[str, Any],
    ui_filters: dict[str, Any],
) -> tuple[str, dict[str, Any], list[str], list[str]]:
    """Resolve slash commands + natural language + UI filters + memory into an exact governed MCP tool call."""
    q = question.strip()
    ql = q.lower()
    applied: list[str] = []
    carried: list[str] = []

    # ------------------------------------------------------------------
    # 1. Exact Slash Commands (/summary, /exceptions, /trace, /log, /comment, /assign, /decide, /plan)
    # ------------------------------------------------------------------
    if ql.startswith("/summary"):
        rest = q[len("/summary") :].strip()
        bu = _extract_bu_id(rest) or ui_filters.get("bu_id")
        ctype = _extract_contract_type(f" {rest} ") or ui_filters.get("contract_type")
        if bu and not _extract_bu_id(rest):
            applied.append(f"Sidebar BU: {bu}")
        if ctype and not _extract_contract_type(f" {rest} "):
            applied.append(f"Sidebar Type: {ctype}")
        return "get_portfolio_summary", {"bu_id": bu, "contract_type": ctype}, applied, carried

    if ql.startswith("/exceptions"):
        rest = q[len("/exceptions") :].strip()
        lim = 10 if rest.lower() == "all" else 5
        cat = _extract_category(rest) if rest and rest.lower() != "all" else ui_filters.get("exception_family")
        bu = _extract_bu_id(rest) or ui_filters.get("bu_id")
        if bu and not _extract_bu_id(rest):
            applied.append(f"Sidebar BU: {bu}")
        return "get_exceptions_queue", {"category": cat, "bu_id": bu, "limit": lim}, applied, carried

    if ql.startswith("/trace"):
        rest = q[len("/trace") :].strip()
        cid = _extract_contract_id(rest) or (rest.split()[0].upper() if rest else memory.get("contract_id", ""))
        if cid and not rest and memory.get("contract_id"):
            carried.append(f"Contract: {cid}")
        return "trace_contract", {"contract_id": cid}, applied, carried

    if ql.startswith("/log"):
        rest = q[len("/log") :].strip()
        parts = rest.split(None, 1)
        ex_id = parts[0].upper() if parts else (memory.get("exception_id") or "")
        note = parts[1].strip() if len(parts) > 1 else ""
        horizon = _extract_horizon(note) or "Next Week"
        assignee = _extract_assignee(note)
        return "log_remediation_action", {"exception_id": ex_id, "action_note": note, "assigned_to": assignee, "plan_horizon": horizon}, applied, carried

    if ql.startswith("/comment"):
        rest = q[len("/comment") :].strip()
        cid = _extract_contract_id(rest) or memory.get("contract_id", "")
        note = re.sub(CONTRACT_ID_RE, "", rest, count=1).strip(" :-") if cid and _extract_contract_id(rest) else rest
        hrs, usd = _extract_impact_numbers(note)
        if cid and not _extract_contract_id(rest):
            carried.append(f"Contract: {cid}")
        return "add_contract_comment", {"contract_id": cid, "comment_text": note, "impact_hours": hrs, "impact_usd": usd}, applied, carried

    if ql.startswith("/assign"):
        rest = q[len("/assign") :].strip()
        cid = _extract_contract_id(rest)
        tid = _extract_task_id(rest)
        if not cid and not tid and memory.get("contract_id"):
            cid = memory["contract_id"]
            carried.append(f"Contract: {cid}")
        assignee = _extract_assignee(rest) or ""
        horizon = _extract_horizon(rest) or "Next Week"
        hrs, _ = _extract_impact_numbers(rest)
        # Extract instruction cleanly after assignee / horizon
        instr = rest
        for tok in (cid, tid, assignee):
            if tok:
                instr = re.sub(re.escape(tok), "", instr, count=1, flags=re.IGNORECASE)
        instr = re.sub(r"\b(?:to|for|next\s+week|this\s+week|next\s+month)\b", "", instr, flags=re.IGNORECASE).strip(" :-,")
        if not instr:
            instr = rest
        return "assign_n1_action_or_task", {
            "contract_id": cid,
            "task_id": tid,
            "assignee_name": assignee,
            "instruction": instr,
            "plan_horizon": horizon,
            "reallocated_hours": hrs,
        }, applied, carried

    if ql.startswith("/decide"):
        rest = q[len("/decide") :].strip()
        cid = _extract_contract_id(rest) or memory.get("contract_id", "")
        ex_id = _extract_exception_id(rest)
        rationale = re.sub(CONTRACT_ID_RE, "", rest, count=1).strip(" :-") if _extract_contract_id(rest) else rest
        if cid and not _extract_contract_id(rest):
            carried.append(f"Contract: {cid}")
        return "record_leadership_decision", {"contract_id": cid, "exception_id": ex_id, "rationale": rationale}, applied, carried

    if ql.startswith("/plan"):
        rest = q[len("/plan") :].strip()
        rl = rest.lower()
        horizon = _extract_horizon(rest)
        assignee = _extract_assignee(rest)
        cid = _extract_contract_id(rest)
        mode = "actions"
        if any(w in rl for w in ("comment", "note", "weather", "clarif")):
            mode = "comments"
        elif any(w in rl for w in ("assign", "task", "resource")):
            mode = "assignments"
        elif any(w in rl for w in ("decision", "buffer", "approve")):
            mode = "decisions"
        return "get_action_plan", {"plan_horizon": horizon, "assigned_to": assignee, "contract_id": cid, "view_mode": mode}, applied, carried

    # ------------------------------------------------------------------
    # 2. Natural-language entity extraction
    # ------------------------------------------------------------------
    q_cid = _extract_contract_id(q)
    q_exid = _extract_exception_id(q)
    q_tid = _extract_task_id(q)
    q_bu = _extract_bu_id(q)
    q_ctype = _extract_contract_type(f" {q} ")
    q_horizon = _extract_horizon(q)
    q_assignee = _extract_assignee(q)

    bu = q_bu or ui_filters.get("bu_id")
    if bu and not q_bu:
        applied.append(f"Sidebar BU: {bu}")
    ctype = q_ctype or ui_filters.get("contract_type")
    if ctype and not q_ctype:
        applied.append(f"Sidebar Type: {ctype}")

    # ------------------------------------------------------------------
    # 3. Natural-Language Write-Back Intents (Comments, N-1 Delegation, Task Assignment, Decisions)
    # ------------------------------------------------------------------
    # 3a. Contract Clarification / Weather / Scope Comment write-back
    if any(p in ql for p in (
        "add comment", "add a comment", "add note", "add a note", "write comment", "log comment",
        "clarification on", "note on ", "comment on ", "record weather", "log weather", "explain variance on",
        "save comment", "write back comment",
    )):
        cid = q_cid or memory.get("contract_id", "")
        if cid and not q_cid:
            carried.append(f"Contract: {cid}")
        note = _strip_prefix_instruction(q, (r"(?:that|saying|because)\s+(.+)$",))
        hrs, usd = _extract_impact_numbers(q)
        return "add_contract_comment", {"contract_id": cid, "comment_text": note, "impact_hours": hrs, "impact_usd": usd}, applied, carried

    # 3b. Business Leader Formal Decision write-back
    if any(p in ql for p in (
        "approve buffer", "approve a ", "approve weather", "approve cost buffer",
        "record decision", "log decision", "issue stop-work", "accept variance", "snooze exception",
    )) and (q_cid or q_exid or memory.get("contract_id")):
        cid = q_cid or memory.get("contract_id", "")
        if cid and not q_cid:
            carried.append(f"Contract: {cid}")
        return "record_leadership_decision", {"contract_id": cid, "exception_id": q_exid, "rationale": q}, applied, carried

    # 3c. N-1 Instruction / Task Assignment / Resource Reallocation write-back
    if any(p in ql for p in (
        "assign ", "instruct ", "delegate ", "tell ", "give instruction", "reallocate ", "task assignment",
    )) and (q_assignee or q_tid) and not any(w in ql for w in ("show ", "list ", "what ", "which ")):
        cid = q_cid or (None if q_tid else memory.get("contract_id"))
        if cid and not q_cid and not q_tid:
            carried.append(f"Contract: {cid}")
        hrs, _ = _extract_impact_numbers(q)
        return "assign_n1_action_or_task", {
            "contract_id": cid,
            "task_id": q_tid,
            "assignee_name": q_assignee or "",
            "instruction": _strip_prefix_instruction(q, (r"\bto\s+(?:freeze|clear|complete|rebalance|submit|approve|expedite|review|prepare|re-baseline)\b(.+)$",)),
            "plan_horizon": q_horizon or "Next Week",
            "reallocated_hours": hrs,
        }, applied, carried

    # 3d. Log remediation action on an exception
    if any(p in ql for p in ("log action", "log an action", "record remediation", "log commitment", "add action to cat")):
        ex_id = q_exid or memory.get("exception_id", "")
        note = _strip_prefix_instruction(q, (r"(?:note|comment|action)\s+(.+)$",))
        return "log_remediation_action", {"exception_id": ex_id, "action_note": note, "assigned_to": q_assignee, "plan_horizon": q_horizon or "Next Week"}, applied, carried

    # ------------------------------------------------------------------
    # 4. Read Action Plan / Comments / Assignments / Decisions / CAT Log
    # ------------------------------------------------------------------
    if any(p in ql for p in ("action plan", "weekly plan", "monthly plan", "upcoming week", "upcoming month", "n-1 instruction", "instructions assigned", "assigned to ")):
        return "get_action_plan", {"plan_horizon": q_horizon, "assigned_to": q_assignee, "contract_id": q_cid, "view_mode": "actions"}, applied, carried

    if any(p in ql for p in ("all comments", "contract comments", "comments on", "notes on", "clarifications on", "weather notes")):
        return "get_action_plan", {"contract_id": q_cid, "view_mode": "comments"}, applied, carried

    if any(p in ql for p in ("task assignments", "who is assigned", "resource reallocations")):
        return "get_action_plan", {"contract_id": q_cid, "assigned_to": q_assignee, "plan_horizon": q_horizon, "view_mode": "assignments"}, applied, carried

    if any(p in ql for p in ("leadership decisions", "executive decisions", "approved buffers", "decisions on")):
        return "get_action_plan", {"contract_id": q_cid, "view_mode": "decisions"}, applied, carried

    if any(p in ql for p in ("action log", "cat log", "remediation commitments", "logged actions", "fact_actionlog", "collaborative action tracker")):
        return "get_action_log", {"exception_id": q_exid, "contract_id": q_cid}, applied, carried

    # ------------------------------------------------------------------
    # 5. Core Analytical Intents
    # ------------------------------------------------------------------
    if any(p in ql for p in ("how is priority score", "priority scoring", "formula", "methodology", "9-view", "nine view", "join key", "relational schema", "vdm mapping", "how do fs and t&m")):
        return "get_methodology_and_lineage", {"topic": q}, applied, carried

    if any(p in ql for p in ("overhead", "lab burden", "laboratory burden", "cat-8000", "cat-9000", "facility rent", "depreciation", "120,000", "120k")):
        return "get_shared_overhead_allocation", {"bu_id": bu}, applied, carried

    if any(p in ql for p in ("integrity", "data quality", "unmatched_efl", "unmatched efl", "orphaned", "orphan", "missing rate", "reconciliation check", "cat 7x", "7x")):
        if q_cid:
            return "trace_contract", {"contract_id": q_cid}, applied, carried
        return "get_data_integrity_audit", {}, applied, carried

    if any(p in ql for p in ("utilization", "under-utilization", "unapproved", "billing lag", "pending timesheet", "unbilled wip", "disc-specialist", "unvalued hour", "timesheet compliance")):
        if q_cid and any(w in ql for w in ("trace", "audit", "why", "detail", "inspect")):
            return "trace_contract", {"contract_id": q_cid}, applied, carried
        return "get_labor_and_timesheet_compliance", {"bu_id": bu}, applied, carried

    if q_cid:
        if any(p in ql for p in ("special purpose", "sp-rev-901 and sp-cost-902", "both special")):
            return "get_contract_profitability", {"special_purpose_only": True}, applied, carried
        return "trace_contract", {"contract_id": q_cid}, applied, carried

    if any(p in ql for p in ("special purpose", "revenue-only", "cost-only", "volume rebate", "holding pool", "non-accessible margin")):
        return "get_contract_profitability", {"special_purpose_only": True}, applied, carried

    if any(p in ql for p in ("exception", "triage", "worst offender", "runaway", "overdue", "priority score", "risk queue", "what needs attention", "what is broken")):
        cat = _extract_category(q) if any(k in ql for k in CATEGORY_ALIASES) else ui_filters.get("exception_family")
        lim = 10 if "all exception" in ql else 5
        return "get_exceptions_queue", {"category": cat, "bu_id": bu, "limit": lim}, applied, carried

    if any(p in ql for p in ("bottom", "underperform", "lowest margin", "negative margin", "worst margin")):
        return "get_contract_profitability", {"bu_id": bu, "contract_type": ctype, "bottom_only": True}, applied, carried

    if any(p in ql for p in ("all contracts", "contract list", "profitability", "contract margin", "fixed-scope contract", "t&m contract")):
        return "get_contract_profitability", {"bu_id": bu, "contract_type": ctype, "bottom_only": False}, applied, carried

    if any(p in ql for p in ("trace it", "audit it", "this contract", "that contract")) and memory.get("contract_id"):
        carried.append(f"Contract: {memory['contract_id']}")
        return "trace_contract", {"contract_id": memory["contract_id"]}, applied, carried

    return "get_portfolio_summary", {"bu_id": bu, "contract_type": ctype}, applied, carried


def _build_followups(payload: ToolPayload) -> list[str]:
    t = payload.tool_name
    if t == "get_portfolio_summary":
        return [
            "/exceptions",
            "/trace FS-AERO-104",
            "/plan next week",
        ]
    if t == "get_exceptions_queue":
        return [
            "/trace FS-AERO-104",
            "/comment FS-OFFSHORE-108 Storm delayed offshore mobilization by 3 days; include weather contingency",
            "/assign FS-AERO-104 to Jordan Vance next week Freeze overtime and deliver SkyForge change order",
        ]
    if t == "trace_contract":
        cid = payload.extra.get("contract_id", "FS-AERO-104")
        exs = payload.extra.get("exception_ids") or []
        f1 = f"/comment {cid} Field clarification: weather/scope variance documented for next month review"
        f2 = f"/assign {cid} to Jordan Vance next week Review burn variance and re-baseline remaining milestones"
        f3 = f"/log {exs[0]} Escalated for immediate margin recovery" if exs else "/plan next week"
        return [f1, f2, f3]
    if t in WRITEBACK_TOOLS:
        cid = payload.extra.get("contract_id", "FS-AERO-104")
        return [f"/trace {cid}", "/plan next week", "/plan comments"]
    if t == "get_action_plan":
        return ["/plan comments", "/plan assignments", "/exceptions"]
    if t == "get_shared_overhead_allocation":
        return ["/summary", "Show Special Purpose contracts SP-REV-901 and SP-COST-902", "/exceptions Financial"]
    if t == "get_labor_and_timesheet_compliance":
        return ["/trace TM-RENEW-202", "/trace TM-ENV-401", "/assign TM-ENV-401 to Jordan Vance next month Rebalance 40 hrs to billable panels"]
    return ["/summary", "/exceptions", "/plan next week"]


def ask(
    question: str,
    *,
    user_id: str = "bu_director",
    user_name: str | None = None,
    memory: dict[str, Any] | None = None,
    model: str | None = "rules",
    as_of: date | None = None,
    ui_filters: dict[str, Any] | None = None,
) -> tuple[AgentAnswer, dict[str, Any]]:
    t0 = time.time()
    req_id = str(uuid.uuid4())[:8]
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    mem = dict(memory or {})
    uif = dict(ui_filters or {})
    use_rules = (not model) or str(model).lower().startswith("rules")

    # 1. Fail-closed safety guardrail
    unsafe_msg = G.check_prompt_safety(question)
    if unsafe_msg:
        return AgentAnswer(
            status="refusal",
            answer_markdown=unsafe_msg,
            filters_used={"topic": "Security Policy", "persona": scope.display_name, "rls": scope.scope_label, "as_of_date": as_of.isoformat()},
            followups=["/summary", "/exceptions", "/plan next week"],
            diagnostics={"request_id": req_id, "via_mcp": False, "guardrail": {"ok": True, "blocked": True}, "model": model or "rules", "latency_s": round(time.time() - t0, 2)},
        ), mem

    # 2. Out-of-scope domain guardrail
    oos_msg = G.check_out_of_scope(question)
    if oos_msg:
        return AgentAnswer(
            status="unsupported",
            answer_markdown=f"**Out of TIC Portfolio Margin Scope:** {oos_msg}\n\nApex Margin Advisor governs **OWMS contracts/milestones**, **GTE timesheets**, **CRC rate cards**, **EFL general ledger & shared lab overhead**, and **CAT write-back action plans & comments**.",
            filters_used={"topic": "Scope Boundary", "persona": scope.display_name, "rls": scope.scope_label, "as_of_date": as_of.isoformat()},
            followups=["/summary", "/exceptions", "/plan next week"],
            diagnostics={"request_id": req_id, "via_mcp": False, "guardrail": {"ok": True, "out_of_scope": True}, "model": model or "rules", "latency_s": round(time.time() - t0, 2)},
        ), mem

    # 3. Deterministic semantic plan + optional LLM tool-calling pass
    det_tool, det_args, applied, carried = plan_deterministic(question, mem, uif)
    chosen_tool, chosen_args = det_tool, dict(det_args)
    tool_source = "rules"
    llm_error_note = None
    is_slash = question.strip().startswith("/")

    if not use_rules and not is_slash:
        try:
            router_msgs = [
                {"role": "system", "content": TOOL_ROUTER_SYSTEM},
                {"role": "user", "content": f"Persona: {scope.display_name}\nContext memory: {mem}\nSidebar filters: {uif}\nQuestion: {question}"},
            ]
            r_res = llm.chat(router_msgs, tools=TOOL_SCHEMAS, model=model, max_tokens=500)
            if r_res.tool_calls:
                cand = r_res.tool_calls[0]
                cname = cand.get("name")
                cargs = cand.get("arguments") or {}
                critical_det = det_tool in WRITEBACK_TOOLS or det_tool in ("trace_contract", "get_data_integrity_audit")
                if cname in ALLOWED_TOOLS and not critical_det:
                    chosen_tool = cname
                    merged = dict(det_args)
                    for k, v in cargs.items():
                        if v not in (None, ""):
                            merged[k] = v
                    chosen_args = merged
                    tool_source = f"llm ({r_res.model})"
                else:
                    tool_source = f"llm+semantic_guard ({r_res.model})"
        except PermissionError as exc:
            llm_error_note = f"AI unavailable — {exc} Falling back to governed deterministic engine."
            use_rules = True
        except Exception as exc:  # noqa: BLE001
            llm_error_note = f"Model connection notice ({type(exc).__name__}); served from governed deterministic engine."
            use_rules = True

    # 4. Execute through the governed MCP tool boundary
    payload = invoke_tool(
        chosen_tool,
        chosen_args,
        user_id=user_id,
        user_name=user_name,
        as_of=as_of,
        via_mcp=True,
    )

    # 5. Generate persona-adapted executive prose (verified by numeric & anomaly guardrails)
    guard_info: dict[str, Any] = {"ok": True, "template": True, "reason": "deterministic_rules"}
    if use_rules or payload.status != "ok" or chosen_tool in WRITEBACK_TOOLS:
        prose = G.deterministic_prose(payload)
        if llm_error_note:
            prose = f"> **{llm_error_note}**\n\n{prose}"
    else:
        try:
            sanitized_context = (
                f"PERSONA: {scope.display_name} ({scope.tone})\n"
                f"QUESTION: {question}\n"
                f"TOOL: {payload.tool_name}\n"
                f"PERIOD: {payload.period_label}\n"
                f"HEADLINE: {payload.headline}\n"
                f"FACTS:\n" + "\n".join(f"- {f}" for f in payload.facts) + "\n"
                f"WARNINGS:\n" + "\n".join(f"- {w}" for w in payload.warnings)
            )
            w_res = llm.chat(
                [
                    {"role": "system", "content": ANSWER_WRITER_SYSTEM},
                    {"role": "user", "content": sanitized_context},
                ],
                model=model,
                max_tokens=450,
            )
            verdict = G.verify_prose(w_res.content, payload)
            if verdict.ok:
                prose = w_res.content
                for w in payload.warnings[:2]:
                    if w not in prose:
                        prose += f"\n\n> **Integrity & Risk Alert:** {w}"
                guard_info = {"ok": True, "template": False, "reason": "verified_llm_prose"}
            else:
                prose = G.deterministic_prose(payload)
                guard_info = {"ok": True, "template": True, "reason": verdict.reason}
        except Exception as exc:  # noqa: BLE001
            prose = G.deterministic_prose(payload)
            guard_info = {"ok": True, "template": True, "reason": f"writer_fallback:{type(exc).__name__}"}

    # 6. Update conversation memory
    new_mem = dict(mem)
    if payload.status == "ok":
        if chosen_args.get("contract_id") or payload.extra.get("contract_id"):
            new_mem["contract_id"] = chosen_args.get("contract_id") or payload.extra.get("contract_id")
        if chosen_args.get("bu_id") or payload.extra.get("bu_id"):
            new_mem["bu_id"] = chosen_args.get("bu_id") or payload.extra.get("bu_id")
        if chosen_args.get("exception_id"):
            new_mem["exception_id"] = chosen_args["exception_id"]
        elif payload.extra.get("exception_ids"):
            new_mem["exception_id"] = payload.extra["exception_ids"][0]
        new_mem["last_tool"] = chosen_tool
        new_mem["last_question"] = question

    cols = list(payload.df.columns) if payload.df is not None and not payload.df.empty else []
    recs = payload.df.to_dict(orient="records") if cols else []

    f_used = dict(payload.filters_used or {})
    f_used.update({
        "topic": payload.topic_label or chosen_tool,
        "period": payload.period_label,
        "persona": scope.display_name,
        "rls": scope.scope_label,
        "as_of_date": as_of.isoformat(),
        "applied": applied,
        "carried_over": carried,
    })

    ans = AgentAnswer(
        status=payload.status,
        answer_markdown=prose,
        table_columns=cols,
        table_records=recs,
        chart_spec=payload.chart_spec or {},
        filters_used=f_used,
        warnings=payload.warnings or [],
        sql_used=[payload.compiled_sql] if payload.compiled_sql else [],
        followups=_build_followups(payload),
        diagnostics={
            "request_id": req_id,
            "via_mcp": payload.via_mcp,
            "tool_calls": [{"name": chosen_tool, "arguments": chosen_args}],
            "tool_choice_source": tool_source,
            "lineage_id": payload.lineage_id,
            "guardrail": guard_info,
            "model": "rules" if use_rules else model,
            "latency_s": round(time.time() - t0, 2),
            "context_contract_id": payload.extra.get("contract_id") or chosen_args.get("contract_id"),
            "context_exception_ids": payload.extra.get("exception_ids") or [],
            "context_task_ids": payload.extra.get("task_ids") or [],
        },
    )
    return ans, new_mem

"""Governed Model Context Protocol (MCP) tool & resource server for Apex Margin Advisor.

Exposes:
  * 5 metadata resources (`apex://metadata/project`, `modules`, `methodologies`, `priority-scoring`, `join-keys`)
  * 14 typed semantic & CAT write-back tools covering `/summary`, `/exceptions`, `/trace`, `/log`,
    `/comment`, `/assign`, `/decide`, `/plan`, profitability, shared lab overhead, labor compliance,
    data integrity, CAT action log, and methodology/lineage.

Supports JSON-RPC 2.0 over stdio (`python -m mcp_server.server`) AND direct local dispatch (`invoke_tool`).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any

from app.config import as_of_date, settings
from app.semantic import service as S

MCP_RESOURCES = {
    "apex://metadata/project": lambda: {
        "product": settings()["app_name"],
        "full_name": settings()["app_full_name"],
        "synthetic_demo": True,
        "views": 9,
        "cat_writeback_tables": 4,
    },
    "apex://metadata/modules": lambda: S.semantic_catalog()["modules"],
    "apex://metadata/methodologies": lambda: S.semantic_catalog()["contract_methodologies"],
    "apex://metadata/priority-scoring": lambda: S.semantic_catalog()["priority_scoring"],
    "apex://metadata/join-keys": lambda: S.semantic_catalog()["join_keys"],
}

ALLOWED_TOOLS = {
    "get_portfolio_summary",
    "get_exceptions_queue",
    "trace_contract",
    "log_remediation_action",
    "add_contract_comment",
    "assign_n1_action_or_task",
    "record_leadership_decision",
    "get_action_plan",
    "get_contract_profitability",
    "get_shared_overhead_allocation",
    "get_labor_and_timesheet_compliance",
    "get_data_integrity_audit",
    "get_action_log",
    "get_methodology_and_lineage",
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_summary",
            "description": "Executive KPI summary (/summary) tailored to active persona: MTD Recognized vs Target Revenue, Portfolio Provisional & Net Operating Margin %, Hours Awaiting Approval, and Active Exceptions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bu_id": {"type": "string", "description": "Optional Business Unit code, e.g. BU-AERO-02"},
                    "contract_type": {"type": "string", "enum": ["FS", "TM", "SP-REV", "SP-COST"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exceptions_queue",
            "description": "Prioritized open exceptions queue (/exceptions [category]) sorted by Priority Score (0–100) descending. Top 5 worst offenders by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Optional family: Setup & Integration Gaps | Labor & Timesheet Compliance | Operational Delivery Risks | Financial & Margin Decay"},
                    "bu_id": {"type": "string"},
                    "contract_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trace_contract",
            "description": "Execute a 5-point OWMS -> GTE -> CRC -> EFL -> Provisional Margin audit trace (/trace <contract_id>) including written-back contract comments, N-1 directives, task assignments, and leadership decisions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contract_id": {"type": "string", "description": "Contract ID e.g. FS-AERO-104, TM-RENEW-202, FS-AUTO-305, TM-ENV-401, SP-REV-901, SP-COST-902"},
                },
                "required": ["contract_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_remediation_action",
            "description": "Record a formalized remediation commitment (/log <exception_id> <action_note>) directly into CAT (Fact_ActionLog).",
            "parameters": {
                "type": "object",
                "properties": {
                    "exception_id": {"type": "string", "description": "Exception ID e.g. EXC-101"},
                    "action_note": {"type": "string", "description": "Manager remediation commitment comment"},
                    "assigned_to": {"type": "string", "description": "Optional N-1 reportee name"},
                    "plan_horizon": {"type": "string", "enum": ["This Week", "Next Week", "Next Month"], "default": "Next Week"},
                    "target_resolution_date": {"type": "string", "description": "Optional YYYY-MM-DD"},
                },
                "required": ["exception_id", "action_note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_contract_comment",
            "description": "Write a contract/project context or clarification comment (/comment <contract_id> <note>) into the database — e.g., weather/natural event delays, cost underestimation, client holds, or overhead buffers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contract_id": {"type": "string", "description": "Target contract ID e.g. FS-OFFSHORE-108"},
                    "comment_text": {"type": "string", "description": "Operational explanation or context note"},
                    "category": {"type": "string", "enum": ["Weather / Natural Event", "Cost / Scope Clarification", "Client Delay", "Resource Bottleneck", "General Note"]},
                    "impact_hours": {"type": "number", "default": 0},
                    "impact_usd": {"type": "number", "default": 0},
                },
                "required": ["contract_id", "comment_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_n1_action_or_task",
            "description": "Delegate an N-1 instruction, assign an unassigned/open task, or record a resource reallocation (/assign <contract_or_task> to <reportee> [next week|next month] <instruction>) into the database action plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contract_id": {"type": "string"},
                    "task_id": {"type": "string", "description": "Optional task UUID e.g. TSK-0112-1"},
                    "assignee_name": {"type": "string", "description": "Reportee / technician name e.g. Jordan Vance, T. Sato"},
                    "instruction": {"type": "string"},
                    "plan_horizon": {"type": "string", "enum": ["This Week", "Next Week", "Next Month"], "default": "Next Week"},
                    "reallocated_hours": {"type": "number", "default": 0},
                    "target_resolution_date": {"type": "string"},
                },
                "required": ["assignee_name", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_leadership_decision",
            "description": "Record an official Business Leader decision (/decide <contract_id> <rationale>) — e.g., approve cost/weather buffer, accept variance, or authorize scope renegotiation (BU Manager role only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "contract_id": {"type": "string"},
                    "decision_type": {"type": "string", "enum": ["Approve Cost / Weather Buffer", "Client Scope Renegotiation", "Accept Variance (Time-Bound)", "Snooze Exception", "Stop-Work Order"]},
                    "rationale": {"type": "string"},
                    "exception_id": {"type": "string"},
                    "effective_until": {"type": "string"},
                },
                "required": ["contract_id", "rationale"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_action_plan",
            "description": "Retrieve the weekly/monthly Action Plan (/plan [horizon|reportee|contract]), N-1 delegated instructions, contract clarification comments, task assignments, or leadership decisions from the CAT database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_horizon": {"type": "string", "enum": ["This Week", "Next Week", "Next Month"]},
                    "assigned_to": {"type": "string"},
                    "contract_id": {"type": "string"},
                    "view_mode": {"type": "string", "enum": ["actions", "comments", "assignments", "decisions"], "default": "actions"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_contract_profitability",
            "description": "Compare contract profitability across Fixed-Scope (FS), Time & Materials (T&M), bottom underperformers, or Special Purpose (SP-REV / SP-COST with N/A margin).",
            "parameters": {
                "type": "object",
                "properties": {
                    "bu_id": {"type": "string"},
                    "contract_type": {"type": "string", "enum": ["FS", "TM", "SP-REV", "SP-COST"]},
                    "bottom_only": {"type": "boolean", "default": False},
                    "special_purpose_only": {"type": "boolean", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_shared_overhead_allocation",
            "description": "Show the $120,000 monthly shared laboratory overhead (Cat-8000 Facility & Cat-9000 Equipment Depreciation) allocated across the 10 BUs and resulting Net Operating Margin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bu_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_labor_and_timesheet_compliance",
            "description": "Inspect T&M billable utilization (<80% alerts), timesheets pending approval > 7 business days (unbilled WIP), and unmapped CRC discipline rate hours.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bu_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_data_integrity_audit",
            "description": "Audit master data reconciliation failures: unmatched_efl_record, task_missing_rate_link, orphaned_fee_structure, invalid_task_dates, and Category 7x GL review items.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_action_log",
            "description": "Retrieve remediation commitments recorded in CAT (Fact_ActionLog).",
            "parameters": {
                "type": "object",
                "properties": {
                    "exception_id": {"type": "string"},
                    "contract_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_methodology_and_lineage",
            "description": "Explain FS vs. T&M revenue/margin formulas, Special Purpose N/A handling, Priority Scoring rubric, 9-view relational joins, and VWM/CORE/FLEX/JDE mapping.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "default": "ALL"},
                },
            },
        },
    },
]


def invoke_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    user_id: str = "bu_director",
    user_name: str | None = None,
    as_of: date | None = None,
    via_mcp: bool = True,
) -> S.ToolPayload:
    if name not in ALLOWED_TOOLS:
        return S.ToolPayload(
            status="refusal",
            tool_name=name,
            headline=f"Tool `{name}` is not in the Apex Margin Advisor governed allowlist.",
            via_mcp=via_mcp,
        )
    args = dict(arguments or {})
    eff_as_of = as_of or as_of_date()

    dispatch = {
        "get_portfolio_summary": lambda: S.get_portfolio_summary(
            bu_id=args.get("bu_id"),
            contract_type=args.get("contract_type"),
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "get_exceptions_queue": lambda: S.get_exceptions_queue(
            category=args.get("category"),
            bu_id=args.get("bu_id"),
            contract_id=args.get("contract_id"),
            limit=int(args.get("limit", 5) or 5),
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "trace_contract": lambda: S.trace_contract(
            contract_id=str(args.get("contract_id") or ""),
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "log_remediation_action": lambda: S.log_remediation_action(
            exception_id=str(args.get("exception_id") or ""),
            action_note=str(args.get("action_note") or ""),
            assigned_to=args.get("assigned_to"),
            plan_horizon=str(args.get("plan_horizon") or "Next Week"),
            target_resolution_date=args.get("target_resolution_date"),
            user_id=user_id,
            user_name=user_name,
            as_of=eff_as_of,
        ),
        "add_contract_comment": lambda: S.add_contract_comment(
            contract_id=str(args.get("contract_id") or ""),
            comment_text=str(args.get("comment_text") or ""),
            category=args.get("category"),
            impact_hours=float(args.get("impact_hours") or 0.0),
            impact_usd=float(args.get("impact_usd") or 0.0),
            user_id=user_id,
            user_name=user_name,
            as_of=eff_as_of,
        ),
        "assign_n1_action_or_task": lambda: S.assign_n1_action_or_task(
            contract_id=args.get("contract_id"),
            task_id=args.get("task_id"),
            assignee_name=str(args.get("assignee_name") or ""),
            instruction=str(args.get("instruction") or ""),
            plan_horizon=str(args.get("plan_horizon") or "Next Week"),
            reallocated_hours=float(args.get("reallocated_hours") or 0.0),
            target_resolution_date=args.get("target_resolution_date"),
            user_id=user_id,
            user_name=user_name,
            as_of=eff_as_of,
        ),
        "record_leadership_decision": lambda: S.record_leadership_decision(
            contract_id=str(args.get("contract_id") or ""),
            decision_type=args.get("decision_type"),
            rationale=str(args.get("rationale") or ""),
            exception_id=args.get("exception_id"),
            effective_until=args.get("effective_until"),
            user_id=user_id,
            user_name=user_name,
            as_of=eff_as_of,
        ),
        "get_action_plan": lambda: S.get_action_plan(
            plan_horizon=args.get("plan_horizon"),
            assigned_to=args.get("assigned_to"),
            contract_id=args.get("contract_id"),
            view_mode=str(args.get("view_mode") or "actions"),
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "get_contract_profitability": lambda: S.get_contract_profitability(
            bu_id=args.get("bu_id"),
            contract_type=args.get("contract_type"),
            bottom_only=bool(args.get("bottom_only", False)),
            special_purpose_only=bool(args.get("special_purpose_only", False)),
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "get_shared_overhead_allocation": lambda: S.get_shared_overhead_allocation(
            bu_id=args.get("bu_id"),
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "get_labor_and_timesheet_compliance": lambda: S.get_labor_and_timesheet_compliance(
            bu_id=args.get("bu_id"),
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "get_data_integrity_audit": lambda: S.get_data_integrity_audit(
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "get_action_log": lambda: S.get_action_log(
            exception_id=args.get("exception_id"),
            contract_id=args.get("contract_id"),
            user_id=user_id,
            as_of=eff_as_of,
        ),
        "get_methodology_and_lineage": lambda: S.get_methodology_and_lineage(
            topic=str(args.get("topic") or "ALL"),
            user_id=user_id,
            as_of=eff_as_of,
        ),
    }
    payload = dispatch[name]()
    payload.via_mcp = via_mcp
    return payload


def handle_jsonrpc(req: dict[str, Any]) -> dict[str, Any]:
    """Minimal JSON-RPC 2.0 handler for stdio MCP clients."""
    rid = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "apex-margin-advisor-mcp", "version": "1.1.0"},
                "capabilities": {"tools": {}, "resources": {}},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "tools": [
                    {
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "inputSchema": t["function"]["parameters"],
                    }
                    for t in TOOL_SCHEMAS
                ]
            },
        }
    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"resources": [{"uri": u, "name": u} for u in MCP_RESOURCES]},
        }
    if method == "resources/read":
        uri = params.get("uri", "")
        if uri not in MCP_RESOURCES:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"Unknown resource: {uri}"}}
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(MCP_RESOURCES[uri](), default=str)}]},
        }
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        user_id = args.pop("user_id", "bu_director")
        user_name = args.pop("user_name", None)
        payload = invoke_tool(name, args, user_id=user_id, user_name=user_name, via_mcp=True)
        body = {
            "status": payload.status,
            "headline": payload.headline,
            "facts": payload.facts,
            "warnings": payload.warnings,
            "rows": payload.df.to_dict(orient="records") if payload.df is not None and not payload.df.empty else [],
        }
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"content": [{"type": "text", "text": json.dumps(body, default=str)}]},
        }
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unsupported method: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_jsonrpc(req)
        except Exception as exc:  # noqa: BLE001
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(exc)}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

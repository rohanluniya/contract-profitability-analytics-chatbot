"""Shared UI helpers for Apex Margin Advisor: CSS, header, sign-in, conversation history, and answer rendering."""
from __future__ import annotations

import base64
import html
import json
import re

import pandas as pd
import streamlit as st

from app.config import env, settings
from app.ui import branding as B
from app.viz.charts import figure
from app.viz.tables import TABLE_CSS, render_html, to_csv_bytes, to_excel_bytes

PERSONAS = {
    k: v["user_id"] for k, v in settings().get("personas", {}).items()
}

WELCOME_EXAMPLES = [
    "/summary",
    "/exceptions",
    "/trace FS-OFFSHORE-108",
]

DEMO_JOURNEY_EXAMPLES = [
    "/summary",
    "/exceptions",
    "/trace FS-AERO-104",
    "/comment FS-OFFSHORE-108 Severe winter storm delayed offshore mobilization by 4 days; add weather contingency for next month",
    "/assign FS-AERO-104 to Jordan Vance next week Freeze overtime and deliver SkyForge change-order quote",
    "/plan next week",
]

GOVERNANCE_EXAMPLES = [
    "/assign TSK-0112-1 to T. Sato next week Clear overdue EMC radiated emissions pre-scan",
    "/decide FS-OFFSHORE-108 Approve 15% storm weather buffer and accept burn variance through 2026-12-05",
    "/plan comments",
    "How is the $120,000 shared laboratory overhead allocated across Business Units?",
    "Show Special Purpose contracts SP-REV-901 and SP-COST-902",
    "Run a master data integrity check for unmatched EFL records and orphaned fees",
]

CSS = """
<style>
[data-testid="stMainBlockContainer"], .block-container {padding-top: 3.5rem; max-width: 1380px;}
[data-testid="stSidebar"] {min-width: 345px;}
.ax-head {display:flex; align-items:center; justify-content:space-between; gap:14px; padding: 11px 18px;
          border-radius: 12px; background: linear-gradient(90deg, #065F46 0%, #1E3A8A 100%);
          color:#fff; margin-bottom: 8px;}
.ax-head-left {display:flex; align-items:center; gap:14px;}
.ax-head img {width: 50px; height: 50px; background:#fff; border-radius: 50%; padding: 3px;}
.ax-head .name {font-size: 1.5rem; font-weight: 800; letter-spacing: 0.03em; margin: 0; line-height: 1.15;}
.ax-head .sub {font-size: 0.84rem; opacity: 0.90; margin-top: 3px;}
.ax-head .persona-pill {background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.32);
                        border-radius: 999px; padding: 5px 12px; font-size: 0.78rem; font-weight: 700;}
.ax-banner {background: #FFF4E5; border: 1px solid #F5B041; color: #7E5109; padding: 6px 12px; border-radius: 8px;
            font-size: 0.84rem; margin-bottom: 10px;}
.ax-scope {font-size: 0.8rem; color: #475569; margin-bottom: 4px;}
.ax-chip {display:inline-block; background:#ECFDF5; color:#065F46; border-radius:12px; padding:2px 10px;
          margin:2px 4px 2px 0; font-size:0.78rem; font-weight:600;}
.ax-chip.filter {background:#EFF6FF; color:#1E3A8A;}
.ax-chip.mcp {background:#F0FDF4; color:#166534; border:1px solid #BBF7D0;}
div[data-testid="stChatMessage"] {background: #FFFFFF;}
.stButton>button {border-radius: 8px; border: 1px solid #CBD5E1; text-align: left; white-space: normal;
                  height: auto; padding: 0.45rem 0.72rem; font-size: 0.84rem;}
.stButton>button p {white-space: normal !important; overflow: visible !important; text-overflow: clip !important;}
.stButton>button:hover {border-color: #065F46; color: #065F46;}
.ax-kpi-card {border:1px solid #E2E8F0; border-top: 3px solid #065F46; border-radius:10px; padding:12px 14px;
              background:#FFFFFF; box-shadow: 0 1px 2px rgba(15,23,42,0.04); min-height: 132px;
              display: flex; flex-direction: column; justify-content: space-between; white-space: normal;}
.ax-kpi-card.risk {border-top-color: #B91C1C;}
.ax-kpi-card.warn {border-top-color: #D97706;}
.ax-kpi-card.blue {border-top-color: #1E3A8A;}
.ax-kpi-card .k-title {font-size:0.77rem; font-weight:700; color:#334155; text-transform:uppercase; letter-spacing:0.03em;}
.ax-kpi-card .k-val {font-size:1.48rem; font-weight:800; color:#0B1F3A; margin:3px 0;}
.ax-kpi-card .k-period {font-size:0.76rem; color:#065F46; font-weight:600;}
.ax-kpi-card.risk .k-period {color:#B91C1C;}
.ax-kpi-card.warn .k-period {color:#B45309;}
.ax-kpi-card .k-sub {font-size:0.75rem; color:#64748B; margin-top:4px; line-height:1.36; white-space: normal;}
</style>
"""

MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~<])")


def esc(text) -> str:
    return html.escape("" if text is None else str(text))


def md_escape(text) -> str:
    return MD_SPECIAL.sub(r"\\\1", "" if text is None else str(text))


def logo_data_uri() -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(B.LOGO_PATH.read_bytes()).decode()


def apply_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def init_state() -> None:
    default_persona = next(iter(PERSONAS.keys()), "Operations Portfolio Director (BU Manager)")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("memory", {})
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("persona", default_persona)
    st.session_state.setdefault("active_cid", None)
    st.session_state.setdefault("welcome_dismissed", False)
    st.session_state.setdefault("model_param", str(st.query_params.get("model", "")).strip().lower())


def model_choices() -> list[str]:
    current = env("LLM_MODEL", "rules") or "rules"
    raw = env("LLM_MODEL_CHOICES", "ollama/qwen2.5-coder:14b,ollama/gpt-oss:20b,gemini/gemini-2.5-flash,openai/gpt-4o-mini") or ""
    out = ["rules (no LLM)"]
    if not current.lower().startswith("rules"):
        out = [current] + out
    for m in raw.split(","):
        m = m.strip()
        if m and m not in out and not m.lower().startswith("rules"):
            out.append(m)
    return out


def header() -> None:
    persona_lbl = st.session_state.get("persona", "Operations Portfolio Director (BU Manager)")
    st.markdown(
        f"<div class='ax-head'>"
        f"<div class='ax-head-left'><img src='{logo_data_uri()}' alt='{esc(B.APP_NAME)} logo'/>"
        f"<div><div class='name'>{esc(B.APP_NAME)}</div>"
        f"<div class='sub'>{esc(B.APP_FULL_NAME)}</div></div></div>"
        f"<div class='persona-pill'>{esc(persona_lbl)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='ax-banner'>⚠️ <b>Synthetic TIC benchmark dataset (10 BUs · 20 Contracts · 9 Views) — prototype for demonstration only.</b> "
        "OWMS, EFL, GTE, CRC & CAT represent fictional organizations, contracts, and financial figures.</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sign-in gate
# ---------------------------------------------------------------------------
def signed_in() -> bool:
    return bool(st.session_state.get("auth_user"))


def sign_in(display_name: str, code: str) -> str | None:
    import hmac
    from app.history.store import normalize_user

    uid = normalize_user(display_name)
    if not uid:
        return "Please enter your display name."
    expected = env("APP_ACCESS_CODE", "apex-demo-2026")
    if not expected:
        return "Sign-in is not configured: set APP_ACCESS_CODE in .env."
    if not hmac.compare_digest(str(code or "").encode(), str(expected).encode()):
        return "The access code is not correct."
    st.session_state["auth_user"] = uid
    st.session_state["auth_name"] = display_name.strip()[:80]
    return None


def sign_out() -> None:
    for k in ("auth_user", "auth_name", "active_cid", "welcome_dismissed"):
        st.session_state.pop(k, None)
    st.session_state.messages, st.session_state.memory = [], {}


def login_page() -> None:
    header()
    st.markdown(f"### Sign in to {B.APP_NAME}")
    with st.form("login", clear_on_submit=False):
        name = st.text_input("Your name", max_chars=80, placeholder="e.g. Jordan Vance")
        code = st.text_input("Access code", type="password", placeholder="Default local demo code: apex-demo-2026")
        ok = st.form_submit_button("Sign in", type="primary")
    if ok:
        err = sign_in(name, code)
        if err:
            st.error(err)
        else:
            st.rerun()
    st.caption(
        "Demo sign-in separates your conversation history and tags your CAT (`/log`) remediation commitments. "
        "Production deployments bind corporate SSO (Microsoft Entra ID) to Row-Level Security."
    )
    st.caption(B.footer_line())


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------
def history_store():
    try:
        from app.history.store import ConversationStore
        return ConversationStore()
    except Exception:  # noqa: BLE001
        return None


def new_conversation() -> None:
    st.session_state.messages, st.session_state.memory = [], {}
    st.session_state.active_cid = None


def open_conversation(cid: str) -> None:
    store = history_store()
    user = st.session_state.get("auth_user")
    if store is None or not user:
        return
    conv, msgs, state = store.load(user, cid)
    if conv is None:
        return
    for m in msgs:
        if m.get("role") == "assistant":
            m.setdefault("answer", {}).setdefault("diagnostics", {})["resumed"] = True
    st.session_state.messages = msgs
    st.session_state.memory = state.get("memory") or {}
    st.session_state.active_cid = conv.conversation_id
    if conv.persona in PERSONAS:
        st.session_state["restore_persona"] = conv.persona
    if state.get("ui_widgets"):
        st.session_state["restore_filters"] = state["ui_widgets"]


def apply_restored_filters() -> None:
    persona = st.session_state.pop("restore_persona", None)
    if persona in PERSONAS:
        st.session_state.persona = persona
        st.session_state["persona_select"] = persona
    pending = st.session_state.pop("restore_filters", None)
    if pending is None:
        return
    from app.ui.sidebar import FILTER_KEYS, clear_filters
    clear_filters()
    for k in FILTER_KEYS:
        if pending.get(k) not in (None, [], "", "All in scope", "All Types", "All Families"):
            st.session_state[k] = pending[k]


def save_turn(question: str, payload: dict, memory: dict, cfg: dict) -> str | None:
    from app.history.store import ConversationLimit
    from app.ui.sidebar import FILTER_KEYS

    store = history_store()
    user = st.session_state.get("auth_user")
    if store is None or not user:
        return None
    try:
        state_blob = {
            "memory": memory,
            "persona": st.session_state.persona,
            "ui_filters": cfg.get("ui_filters") or {},
            "ui_widgets": {k: st.session_state.get(k) for k in FILTER_KEYS},
        }
        cid = store.save_turn(
            user_id=user,
            cid=st.session_state.get("active_cid"),
            persona=st.session_state.persona,
            question=question,
            payload=payload,
            memory=state_blob,
        )
        st.session_state.active_cid = cid
    except ConversationLimit as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return f"History note: conversation could not be saved ({type(exc).__name__})."
    return None


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def chips(values: list[str], kind: str = "") -> None:
    vals = [v for v in values if v]
    if vals:
        cls = f"ax-chip {kind}".strip()
        st.markdown("".join(f"<span class='{cls}'>{esc(v)}</span>" for v in vals), unsafe_allow_html=True)


def queue_page(name: str, question: str | None = None) -> None:
    if question:
        st.session_state.pending = question
    st.session_state.nav_goto = name


def ask_button(label: str, question: str, key: str) -> None:
    st.button(label, key=key, help=question, on_click=queue_page, args=("chat", question))


def example_buttons(questions: list[str], prefix: str, ncols: int = 2) -> None:
    cols = st.columns(ncols)
    for i, q in enumerate(questions):
        if cols[i % ncols].button(q, key=f"{prefix}_{i}", width="stretch"):
            st.session_state.pending = q
            st.rerun()


def render_answer(ans: dict, idx: int, cfg: dict) -> None:
    status = ans.get("status", "ok")
    d = ans.get("diagnostics") or {}
    f = ans.get("filters_used") or {}

    if status == "refusal":
        st.error("🔒 " + (ans.get("answer_markdown") or ""))
    elif status == "unsupported":
        st.warning("ℹ️ " + (ans.get("answer_markdown") or ""))
    else:
        st.markdown(ans.get("answer_markdown") or "")

    if status in ("ok", "unsupported"):
        chips([f.get("topic"), f.get("period"), f.get("persona")])
        if d.get("via_mcp"):
            chips([f"MCP Tool: {(d.get('tool_calls') or [{}])[0].get('name', 'governed')}"], "mcp")
        if f.get("applied"):
            st.caption("Filters applied: " + " · ".join(f["applied"]))
        if f.get("carried_over"):
            st.caption("↪ Context carried over: " + " · ".join(f["carried_over"]))

    cols = ans.get("table_columns") or []
    recs = ans.get("table_records") or []
    df = pd.DataFrame(recs, columns=cols) if cols and recs else pd.DataFrame()
    if not df.empty:
        st.markdown(TABLE_CSS + render_html(df), unsafe_allow_html=True)

    fig = figure(ans.get("chart_spec") or {})
    if fig is not None:
        st.plotly_chart(fig, width="stretch", key=f"chart_{idx}")

    if not df.empty:
        c1, c2, _ = st.columns([1, 1, 5])
        c1.download_button(
            "⬇️ CSV",
            to_csv_bytes(df),
            file_name=f"apex_margin_{idx}.csv",
            mime="text/csv",
            key=f"csv_{idx}",
        )
        c2.download_button(
            "⬇️ Excel",
            to_excel_bytes(df),
            file_name=f"apex_margin_{idx}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"xls_{idx}",
        )

    if status in ("ok", "unsupported", "refusal"):
        with st.expander("🔍 How I got this & 9-View Lineage"):
            st.markdown(
                f"**Topic / Tool:** `{f.get('topic', '-')}`  \n"
                f"**Period:** `{f.get('period', '-')}` (As-of `{f.get('as_of_date', '-')}`)  \n"
                f"**Persona & Scope:** `{f.get('persona', '-')}` — {f.get('rls', '-')}  \n"
                f"**9-View Lineage:** `{d.get('lineage_id', 'vwm.*')}`"
            )
            calls = d.get("tool_calls") or []
            if calls:
                st.markdown(f"**MCP Tool Call** (router: `{d.get('tool_choice_source', 'rules')}`, `via_mcp={d.get('via_mcp')}`)")
                st.json(calls, expanded=False)
            g = d.get("guardrail") or {}
            if g:
                g_lbl = "verified LLM prose" if (g.get("ok") and not g.get("template")) else f"deterministic template ({g.get('reason', 'rules')})"
                st.caption(f"Guardrail: {g_lbl} · model: {d.get('model', 'rules')} · latency: {d.get('latency_s', '-')} s")
            for sql in ans.get("sql_used") or []:
                st.code(sql, language="sql")

    # Inline Quick Write-Back Drawer directly in Chat (on the latest assistant message)
    is_latest = idx == len(st.session_state.get("messages", [])) - 1
    if status == "ok" and is_latest:
        _inline_writeback_drawer(ans, idx, cfg)

    fu = ans.get("followups") or []
    if fu and status in ("ok", "unsupported"):
        st.markdown("**Suggested follow-ups**")
        fcols = st.columns(min(3, len(fu)))
        for j, q in enumerate(fu[:3]):
            if fcols[j].button(q, key=f"fu_{idx}_{j}", width="stretch"):
                st.session_state.pending = q
                st.rerun()


def _inline_writeback_drawer(ans: dict, idx: int, cfg: dict) -> None:
    """Collapsible inline CAT write-back panel directly beneath the latest chat answer."""
    from app.cat.store import COMMENT_CATEGORIES, DECISION_TYPES, PLAN_HORIZONS, TEAM_DIRECTORY
    from app.semantic import service as Svc

    d = ans.get("diagnostics") or {}
    ctx_cid = d.get("context_contract_id") or ""
    contracts_res = Svc.get_contract_profitability(user_id=cfg["user_id"], as_of=cfg["as_of"])
    cids = contracts_res.df["Contract ID"].tolist() if not contracts_res.df.empty else []
    if not cids:
        return
    default_idx = cids.index(ctx_cid) if ctx_cid in cids else 0
    team_names = [t["name"] for t in TEAM_DIRECTORY]

    lbl = f"✍️ Write Back to Database — {ctx_cid or 'Contract Comment · N-1 Action Plan · Decision'}"
    with st.expander(lbl, expanded=False):
        t_cmt, t_n1, t_dec = st.tabs([
            "📝 Contract Comment (Weather / Scope)",
            "👤 N-1 Instruction / Action Plan",
            "🏛️ Business Leader Decision",
        ])
        with t_cmt:
            with st.form(f"inline_cmt_{idx}", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns([1.2, 1.5, 0.8, 0.8])
                cid = c1.selectbox("Contract", cids, index=default_idx, key=f"ic_cid_{idx}")
                cat = c2.selectbox("Category", list(COMMENT_CATEGORIES), key=f"ic_cat_{idx}")
                hrs = c3.number_input("Impact Hrs", min_value=0.0, value=0.0, step=4.0, key=f"ic_hrs_{idx}")
                usd = c4.number_input("Impact ($)", min_value=0.0, value=0.0, step=500.0, key=f"ic_usd_{idx}")
                txt = st.text_area("Clarification / Root Cause Note", placeholder="e.g. Severe storm delayed vessel mobilization; underestimated cost — add contingency buffer.", height=70, key=f"ic_txt_{idx}")
                if st.form_submit_button("Save Comment to Database", type="primary"):
                    if txt.strip():
                        out = Svc.add_contract_comment(
                            contract_id=cid, comment_text=txt.strip(), category=cat,
                            impact_hours=float(hrs), impact_usd=float(usd),
                            user_id=cfg["user_id"], user_name=st.session_state.get("auth_name"), as_of=cfg["as_of"],
                        )
                        st.session_state["writeback_toast"] = out.headline
                        st.rerun()
        with t_n1:
            with st.form(f"inline_n1_{idx}", clear_on_submit=True):
                c1, c2, c3 = st.columns([1.2, 1.3, 1])
                cid = c1.selectbox("Contract", cids, index=default_idx, key=f"in_cid_{idx}")
                rep = c2.selectbox("Assign To (N-1)", team_names, key=f"in_rep_{idx}")
                hor = c3.selectbox("Plan Horizon", list(PLAN_HORIZONS), index=1, key=f"in_hor_{idx}")
                txt = st.text_area("Instruction / Task Assignment for Reportee", placeholder="e.g. Re-baseline task hours and submit client change order before next Tuesday.", height=70, key=f"in_txt_{idx}")
                if st.form_submit_button("Save to Action Plan DB", type="primary"):
                    if txt.strip():
                        out = Svc.assign_n1_action_or_task(
                            contract_id=cid, assignee_name=rep, instruction=txt.strip(),
                            plan_horizon=hor, user_id=cfg["user_id"], user_name=st.session_state.get("auth_name"), as_of=cfg["as_of"],
                        )
                        st.session_state["writeback_toast"] = out.headline
                        st.rerun()
        with t_dec:
            if cfg["user_id"] != "bu_director":
                st.caption("🔒 Business Leader Decisions require the **Operations Portfolio Director (BU Manager)** persona.")
            else:
                with st.form(f"inline_dec_{idx}", clear_on_submit=True):
                    c1, c2 = st.columns([1.2, 1.6])
                    cid = c1.selectbox("Contract", cids, index=default_idx, key=f"id_cid_{idx}")
                    dtype = c2.selectbox("Decision Type", list(DECISION_TYPES), key=f"id_typ_{idx}")
                    txt = st.text_area("Decision Rationale", placeholder="e.g. Approve 15% weather contingency overhead buffer through Dec 5.", height=70, key=f"id_txt_{idx}")
                    if st.form_submit_button("Record Leadership Decision", type="primary"):
                        if txt.strip():
                            out = Svc.record_leadership_decision(
                                contract_id=cid, decision_type=dtype, rationale=txt.strip(),
                                user_id=cfg["user_id"], user_name=st.session_state.get("auth_name"), as_of=cfg["as_of"],
                            )
                            st.session_state["writeback_toast"] = out.headline
                            st.rerun()


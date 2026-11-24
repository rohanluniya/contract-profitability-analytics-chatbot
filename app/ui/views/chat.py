"""Chat view: Persona-Adaptive Executive KPI Strip + Slash-Command & Conversational Analytics."""
from __future__ import annotations

import time

import streamlit as st

from app.agent.graph import ask
from app.semantic import service as Svc
from app.ui import branding as B
from app.ui import common as C
from app.ui import sidebar as Side


def _kpi_overview_strip(cfg: dict) -> None:
    """Render 4 persona-adaptive executive KPI cards from the live 9-view warehouse."""
    uif = cfg.get("ui_filters") or {}
    snap = Svc.get_portfolio_summary(
        bu_id=uif.get("bu_id"),
        contract_type=uif.get("contract_type"),
        user_id=cfg["user_id"],
        as_of=cfg["as_of"],
    )
    if snap.status != "ok":
        st.warning(snap.headline)
        return

    k = snap.extra.get("kpis") or {}
    uid = cfg["user_id"]

    if uid == "pm_delivery":
        cards = [
            ("Assigned Contracts", f"{k['contract_count']}", "PM Field & Lab Scope", f"MTD Recognized: ${k['mtd_rev']:,.0f} vs Target ${k['tgt_rev']:,.0f}", ""),
            ("Provisional Margin", f"{k['port_margin_pct']:.1f}%", "Complete-rate commercial", "FS-AERO-104 at 168% burn (-21.6% margin)", "warn"),
            ("Unapproved & Unvalued Hrs", f"{k['unapp_hrs']:.0f}h / {k['unval_hrs']:.0f}h", "GTE & CRC Compliance", f"${k['unbilled_wip']:,.0f} WIP >7d lag · 48h missing CRC rate", "risk"),
            ("Active Exceptions", f"{k['active_exceptions']}", "Tactical Triage Queue", "Top priority: EXC-101 on FS-AERO-104", "risk"),
        ]
    elif uid == "commercial_admin":
        cards = [
            ("MTD Commercial Revenue", f"${k['mtd_rev']:,.0f}", f"Target: ${k['tgt_rev']:,.0f}", f"Variance: ${k['rev_gap']:+,.0f} across {k['contract_count']} contracts", "blue"),
            ("Unbilled WIP (>7d Lag)", f"${k['unbilled_wip']:,.0f}", f"{k['unapp_hrs']:.0f} hrs awaiting approval", "TM-ELEC-204 pending 11 business days", "warn"),
            ("Master Data Exceptions", f"{k['unval_hrs']:.0f}h + 1 EFL", "CRC / EFL / Fee Gaps", "FS-AUTO-305 unmatched · DISC-SPECIALIST-9 unmapped · 1 orphan fee", "risk"),
            ("Active Exceptions", f"{k['active_exceptions']}", "Cross-BU Audit Queue", "Includes SP-REV-901 & SP-COST-902 (strictly N/A margin)", "risk"),
        ]
    else:  # bu_director
        cards = [
            ("MTD Recognized Revenue", f"${k['mtd_rev']:,.0f}", f"vs. Target ${k['tgt_rev']:,.0f}", f"Revenue Gap: ${k['rev_gap']:+,.0f} · {k['contract_count']} portfolio contracts", "blue"),
            ("Provisional / Net Margin", f"{k['port_margin_pct']:.1f}% / {k['net_op_margin_pct']:.1f}%", f"After ${k['alloc_ovh']:,.0f} Lab Burden", f"Net Operating Margin: ${k['net_op_margin_usd']:,.0f}", ""),
            ("T&M Utilization & WIP", f"{k['tm_util_pct']:.1f}%", f"{k['unapp_hrs']:.0f}h unapproved · {k['unval_hrs']:.0f}h unmapped", "Alert: TM-ENV-401 at 64.0% (<80% threshold)", "warn"),
            ("Active Exceptions", f"{k['active_exceptions']}", "Management by Exception", "Top offender: FS-AERO-104 (Priority Score > 80)", "risk"),
        ]

    cols = st.columns(4)
    for idx, (title, val, period, sub, style_cls) in enumerate(cards):
        cols[idx].markdown(
            f"<div class='ax-kpi-card {style_cls}'>"
            f"<div class='k-title'>{C.esc(title)}</div>"
            f"<div class='k-val'>{C.esc(val)}</div>"
            f"<div class='k-period'>{C.esc(period)}</div>"
            f"<div class='k-sub'>{C.esc(sub)}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def _has_history() -> bool:
    store, user = C.history_store(), st.session_state.get("auth_user")
    if store is None or not user:
        return False
    try:
        return bool(store.list(user))
    except Exception:  # noqa: BLE001
        return False


def welcome_card() -> None:
    if st.session_state.get("welcome_dismissed") or _has_history():
        return
    with st.container(border=True, key="welcome_card"):
        c1, c2 = st.columns([12, 1])
        c1.markdown(f"#### Welcome to {B.APP_NAME}")
        if c2.button("✕", key="welcome_close", help="Dismiss"):
            st.session_state.welcome_dismissed = True
            st.rerun()
        st.markdown(
            "Protect and audit TIC contract profitability through **Management by Exception** — and **write comments, "
            "N-1 reportee instructions, task assignments, and leadership decisions directly back into the CAT database** "
            "using slash commands or natural language."
        )
        C.example_buttons(C.WELCOME_EXAMPLES, "wel", 3)
        b1, b2, b3, _ = st.columns([2, 2.2, 2.2, 3.6])
        b1.button("🚨 Exception Triage", key="welcome_exc", on_click=C.queue_page, args=("exceptions",))
        b2.button("🗓️ Action Plan & Notes", key="welcome_plan", on_click=C.queue_page, args=("plan",))
        b3.button("📋 Portfolio & Overhead", key="welcome_port", on_click=C.queue_page, args=("portfolio",))


def prompt_gallery() -> None:
    st.markdown("#### Executive Triage, Write-Back & Action Plan Walkthrough")
    C.example_buttons(C.DEMO_JOURNEY_EXAMPLES, "journey", 2)
    with st.expander("Task Assignment, Leadership Decisions, Overhead & Governance Prompts", expanded=False):
        C.example_buttons(C.GOVERNANCE_EXAMPLES, "gov", 2)


def process(question: str, cfg: dict) -> None:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑‍💼"):
        st.markdown(C.md_escape(question))
    warning = None
    with st.chat_message("assistant", avatar="🛡️"):
        with st.spinner("Auditing 9-view TIC portfolio via MCP ..."):
            t0 = time.time()
            try:
                ans, mem = ask(
                    question,
                    user_id=cfg["user_id"],
                    user_name=st.session_state.get("auth_name"),
                    memory=st.session_state.memory,
                    model=cfg["model"] or "rules",
                    as_of=cfg["as_of"],
                    ui_filters=cfg.get("ui_filters"),
                )
                payload = ans.model_dump()
                payload["diagnostics"]["question"] = question
                st.session_state.memory = mem
                warning = C.save_turn(question, payload, mem, cfg)
            except Exception as exc:  # noqa: BLE001
                payload = {
                    "answer_markdown": f"Unexpected error: `{type(exc).__name__}`: {exc}",
                    "status": "error",
                    "followups": [],
                    "diagnostics": {"latency_s": round(time.time() - t0, 2), "question": question},
                }
    st.session_state.messages.append({"role": "assistant", "answer": payload})
    if warning:
        st.session_state["history_warning"] = warning
    st.rerun()


def _bottom_chips(cfg: dict) -> None:
    chips = Side.filter_chips(cfg.get("ui_filters") or {})
    target = getattr(st, "bottom", None)
    holder = target.container() if target is not None else st.container()
    with holder:
        if chips:
            C.chips(["Active Filters: " + chips[0]] + chips[1:], "filter")
        else:
            st.caption("Commands: `/summary` · `/exceptions` · `/trace <id>` · `/comment <id> <note>` · `/assign <id> to <name> [next week|next month] <task>` · `/decide <id> <rationale>` · `/plan`")


def render() -> None:
    cfg = st.session_state["cfg"]
    if st.session_state.get("history_warning"):
        st.warning(st.session_state.pop("history_warning"))
    if st.session_state.get("writeback_toast"):
        st.success("✅ " + st.session_state.pop("writeback_toast"))

    _kpi_overview_strip(cfg)
    st.write("")

    if not st.session_state.messages and not st.session_state.pending:
        welcome_card()
        prompt_gallery()

    for i, m in enumerate(st.session_state.messages):
        with st.chat_message(m["role"], avatar="🧑‍💼" if m["role"] == "user" else "🛡️"):
            if m["role"] == "user":
                st.markdown(C.md_escape(m["content"]))
            else:
                C.render_answer(m["answer"], i, cfg)

    _bottom_chips(cfg)
    typed = st.chat_input("Ask Apex Margin Advisor or write back via /comment, /assign, /decide, /log, /plan ...")
    q = typed or st.session_state.pending
    if q:
        st.session_state.pending = None
        process(q, cfg)

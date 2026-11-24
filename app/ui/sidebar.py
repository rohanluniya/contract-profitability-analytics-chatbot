"""Sidebar for Apex Margin Advisor: Quick Guide, Multi-Persona RLS, Scope Filters, Model Selector & Conversations."""
from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from app.config import backend, data_as_of_date
from app.semantic.access import get_user_scope
from app.semantic.service import EXCEPTION_FAMILIES
from app.ui import branding as B
from app.ui import common as C

QUICK_TIPS = """
1. **Analytical Slash Commands:**
   - `/summary` — Persona-adapted KPI card & BU margin summary
   - `/exceptions [category]` — Priority-scored top-5 exception queue (0–100 pts)
   - `/trace <contract_id>` — 5-point OWMS / GTE / CRC / EFL audit + live written-back notes
2. **Database Write-Back Slash Commands (CAT Persistent Store):**
   - `/comment <contract_id> <note>` — Save weather/natural event delays, scope underestimation, or client context notes
   - `/assign <contract_or_task> to <reportee> [next week|next month] <instruction>` — Delegate N-1 directives, assign unassigned tasks, or reallocate hours
   - `/decide <contract_id> <rationale>` — Record official Business Leader decisions (BU Manager role only)
   - `/log <exception_id> <note>` — Log a remediation commitment on an exception
   - `/plan [this week|next week|next month|reportee|comments|assignments|decisions]` — View the weekly/monthly Action Plan
3. **Inline Write-Back in Chat:** Expand **✍️ Write Back to Database** beneath any assistant response, or use the **🗓️ Action Plan & Notes** tab.
4. **Anomaly Integrity Enforced:** `SP-REV-901` / `SP-COST-902` strictly report `N/A` margin, `TM-RENEW-202` flags 48 unmapped rate hours as unvalued exposure, and ERP actuals are never overwritten by human notes.
"""

CONTRACT_TYPE_OPTIONS = ["All Types", "FS", "TM", "SP-REV", "SP-COST"]
EXCEPTION_FAMILY_OPTIONS = ["All Families", *EXCEPTION_FAMILIES]
FILTER_KEYS = ["flt_bu", "flt_ctype", "flt_exfam"]


@st.dialog("Apex Margin Advisor — Quick Guide")
def quick_guide() -> None:
    st.markdown(QUICK_TIPS)
    st.button("Open Full User Guide", type="primary", key="qg_open_guide", on_click=C.queue_page, args=("guide",))


def clear_filters() -> None:
    for k in FILTER_KEYS:
        st.session_state.pop(k, None)


def _persona_changed() -> None:
    st.session_state.persona = st.session_state.persona_select
    C.new_conversation()
    clear_filters()


def _settings() -> dict:
    with st.expander("Persona & Model Settings", expanded=True):
        if "persona_select" not in st.session_state:
            st.session_state.persona_select = st.session_state.persona
        persona = st.selectbox(
            "Active Persona (RLS)",
            list(C.PERSONAS),
            key="persona_select",
            on_change=_persona_changed,
        )
        user_id = C.PERSONAS[persona]
        scope = get_user_scope(user_id)
        st.markdown(f"<div class='ax-scope'><b>Scope:</b> {C.esc(scope.scope_label)}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='ax-scope'><b>Tone:</b> {C.esc(scope.tone)}</div>", unsafe_allow_html=True)

        max_d = data_as_of_date()
        as_of = st.date_input(
            "As-of date",
            value=max_d,
            min_value=date(2026, 11, 1),
            max_value=max_d,
            help="Point-in-time evaluation date for overdue milestones and MTD metrics.",
        )

        choices = C.model_choices()
        if st.session_state.get("model_select") not in choices:
            wanted = st.session_state.get("model_param") or str(st.query_params.get("model", "")).strip().lower()
            st.session_state.model_select = next(
                (c for c in choices if wanted and c.lower().startswith(wanted)),
                choices[0],
            )
        model = st.selectbox(
            "Model (LiteLLM)",
            choices,
            key="model_select",
            help="'rules (no LLM)' executes 100% deterministic local routing & grounded consulting prose.",
        )
    return {
        "user_id": user_id,
        "as_of": as_of,
        "model": None if model.startswith("rules") else model,
        "model_label": model,
    }


def _prune_single(key: str, valid_options: list[str]) -> None:
    cur = st.session_state.get(key)
    if cur not in (None, *valid_options):
        st.session_state.pop(key, None)


def _filters(user_id: str) -> dict:
    scope = get_user_scope(user_id)
    with st.expander("Portfolio Scope Filters", expanded=False):
        bu_opts = ["All in scope"] + list(scope.allowed_bus)
        _prune_single("flt_bu", bu_opts)
        sel_bu = st.selectbox("Business Unit", bu_opts, key="flt_bu")

        _prune_single("flt_ctype", CONTRACT_TYPE_OPTIONS)
        sel_ct = st.selectbox("Contract Structure", CONTRACT_TYPE_OPTIONS, key="flt_ctype")

        _prune_single("flt_exfam", EXCEPTION_FAMILY_OPTIONS)
        sel_ef = st.selectbox("Exception Family", EXCEPTION_FAMILY_OPTIONS, key="flt_exfam")

        st.button("Clear filters", width="stretch", on_click=clear_filters, key="clear_filters")

    ui: dict = {}
    if sel_bu != "All in scope":
        ui["bu_id"] = sel_bu
    if sel_ct != "All Types":
        ui["contract_type"] = sel_ct
    if sel_ef != "All Families":
        ui["exception_family"] = sel_ef
    return ui


def filter_chips(ui: dict) -> list[str]:
    out = []
    if ui.get("bu_id"):
        out.append(f"BU: {ui['bu_id']}")
    if ui.get("contract_type"):
        out.append(f"Type: {ui['contract_type']}")
    if ui.get("exception_family"):
        out.append(f"Family: {ui['exception_family']}")
    return out


def _relative_time(ts: datetime | None) -> str:
    if ts is None:
        return ""
    secs = (datetime.now() - ts).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    days = int(secs // 86400)
    return "yesterday" if days == 1 else f"{days}d ago"


def _conversations(user_key: str) -> None:
    st.markdown("**Conversations**")
    if st.button("➕ New conversation", width="stretch", key="new_conv"):
        C.new_conversation()
        st.rerun()
    store = C.history_store()
    if store is None:
        st.caption("Conversation history unavailable.")
        return
    try:
        convs = store.list(user_key)
    except Exception as exc:  # noqa: BLE001
        st.caption(f"History unavailable ({type(exc).__name__}).")
        return
    if not convs:
        st.caption("Your last 10 conversations will appear here.")
    active = st.session_state.get("active_cid")
    for c in convs:
        cols = st.columns([5, 1])
        mark = "📌 " if c.is_pinned else ""
        cur = "▸ " if c.conversation_id == active else ""
        label = f"{cur}{mark}{C.md_escape(c.title)} · {_relative_time(c.updated_at)}"
        if cols[0].button(
            label,
            key=f"conv_{c.conversation_id}",
            width="stretch",
            type="primary" if c.conversation_id == active else "secondary",
        ):
            C.open_conversation(c.conversation_id)
            st.rerun()
        with cols[1].popover("⋯", help="Rename, pin or delete"):
            new_t = st.text_input("Rename", value=c.title, key=f"ren_{c.conversation_id}", max_chars=120)
            if st.button("Save name", key=f"ren_btn_{c.conversation_id}"):
                store.rename(user_key, c.conversation_id, new_t)
                st.rerun()
            if st.button("Unpin" if c.is_pinned else "Pin to top", key=f"pin_{c.conversation_id}"):
                store.pin(user_key, c.conversation_id, not c.is_pinned)
                st.rerun()
            confirm = st.checkbox("Confirm delete", key=f"delc_{c.conversation_id}")
            if st.button("Delete", key=f"del_{c.conversation_id}", disabled=not confirm):
                store.delete(user_key, c.conversation_id)
                if active == c.conversation_id:
                    C.new_conversation()
                st.rerun()
    st.caption("Keeps your last 10 threads; pinned conversations stay on top.")


def render() -> dict:
    with st.sidebar:
        if st.button("❓ Quick guide & Slash Commands", width="stretch"):
            quick_guide()
        who = st.session_state.get("auth_name")
        if who:
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.caption(f"Signed in as **{C.md_escape(who)}**")
            c2.button("Sign out", key="sign_out", on_click=C.sign_out, width="stretch")
        cfg = _settings()
        cfg["ui_filters"] = _filters(cfg["user_id"])
        st.divider()
        _conversations(st.session_state.get("auth_user") or "")
        st.divider()
        st.caption(f"Backend: {backend()} · 9 views (`vwm.*`) · CAT live write-back")
        st.caption(B.footer_line())
    st.session_state["cfg"] = cfg
    return cfg

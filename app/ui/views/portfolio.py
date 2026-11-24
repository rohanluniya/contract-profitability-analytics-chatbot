"""Portfolio & Shared Overhead view: 20-Contract Margin Ledger, $120k Indirect Lab Burden & T&M Utilization."""
from __future__ import annotations

import streamlit as st

from app.semantic import service as Svc
from app.ui import common as C
from app.viz.charts import figure
from app.viz.tables import TABLE_CSS, render_html, to_csv_bytes


def render() -> None:
    cfg = st.session_state["cfg"]
    uif = cfg.get("ui_filters") or {}

    st.markdown("### 📋 Contract Portfolio, Shared Lab Overhead & T&M Utilization")
    t_port, t_ovh, t_labor = st.tabs([
        "📑 Contract Profitability (FS / T&M / SP)",
        "🧪 Shared Laboratory Overhead ($120,000)",
        "⏱️ Labor, Utilization & Unbilled WIP",
    ])

    with t_port:
        c1, c2 = st.columns([1.2, 1.5])
        ct_pick = c1.selectbox("Contract Type", ["All Types", "FS", "TM", "SP-REV", "SP-COST"])
        bot_only = c2.checkbox("Show only underperforming bottom contracts", value=False)
        res = Svc.get_contract_profitability(
            bu_id=uif.get("bu_id"),
            contract_type=None if ct_pick == "All Types" else ct_pick,
            bottom_only=bot_only,
            special_purpose_only=ct_pick in ("SP-REV", "SP-COST"),
            user_id=cfg["user_id"],
            as_of=cfg["as_of"],
        )
        if res.status == "refusal":
            st.error(res.headline)
        else:
            st.markdown(res.headline)
            fig = figure(res.chart_spec)
            if fig is not None:
                st.plotly_chart(fig, width="stretch", key="port_margin_chart")
            if not res.df.empty:
                st.markdown(TABLE_CSS + render_html(res.df), unsafe_allow_html=True)
                st.download_button(
                    "⬇️ Download Portfolio Table (CSV)",
                    to_csv_bytes(res.df),
                    file_name="apex_contract_portfolio.csv",
                    mime="text/csv",
                )
        st.markdown("#### Investigate Special Cases in Chat")
        b1, b2, b3 = st.columns(3)
        with b1:
            C.ask_button("Trace FS-AERO-104 (168% Burn)", "/trace FS-AERO-104", key="pf_ask_1")
        with b2:
            C.ask_button("Trace FS-AUTO-305 (Unmatched EFL)", "/trace FS-AUTO-305", key="pf_ask_2")
        with b3:
            C.ask_button("Inspect SP-REV-901 & SP-COST-902", "Show Special Purpose contracts SP-REV-901 and SP-COST-902", key="pf_ask_3")

    with t_ovh:
        ovh = Svc.get_shared_overhead_allocation(
            bu_id=uif.get("bu_id"),
            user_id=cfg["user_id"],
            as_of=cfg["as_of"],
        )
        if ovh.status == "refusal":
            st.warning("🔒 " + ovh.headline)
        else:
            st.markdown(ovh.headline)
            for f in ovh.facts:
                st.markdown(f"- {f}")
            fig = figure(ovh.chart_spec)
            if fig is not None:
                st.plotly_chart(fig, width="stretch", key="ovh_alloc_chart")
            if not ovh.df.empty:
                st.markdown(TABLE_CSS + render_html(ovh.df), unsafe_allow_html=True)

    with t_labor:
        lab = Svc.get_labor_and_timesheet_compliance(
            bu_id=uif.get("bu_id"),
            user_id=cfg["user_id"],
            as_of=cfg["as_of"],
        )
        if lab.status == "refusal":
            st.error(lab.headline)
        else:
            st.markdown(lab.headline)
            for f in lab.facts:
                st.markdown(f"- {f}")
            fig = figure(lab.chart_spec)
            if fig is not None:
                st.plotly_chart(fig, width="stretch", key="labor_util_chart")
            if not lab.df.empty:
                st.markdown(TABLE_CSS + render_html(lab.df), unsafe_allow_html=True)

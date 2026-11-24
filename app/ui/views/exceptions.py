"""Exception Triage Command Center: 4 Exception Families, Priority Scoring Breakdown, Trace & Live CAT Write-Back."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from app.semantic import service as Svc
from app.ui import common as C
from app.viz.charts import figure
from app.viz.tables import TABLE_CSS, render_html, to_csv_bytes


def render() -> None:
    cfg = st.session_state["cfg"]
    uif = cfg.get("ui_filters") or {}

    st.markdown("### 🚨 Management by Exception — Priority Triage Queue")
    st.info(
        "**Priority Score (0–100):** `Materiality (max 45)` + `Urgency (max 25)` + `Deterioration (max 15)` + `Action Latency (max 15)`. "
        "Healthy contracts are filtered out automatically so operational leaders focus exclusively on margin decay, delivery bottlenecks, and ledger integrity gaps."
    )

    f1, f2 = st.columns([2, 1])
    fam = f1.selectbox("Filter by Exception Family", ["All Families", *Svc.EXCEPTION_FAMILIES])
    lim = f2.selectbox("Show Top Offenders", [5, 10, 20], index=1)

    res = Svc.get_exceptions_queue(
        category=None if fam == "All Families" else fam,
        bu_id=uif.get("bu_id"),
        limit=int(lim),
        user_id=cfg["user_id"],
        as_of=cfg["as_of"],
    )
    if res.status == "refusal":
        st.error(res.headline)
        return

    st.markdown(res.headline)
    fig = figure(res.chart_spec)
    if fig is not None:
        st.plotly_chart(fig, width="stretch", key="triage_priority_chart")

    if not res.df.empty:
        st.markdown(TABLE_CSS + render_html(res.df), unsafe_allow_html=True)
        st.download_button(
            "⬇️ Download Exception Queue (CSV)",
            to_csv_bytes(res.df),
            file_name="apex_exceptions_triage.csv",
            mime="text/csv",
        )

        st.markdown("#### Quick 5-Point Trace in Chat")
        tcols = st.columns(min(4, len(res.df)))
        for idx, (_, row) in enumerate(res.df.head(4).iterrows()):
            cid = str(row["Contract ID"])
            with tcols[idx]:
                C.ask_button(
                    f"Trace {cid} ({row['Priority Score']:.1f})",
                    f"/trace {cid}",
                    key=f"exc_trace_{idx}_{cid}",
                )

        st.divider()
        st.markdown("#### ✍️ Record Remediation Commitment in CAT (`Fact_ActionLog`)")
        with st.form("cat_log_form", clear_on_submit=True):
            c1, c2 = st.columns([1.4, 1])
            ex_opts = [f"{r['Exception ID']} — {r['Contract ID']} ({r['Family']})" for _, r in res.df.iterrows()]
            chosen_ex = c1.selectbox("Select Exception", ex_opts)
            tgt_date = c2.date_input("Target Resolution Date", value=cfg["as_of"] + timedelta(days=7))
            comment = st.text_area(
                "Remediation Action Commitment",
                placeholder="e.g. Cap weekend overtime on fatigue rig and submit commercial scope change order to client.",
                height=80,
            )
            submitted = st.form_submit_button("Log Remediation Action to CAT", type="primary")
        if submitted:
            ex_id = chosen_ex.split("—")[0].strip()
            if not comment.strip():
                st.warning("Please enter a remediation action comment before logging.")
            else:
                out = Svc.log_remediation_action(
                    exception_id=ex_id,
                    action_note=comment.strip(),
                    target_resolution_date=tgt_date.isoformat(),
                    user_id=cfg["user_id"],
                    user_name=st.session_state.get("auth_name"),
                    as_of=cfg["as_of"],
                )
                if out.status == "ok":
                    st.success(out.headline)
                    st.rerun()
                else:
                    st.error(out.headline)

    st.markdown("#### Active Collaborative Action Tracker (`Fact_ActionLog`)")
    log_res = Svc.get_action_log(user_id=cfg["user_id"], as_of=cfg["as_of"])
    if not log_res.df.empty:
        st.markdown(TABLE_CSS + render_html(log_res.df), unsafe_allow_html=True)
    else:
        st.caption("No remediation actions logged yet in your scope.")

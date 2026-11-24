"""Data Catalog view: Financial Formulas, 9-View Schema & VWM/VDM Mapping, Data Integrity Checks, Live View Preview."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text

from app.db import get_engine
from app.semantic import service as Svc
from app.viz.tables import TABLE_CSS, render_html

NINE_VIEW_DIAGRAM = """[Dim_Contracts]
│  (1:N via project_uuid)
├──> [Dim_Services]
│           │  (1:N via service_uuid)
│           └──> [Dim_Tasks]
│                       │  (1:N via task_uuid)
│                       └──> [Fact_Timesheets]
│                                   │  (N:1 via discipline_id + effective_year)
│                                   └──> [Dim_RateCatalog]
│
│  (1:1 via TRIM/LTRIM efl_contract_id — LEFT JOIN)
├──> [Fact_GeneralLedger]
│
│  (N:1 via operating_unit_id)
├──> [Fact_SharedOverheadAllocation]
│
│  (1:N via project_uuid)
└──> [Fact_Exceptions]
            │  (1:N via exception_uuid / exception_id)
            └──> [Fact_ActionLog]  (CAT persistent business-key store)"""

VIEWS_LIST = [
    "vwm.Dim_Contracts",
    "vwm.Dim_Services",
    "vwm.Dim_Tasks",
    "vwm.Fact_Timesheets",
    "vwm.Dim_RateCatalog",
    "vwm.Fact_GeneralLedger",
    "vwm.Fact_SharedOverheadAllocation",
    "vwm.Fact_Exceptions",
    "vwm.Fact_ActionLog",
]


def render() -> None:
    cfg = st.session_state["cfg"]
    st.markdown("### 🗂️ Data Catalog, 9-View Relational Schema & Integrity Audit")
    t_rules, t_schema, t_checks, t_prev = st.tabs([
        "📏 Financial & Scoring Rules",
        "🔗 9-View Schema & VWM Mapping",
        "⚙️ Master Data Integrity Checks",
        "🔬 Live 9-View Table Preview",
    ])

    with t_rules:
        meth = Svc.get_methodology_and_lineage(user_id=cfg["user_id"], as_of=cfg["as_of"])
        st.markdown(meth.headline)
        st.markdown(TABLE_CSS + render_html(meth.df), unsafe_allow_html=True)

        st.markdown("#### Priority Scoring Formula (0–100 Points)")
        score_df = pd.DataFrame([
            {"Component": "Materiality", "Max Points": 45, "Calculation Logic": "min(45, 45 × log10(Capital_at_Risk / 5000 + 1))"},
            {"Component": "Urgency", "Max Points": 25, "Calculation Logic": "Due <= 3 days (or overdue): 25 pts | <= 7 days: 15 pts | <= 30 days: 5 pts"},
            {"Component": "Deterioration", "Max Points": 15, "Calculation Logic": "Hour burn > 150%: 15 pts | 120%–150%: 10 pts | 100%–120%: 5 pts"},
            {"Component": "Action Latency", "Max Points": 15, "Calculation Logic": "Unresolved > 14 days: 15 pts | 7–14 days: 10 pts | New (< 7 days): 3 pts"},
        ])
        st.markdown(TABLE_CSS + render_html(score_df), unsafe_allow_html=True)

    with t_schema:
        st.markdown("#### 9-View Relational Architecture (`schema: vwm`)")
        st.code(NINE_VIEW_DIAGRAM, language="text")

        cat = Svc.semantic_catalog()
        mod_df = pd.DataFrame([
            {
                "TIC Module": k,
                "Full Name": v["full_name"],
                "Governed Views": ", ".join(v["views"]),
                "Enterprise VWM / VDM Source Mapping": v["real_vdm_source"],
            }
            for k, v in cat["modules"].items()
        ])
        st.markdown("#### Synthetic Platform Modules ↔ Enterprise VWM / VDM Source Mapping")
        st.markdown(TABLE_CSS + render_html(mod_df), unsafe_allow_html=True)

        st.info(
            "**Critical Join Hygiene (VWM Data Analyst Guide):** All linkage joins to `Fact_GeneralLedger` (`LTRIM(TRIM(efl_contract_id), '0')`) "
            "and `Dim_RateCatalog` (`discipline_id` + `effective_year`) execute strictly as **LEFT JOINs**. "
            "Unlike inner-join extracts that silently drop unmatched contracts or unmapped rate cards, LEFT JOIN governance guarantees zero silent loss."
        )

    with t_checks:
        aud = Svc.get_data_integrity_audit(user_id=cfg["user_id"], as_of=cfg["as_of"])
        st.markdown(aud.headline)
        for f in aud.facts:
            st.markdown(f"- {f}")
        st.markdown(TABLE_CSS + render_html(aud.df), unsafe_allow_html=True)

    with t_prev:
        st.markdown("#### Live Preview of Governed 9 Views (Top 25 Rows)")
        obj = st.selectbox("Select view", VIEWS_LIST)
        eng = get_engine(cfg["user_id"])
        with eng.connect() as conn:
            sample = pd.read_sql(text(f"SELECT * FROM {obj} LIMIT 25"), conn)
        st.markdown(TABLE_CSS + render_html(sample), unsafe_allow_html=True)

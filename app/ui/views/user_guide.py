"""User Guide view: Persona Matrix, Slash Commands Reference & Guided Walkthrough."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.ui import branding as B
from app.ui import common as C
from app.viz.tables import TABLE_CSS, render_html


def render() -> None:
    st.markdown(f"### 📘 {B.APP_NAME} — User Guide & Command Reference")

    st.markdown("#### 1. Structured Slash Commands (Analytics & Database Write-Back)")
    cmd_df = pd.DataFrame([
        {
            "Command": "/summary",
            "Purpose": "Executive KPI summary card tailored to your active persona (MTD Rev vs. Target, Margin %, Unapproved Hours, Active Exceptions).",
            "Example": "/summary  or  /summary BU-AERO-02",
        },
        {
            "Command": "/exceptions [category]",
            "Purpose": "Prioritized table of open exceptions sorted by Priority Score (0–100, descending). Top 5 by default.",
            "Example": "/exceptions  |  /exceptions Setup  |  /exceptions Financial  |  /exceptions all",
        },
        {
            "Command": "/trace <contract_id>",
            "Purpose": "5-point OWMS / GTE / CRC / EFL audit trace + all written-back comments, N-1 instructions, task assignments, and leadership decisions.",
            "Example": "/trace FS-AERO-104  |  /trace FS-OFFSHORE-108  |  /trace TM-RENEW-202  |  /trace SP-REV-901",
        },
        {
            "Command": "/comment <contract_id> <note>",
            "Purpose": "Writes a field/commercial clarification note (weather delay, natural calamity, scope/cost underestimation, client hold) to `cat_contract_comments`.",
            "Example": "/comment FS-OFFSHORE-108 Storm halted vessel mobilization for 4 days; add weather contingency for December",
        },
        {
            "Command": "/assign <id> to <name> [horizon] <note>",
            "Purpose": "Delegates an N-1 instruction, assigns an unassigned task (`TSK-...`), or reallocates hours into the weekly/monthly Action Plan (`This Week`, `Next Week`, `Next Month`).",
            "Example": "/assign FS-AERO-104 to Jordan Vance next week Freeze overtime and deliver SkyForge change order",
        },
        {
            "Command": "/decide <contract_id> <rationale>",
            "Purpose": "Records a formal Business Leader decision (approve weather/cost buffer, accept variance, stop-work order) in `cat_leadership_decisions` (BU Manager role only).",
            "Example": "/decide FS-OFFSHORE-108 Approve 15% storm mobilization buffer through 2026-12-05",
        },
        {
            "Command": "/log <exception_id> <action_note>",
            "Purpose": "Writes a formalized remediation commitment directly into CAT (`Fact_ActionLog`) with baseline snapshot & target resolution date.",
            "Example": "/log EXC-101 Cap weekend fatigue rig overtime and submit client change order",
        },
        {
            "Command": "/plan [horizon|reportee|mode]",
            "Purpose": "Retrieves the Weekly/Monthly Action Plan, N-1 instructions by reportee, contract comments, task assignments, or leadership decisions.",
            "Example": "/plan next week  |  /plan Jordan Vance  |  /plan comments  |  /plan decisions",
        },
    ])
    st.markdown(TABLE_CSS + render_html(cmd_df), unsafe_allow_html=True)

    st.markdown("#### 2. Multi-Persona Contextual Adaptation")
    persona_df = pd.DataFrame([
        {
            "Persona": "Operations Portfolio Director (BU Manager)",
            "Scope (RLS)": "All 10 Business Units · 20 Portfolio Contracts",
            "Primary KPI Focus": "Provisional & Net Operating Margin %, MTD revenue gap, bottom contracts, shared lab overhead ($120k), T&M utilization.",
            "Action Orientation": "Strategic: scope renegotiation, stop-work orders, cross-BU resource balancing.",
        },
        {
            "Persona": "Project Delivery Manager (PM)",
            "Scope (RLS)": "6 Assigned Operational Contracts (Jordan Vance)",
            "Primary KPI Focus": "Milestone completion, actual vs. planned hour burn, timesheets awaiting approval, overdue tasks.",
            "Action Orientation": "Tactical: approve timesheets, reallocate field technicians, re-baseline task hours.",
        },
        {
            "Persona": "Commercial Contract Administrator",
            "Scope (RLS)": "Cross-BU Commercial Contracts & EFL Reconciliation (All 20)",
            "Primary KPI Focus": "Unbilled WIP (>7d lag), Milestone-to-GL variance, unmapped CRC rates, unmatched EFL IDs, orphaned fees.",
            "Action Orientation": "Compliance: billing adjustments, GL journal reclassifications, CRC rate card fixes.",
        },
    ])
    st.markdown(TABLE_CSS + render_html(persona_df), unsafe_allow_html=True)

    st.markdown("#### 3. Try the 5 Injected Benchmark Scenarios")
    c1, c2, c3 = st.columns(3)
    with c1:
        C.ask_button("1. Runaway Burn: FS-AERO-104 (168%)", "/trace FS-AERO-104", key="ug_s1")
        C.ask_button("4. Low Utilization: TM-ENV-401 (64%)", "/trace TM-ENV-401", key="ug_s4")
    with c2:
        C.ask_button("2. Missing CRC Rate: TM-RENEW-202 (48h)", "/trace TM-RENEW-202", key="ug_s2")
        C.ask_button("5. Shared Lab Overhead ($120k / 10 BUs)", "How is the $120,000 shared laboratory overhead allocated across Business Units?", key="ug_s5")
    with c3:
        C.ask_button("3. Unmatched EFL: FS-AUTO-305", "/trace FS-AUTO-305", key="ug_s3")
        C.ask_button("6. Special Purpose N/A Margin Check", "Show Special Purpose contracts SP-REV-901 and SP-COST-902", key="ug_s6")

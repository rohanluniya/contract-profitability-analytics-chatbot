"""About view: Architecture Diagram, Governance Guarantees & Enterprise VWM/VDM Production Path."""
from __future__ import annotations

import streamlit as st

from app.config import backend
from app.ui import branding as B

ARCH_DOT = """
digraph {
  rankdir=LR; bgcolor="transparent";
  node [shape=box, style="rounded,filled", fillcolor="#ECFDF5", color="#065F46", fontname="Helvetica", fontsize=11];
  edge [color="#1E3A8A"];
  q [label="Slash Command or\\nPlain-English Query", fillcolor="#EFF6FF", color="#1E3A8A"];
  r [label="Persona RLS &\\nGoverned MCP Router\\n(10 Typed Tools)"];
  w [label="9-View TIC Warehouse\\n(OWMS · EFL · GTE · CRC)"];
  c [label="CAT Action Store\\n(Fact_ActionLog)"];
  g [label="Anomaly & Numeric\\nGuardrail Layer"];
  o [label="Direct-Answer Insight\\n+ Table + Chart + Trace", fillcolor="#EFF6FF", color="#1E3A8A"];
  q -> r -> w -> g -> o;
  r -> c -> g;
}
"""


def render() -> None:
    st.markdown(f"## About {B.APP_NAME}")
    st.markdown(
        f"**{B.APP_NAME}** (*{B.APP_FULL_NAME}*) operationalizes **Management by Exception** for global "
        "Testing, Inspection, and Certification (TIC) portfolios — automatically isolating margin erosion, "
        "runaway hour burn, T&M utilization leakage, and ERP ledger mismatches across 9 governed views."
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            "#### Core Analytical Guarantees\n"
            "- **Fixed-Scope vs. T&M Economics:** Distinct revenue recognition, labor cost, and warning rules (`>115%` burn alert, `>150%` accrual block, `<80%` T&M utilization, `>7d` unapproved WIP lag).\n"
            "- **Non-Accessible Margin Protection:** `SP-REV-901` never reports `100%` margin (`N/A — Commercial Revenue Adjustment Contract`); `SP-COST-902` never reports `-100%` (`N/A — Internal Operational Holding Pool`).\n"
            "- **Zero Silent Drops:** Unmatched EFL contracts (`FS-AUTO-305`), unmapped CRC rate hours (`TM-RENEW-202`, `48 hrs`), and orphaned fee lines (`SVC-ORPHAN-999`) surface explicitly.\n"
            "- **Separate Indirect Lab Burden:** `$120,000` monthly `Cat-8000` / `Cat-9000` central laboratory overhead deducts transparently after contract provisional margin."
        )
    with c2:
        st.markdown(
            "#### Prototype Scope vs. Enterprise VWM / VDM Lift\n"
            "- **Synthetic Benchmark:** 10 TIC Business Units, 20 contracts (`12 FS`, `6 T&M`, `1 SP-REV`, `1 SP-COST`), and 5 injected anomaly scenarios with zero production ERP connectivity.\n"
            "- **Direct VWM / VDM Alignment:** Maps cleanly to enterprise `CORE` (`Project.*`, `Admin.*`), `FLEX / JD Edwards` (`F5201`, `F4211`, `F0911`, `F0901`, `F06116Z1`, `F069116`), and SharePoint management action lists.\n"
            f"- **Active Runtime Backend:** **`{backend().upper()}`** (supports zero-dependency DuckDB or SQL Server 2022 with `SESSION_CONTEXT` RLS), LiteLLM (`rules`, Ollama, Gemini, OpenAI), and standalone JSON-RPC 2.0 MCP server.\n"
            "- **Persistent CAT Audit Trail:** Remediation commitments link strictly by business keys (`exception_id`, `exception_uuid`, `contract_id`) so warehouse refreshes never orphan action history."
        )

    st.markdown("#### System Architecture")
    st.graphviz_chart(ARCH_DOT)
    st.caption(B.footer_line())

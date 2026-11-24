"""Governed HTML table formatting and CSV / Excel export helpers for Apex Margin Advisor."""
from __future__ import annotations

import html
import io

import pandas as pd

TABLE_CSS = """
<style>
table.ax-tbl { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin: 8px 0 12px; }
table.ax-tbl th { background: #0B1F3A; color: #FFFFFF; text-align: left; padding: 8px 10px; font-weight: 700; }
table.ax-tbl td { padding: 7px 10px; border-bottom: 1px solid #E2E8F0; color: #1E293B; vertical-align: top; }
table.ax-tbl tr:nth-child(even) td { background: #F8FAFC; }
table.ax-tbl td.num, table.ax-tbl th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.ax-badge-crit { background: #FEE2E2; color: #991B1B; padding: 2px 7px; border-radius: 6px; font-weight: 700; font-size: 0.77rem; white-space: nowrap; }
.ax-badge-warn { background: #FEF3C7; color: #92400E; padding: 2px 7px; border-radius: 6px; font-weight: 600; font-size: 0.77rem; white-space: nowrap; }
.ax-badge-ok { background: #DCFCE7; color: #166534; padding: 2px 7px; border-radius: 6px; font-weight: 600; font-size: 0.77rem; white-space: nowrap; }
.ax-badge-na { background: #F1F5F9; color: #475569; padding: 2px 7px; border-radius: 6px; font-weight: 600; font-size: 0.77rem; white-space: nowrap; }
</style>
"""


def _fmt_cell(col: str, val) -> tuple[str, bool]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—", False
    if isinstance(val, bool):
        return ("Yes" if val else "No"), False
    if isinstance(val, (int, float)):
        is_usd = "($)" in col
        if is_usd:
            if val < 0:
                return f"-${abs(val):,.0f}", True
            return f"${val:,.0f}", True
        if isinstance(val, int) or float(val).is_integer():
            return f"{int(val):,}", True
        return f"{val:,.1f}", True

    s = html.escape(str(val))
    su = s.upper()
    if col in ("Severity", "Status", "Audit Status", "Compliance Flag"):
        if any(k in su for k in ("CRITICAL", "DISCONNECTED", "RUNAWAY", "UNMATCHED EFL", "UNMAPPED RATE")):
            return f"<span class='ax-badge-crit'>{s}</span>", False
        if any(k in su for k in ("AT RISK", "WARNING", "HIGH", "WATCH", "DELIVERY RISK", "BILLING LAG", "VARIANCE", "MEDIUM")):
            return f"<span class='ax-badge-warn'>{s}</span>", False
    if s in ("Healthy", "Verified", "PASS", "Action Logged", "Completed"):
        return f"<span class='ax-badge-ok'>{s}</span>", False
    if "N/A" in s or "Special Purpose" in s:
        if col in ("Status", "Audit Status", "Provisional Margin"):
            return f"<span class='ax-badge-na'>{s}</span>", False
    return s, False


def render_html(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    cols = list(df.columns)
    num_cols = {c for c in cols if pd.api.types.is_numeric_dtype(df[c])}
    ths = "".join(f"<th class='{'num' if c in num_cols else ''}'>{html.escape(str(c))}</th>" for c in cols)
    rows_html = []
    for _, row in df.iterrows():
        tds = []
        for c in cols:
            txt, is_n = _fmt_cell(c, row[c])
            cls = "num" if (c in num_cols or is_n) else ""
            tds.append(f"<td class='{cls}'>{txt}</td>")
        rows_html.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table class='ax-tbl'><thead><tr>{ths}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Apex_Margin_Data")
    return buf.getvalue()

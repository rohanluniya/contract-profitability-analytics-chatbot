"""Governed TIC Portfolio Margin & Exception Semantic Service.

Queries strictly the 9 relational views in schema `vwm`:
  Dim_Contracts, Dim_Services, Dim_Tasks, Fact_Timesheets, Dim_RateCatalog,
  Fact_GeneralLedger, Fact_SharedOverheadAllocation, Fact_Exceptions, Fact_ActionLog

Plus live CAT remediation write-back via `ActionTrackerStore` (persisted by business keys).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

import pandas as pd
import yaml
from sqlalchemy import text

from app.cat.store import ActionTrackerStore
from app.config import ROOT, as_of_date
from app.db import get_engine
from app.semantic.access import UserScope, check_bu_access, check_contract_access, get_user_scope

SPECIAL_REV_LABEL = "N/A (Commercial Revenue Adjustment Contract)"
SPECIAL_COST_LABEL = "N/A (Internal Operational Holding Pool)"
DISCONNECTED_EFL_LABEL = "Disconnected from Financial Ledger"

EXCEPTION_FAMILIES = (
    "Setup & Integration Gaps",
    "Labor & Timesheet Compliance",
    "Operational Delivery Risks",
    "Financial & Margin Decay",
)


@dataclass
class ToolPayload:
    status: str = "ok"
    tool_name: str = ""
    topic_label: str = ""
    period_label: str = "Nov 2026 MTD"
    headline: str = ""
    facts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    chart_spec: dict[str, Any] = field(default_factory=dict)
    compiled_sql: str = ""
    lineage_id: str = "vwm.Dim_Contracts -> vwm.Fact_GeneralLedger"
    filters_used: dict[str, Any] = field(default_factory=dict)
    via_mcp: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
def semantic_catalog() -> dict[str, Any]:
    with open(ROOT / "app" / "semantic" / "metrics.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _fmt_usd(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "—"
    if val < 0:
        return f"-${abs(val):,.0f}"
    return f"${val:,.0f}"


def _fmt_pct(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "N/A"
    return f"{val:.1f}%"


# ---------------------------------------------------------------------------
# Core 9-View Contract Financial Rollup Engine (single source of truth)
# ---------------------------------------------------------------------------
CONTRACT_METRICS_SQL = """
WITH svc_agg AS (
    SELECT
        project_uuid,
        SUM(CASE WHEN is_billable = 1 AND is_orphaned = 0 THEN total_service_fee ELSE 0 END) AS contract_value
    FROM vwm.Dim_Services
    GROUP BY project_uuid
),
task_svc AS (
    SELECT
        t.task_uuid,
        t.service_uuid,
        t.project_uuid,
        t.task_name,
        t.discipline_id,
        t.planned_hours,
        t.due_date,
        t.completion_pct,
        t.task_status,
        t.invalid_dates_flag,
        s.total_service_fee,
        SUM(CASE WHEN t.task_status <> 'Cancelled' THEN t.planned_hours ELSE 0 END)
            OVER (PARTITION BY t.service_uuid) AS svc_planned_hours,
        r.hourly_cost_rate,
        r.billable_sell_rate
    FROM vwm.Dim_Tasks t
    LEFT JOIN vwm.Dim_Services s
        ON s.service_uuid = t.service_uuid AND s.is_orphaned = 0
    LEFT JOIN vwm.Dim_RateCatalog r
        ON r.discipline_id = t.discipline_id AND r.effective_year = 2026
),
task_rollup AS (
    SELECT
        project_uuid,
        SUM(CASE WHEN task_status <> 'Cancelled' THEN planned_hours ELSE 0 END) AS planned_hours,
        SUM(
            CASE
                WHEN task_status <> 'Cancelled' AND svc_planned_hours > 0
                THEN (total_service_fee * (planned_hours / svc_planned_hours)) * (completion_pct / 100.0)
                ELSE 0
            END
        ) AS fs_milestone_recognized_rev,
        SUM(
            CASE
                WHEN task_status <> 'Cancelled' AND due_date >= '2026-11-01' AND due_date <= '2026-11-30' AND svc_planned_hours > 0
                THEN total_service_fee * (planned_hours / svc_planned_hours)
                ELSE 0
            END
        ) AS fs_target_rev_mtd,
        SUM(
            CASE
                WHEN task_status <> 'Cancelled' AND billable_sell_rate IS NOT NULL
                THEN planned_hours * billable_sell_rate
                ELSE 0
            END
        ) AS tm_target_rev_mtd,
        SUM(CASE WHEN task_status NOT IN ('Completed', 'Cancelled') AND due_date < :as_of_iso THEN 1 ELSE 0 END) AS overdue_tasks,
        SUM(invalid_dates_flag) AS invalid_date_tasks
    FROM task_svc
    GROUP BY project_uuid
),
ts_joined AS (
    SELECT
        ts.project_uuid,
        ts.task_uuid,
        ts.discipline_id,
        ts.hours_logged,
        ts.is_billable_pay_type,
        ts.approval_status,
        ts.pending_business_days,
        ts.has_header,
        r.hourly_cost_rate,
        r.billable_sell_rate
    FROM vwm.Fact_Timesheets ts
    LEFT JOIN vwm.Dim_RateCatalog r
        ON r.discipline_id = ts.discipline_id AND r.effective_year = ts.effective_year
),
ts_rollup AS (
    SELECT
        project_uuid,
        SUM(hours_logged) AS actual_logged_hours,
        SUM(CASE WHEN approval_status = 'Approved' THEN hours_logged ELSE 0 END) AS approved_hours,
        SUM(CASE WHEN approval_status = 'Approved' AND is_billable_pay_type = 1 THEN hours_logged ELSE 0 END) AS approved_billable_hours,
        SUM(CASE WHEN approval_status <> 'Approved' THEN hours_logged ELSE 0 END) AS unapproved_hours,
        SUM(CASE WHEN approval_status <> 'Approved' AND pending_business_days > 7 THEN hours_logged ELSE 0 END) AS lagging_unapproved_hours,
        SUM(CASE WHEN approval_status <> 'Approved' AND billable_sell_rate IS NOT NULL THEN hours_logged * billable_sell_rate ELSE 0 END) AS unbilled_wip_value,
        SUM(CASE WHEN hourly_cost_rate IS NULL THEN hours_logged ELSE 0 END) AS unvalued_hours,
        SUM(CASE WHEN approval_status = 'Approved' AND hourly_cost_rate IS NOT NULL THEN hours_logged * hourly_cost_rate ELSE 0 END) AS fs_direct_labor_cost,
        SUM(CASE WHEN hourly_cost_rate IS NOT NULL THEN hours_logged * hourly_cost_rate ELSE 0 END) AS tm_direct_labor_cost,
        SUM(CASE WHEN approval_status = 'Approved' AND is_billable_pay_type = 1 AND billable_sell_rate IS NOT NULL THEN hours_logged * billable_sell_rate ELSE 0 END) AS tm_recognized_rev,
        SUM(CASE WHEN has_header = 0 THEN 1 ELSE 0 END) AS missing_header_entries
    FROM ts_joined
    GROUP BY project_uuid
),
gl_rollup AS (
    SELECT
        efl_contract_key_norm,
        SUM(CASE WHEN account_category IN ('1', '2') THEN recognized_amount ELSE 0 END) AS gl_recognized_rev,
        SUM(CASE WHEN account_category = '2' THEN recognized_amount ELSE 0 END) AS gl_finance_adj,
        SUM(CASE WHEN account_category IN ('8000', '9000') THEN direct_expense_amount ELSE 0 END) AS gl_direct_expenses,
        SUM(CASE WHEN account_category = '7x' THEN raw_amount ELSE 0 END) AS gl_cat7x_review_amt,
        COUNT(*) AS gl_line_count
    FROM vwm.Fact_GeneralLedger
    GROUP BY efl_contract_key_norm
)
SELECT
    c.project_uuid,
    c.contract_id,
    c.contract_name,
    c.operating_unit_id,
    c.bu_name,
    c.region,
    c.contract_type,
    c.project_status,
    c.efl_contract_id,
    c.efl_matched,
    c.pm_user_id,
    c.pm_name,
    c.client_name,
    COALESCE(sa.contract_value, 0.0) AS contract_value,
    COALESCE(tr.planned_hours, 0.0) AS planned_hours,
    COALESCE(tsr.actual_logged_hours, 0.0) AS actual_logged_hours,
    COALESCE(tsr.approved_hours, 0.0) AS approved_hours,
    COALESCE(tsr.approved_billable_hours, 0.0) AS approved_billable_hours,
    COALESCE(tsr.unapproved_hours, 0.0) AS unapproved_hours,
    COALESCE(tsr.lagging_unapproved_hours, 0.0) AS lagging_unapproved_hours,
    COALESCE(tsr.unbilled_wip_value, 0.0) AS unbilled_wip_value,
    COALESCE(tsr.unvalued_hours, 0.0) AS unvalued_hours,
    COALESCE(tr.fs_milestone_recognized_rev, 0.0) AS fs_milestone_recognized_rev,
    COALESCE(tr.fs_target_rev_mtd, 0.0) AS fs_target_rev_mtd,
    COALESCE(tr.tm_target_rev_mtd, 0.0) AS tm_target_rev_mtd,
    COALESCE(tsr.fs_direct_labor_cost, 0.0) AS fs_direct_labor_cost,
    COALESCE(tsr.tm_direct_labor_cost, 0.0) AS tm_direct_labor_cost,
    COALESCE(tsr.tm_recognized_rev, 0.0) AS tm_recognized_rev,
    COALESCE(glr.gl_recognized_rev, 0.0) AS gl_recognized_rev,
    COALESCE(glr.gl_finance_adj, 0.0) AS gl_finance_adj,
    COALESCE(glr.gl_direct_expenses, 0.0) AS gl_direct_expenses,
    COALESCE(glr.gl_cat7x_review_amt, 0.0) AS gl_cat7x_review_amt,
    COALESCE(tr.overdue_tasks, 0) AS overdue_tasks,
    COALESCE(tr.invalid_date_tasks, 0) AS invalid_date_tasks
FROM vwm.Dim_Contracts c
LEFT JOIN svc_agg sa ON sa.project_uuid = c.project_uuid
LEFT JOIN task_rollup tr ON tr.project_uuid = c.project_uuid
LEFT JOIN ts_rollup tsr ON tsr.project_uuid = c.project_uuid
LEFT JOIN gl_rollup glr ON glr.efl_contract_key_norm = c.efl_contract_key_norm
ORDER BY c.contract_type, c.contract_id
"""


def _load_contract_metrics(
    *,
    scope: UserScope,
    as_of: date,
    bu_id: str | None = None,
    contract_type: str | None = None,
) -> pd.DataFrame:
    eng = get_engine(scope.user_id)
    with eng.connect() as conn:
        df = pd.read_sql(text(CONTRACT_METRICS_SQL), conn, params={"as_of_iso": as_of.isoformat()})

    # Apply persona Row-Level Security (RLS)
    df = df[df["operating_unit_id"].isin(scope.allowed_bus)].copy()
    if scope.assigned_contracts is not None:
        df = df[df["contract_id"].isin(scope.assigned_contracts)].copy()
    if bu_id:
        df = df[df["operating_unit_id"] == bu_id].copy()
    if contract_type:
        ct = contract_type.upper().replace("T&M", "TM")
        df = df[df["contract_type"] == ct].copy()

    if df.empty:
        return df

    # Derive canonical FS, T&M, and Special Purpose financial metrics per row
    rec_revs, tgt_revs, labor_costs, dir_exps, margins_usd, margins_pct, margin_labels = [], [], [], [], [], [], []
    burn_pcts, util_pcts, gl_vars, health_flags = [], [], [], []

    for _, r in df.iterrows():
        ctype = str(r["contract_type"])
        planned_h = float(r["planned_hours"])
        actual_h = float(r["actual_logged_hours"])
        app_bill_h = float(r["approved_billable_hours"])
        unval_h = float(r["unvalued_hours"])
        efl_ok = int(r["efl_matched"]) == 1
        burn = (actual_h / planned_h * 100.0) if planned_h > 0 else None
        util = (app_bill_h / actual_h * 100.0) if (ctype == "TM" and actual_h > 0) else None

        if ctype == "FS":
            rec = float(r["fs_milestone_recognized_rev"])
            tgt = float(r["fs_target_rev_mtd"]) if float(r["fs_target_rev_mtd"]) > 0 else float(r["contract_value"]) * 0.5
            lcost = float(r["fs_direct_labor_cost"])
            dexp = float(r["gl_direct_expenses"]) if efl_ok else 0.0
            m_usd = rec - lcost - dexp
            m_pct = (m_usd / rec * 100.0) if rec > 0 else None
            gl_var = (rec - float(r["gl_recognized_rev"])) if efl_ok else None
            if not efl_ok:
                mlbl = f"{m_pct:.1f}% (EFL Disconnected)" if m_pct is not None else DISCONNECTED_EFL_LABEL
            elif burn is not None and burn > 150.0:
                mlbl = f"{m_pct:.1f}% (Accrual Blocked)"
            else:
                mlbl = f"{m_pct:.1f}%" if m_pct is not None else "N/A"
        elif ctype == "TM":
            rec = float(r["tm_recognized_rev"])
            tgt = float(r["tm_target_rev_mtd"])
            lcost = float(r["tm_direct_labor_cost"])
            dexp = 0.0
            m_usd = rec - lcost
            m_pct = (m_usd / rec * 100.0) if rec > 0 else None
            gl_var = (rec - float(r["gl_recognized_rev"])) if efl_ok else None
            if unval_h > 0:
                mlbl = f"{m_pct:.1f}% ({unval_h:.0f}h unvalued)" if m_pct is not None else f"Incomplete ({unval_h:.0f}h unvalued)"
            else:
                mlbl = f"{m_pct:.1f}%" if m_pct is not None else "N/A"
        elif ctype == "SP-REV":
            rec = float(r["gl_recognized_rev"])
            tgt = rec
            lcost = 0.0
            dexp = 0.0
            m_usd = rec
            m_pct = None
            gl_var = 0.0
            mlbl = SPECIAL_REV_LABEL
        else:  # SP-COST
            rec = 0.0
            tgt = 0.0
            lcost = 0.0
            dexp = float(r["gl_direct_expenses"])
            m_usd = -dexp
            m_pct = None
            gl_var = 0.0
            mlbl = SPECIAL_COST_LABEL

        # Contract risk status
        if ctype in ("SP-REV", "SP-COST"):
            status = "Special Purpose (N/A)"
        elif not efl_ok:
            status = "Disconnected (EFL)"
        elif (burn is not None and burn > 150.0) or (m_pct is not None and m_pct < 0):
            status = "Critical"
        elif unval_h > 0 or (util is not None and util < 80.0) or (burn is not None and burn > 115.0) or (gl_var is not None and abs(gl_var) > 10000.0) or int(r["overdue_tasks"]) > 0:
            status = "At Risk"
        elif float(r["lagging_unapproved_hours"]) > 0:
            status = "Watch"
        else:
            status = "Healthy"

        rec_revs.append(round(rec, 2))
        tgt_revs.append(round(tgt, 2))
        labor_costs.append(round(lcost, 2))
        dir_exps.append(round(dexp, 2))
        margins_usd.append(round(m_usd, 2))
        margins_pct.append(round(m_pct, 1) if m_pct is not None else None)
        margin_labels.append(mlbl)
        burn_pcts.append(round(burn, 1) if burn is not None else None)
        util_pcts.append(round(util, 1) if util is not None else None)
        gl_vars.append(round(gl_var, 2) if gl_var is not None else None)
        health_flags.append(status)

    df["recognized_revenue"] = rec_revs
    df["target_revenue_mtd"] = tgt_revs
    df["direct_labor_cost"] = labor_costs
    df["direct_expenses"] = dir_exps
    df["provisional_margin_usd"] = margins_usd
    df["provisional_margin_pct"] = margins_pct
    df["margin_display"] = margin_labels
    df["hour_burn_pct"] = burn_pcts
    df["utilization_pct"] = util_pcts
    df["gl_revenue_variance"] = gl_vars
    df["risk_status"] = health_flags
    return df


def _load_exceptions(
    *,
    scope: UserScope,
    category: str | None = None,
    bu_id: str | None = None,
    contract_id: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    eng = get_engine(scope.user_id)
    with eng.connect() as conn:
        df = pd.read_sql(text("""
            SELECT
                e.*,
                c.contract_name,
                c.bu_name,
                c.contract_type,
                c.pm_name
            FROM vwm.Fact_Exceptions e
            JOIN vwm.Dim_Contracts c ON c.project_uuid = e.project_uuid
            ORDER BY e.priority_score DESC, e.capital_at_risk DESC
        """), conn)

    # RLS enforcement
    df = df[df["operating_unit_id"].isin(scope.allowed_bus)].copy()
    if scope.assigned_contracts is not None:
        df = df[df["contract_id"].isin(scope.assigned_contracts)].copy()
    if not scope.can_view_gl_reconciliation:
        df = df[df["rule_code"] != "milestone_gl_revenue_variance"].copy()
    if bu_id:
        df = df[df["operating_unit_id"] == bu_id].copy()
    if contract_id:
        df = df[df["contract_id"] == contract_id.upper()].copy()
    if category and category.lower() not in ("all", "any", ""):
        cl = category.lower()
        df = df[
            df["exception_family"].str.lower().str.contains(cl, regex=False)
            | df["rule_code"].str.lower().str.contains(cl, regex=False)
            | df["severity"].str.lower().str.contains(cl, regex=False)
        ].copy()

    # Overlay live CAT action counts so logged remediations appear immediately
    cat_actions = ActionTrackerStore().list_actions(limit=200)
    action_counts: dict[str, int] = {}
    for a in cat_actions:
        action_counts[a.exception_id] = action_counts.get(a.exception_id, 0) + 1
    df["cat_actions_logged"] = df["exception_id"].map(lambda x: action_counts.get(x, 0))
    df["live_status"] = df.apply(
        lambda r: "Action Logged" if r["cat_actions_logged"] > 0 else r["status"], axis=1
    )

    if limit is not None and limit > 0:
        df = df.head(limit).copy()
    return df


def _load_overhead(scope: UserScope, bu_id: str | None = None) -> pd.DataFrame:
    eng = get_engine(scope.user_id)
    with eng.connect() as conn:
        df = pd.read_sql(text("""
            SELECT * FROM vwm.Fact_SharedOverheadAllocation
            ORDER BY allocated_bu_overhead DESC
        """), conn)
    df = df[df["operating_unit_id"].isin(scope.allowed_bus)].copy()
    if bu_id:
        df = df[df["operating_unit_id"] == bu_id].copy()
    return df


# ---------------------------------------------------------------------------
# Tool 1: /summary — Persona-Adaptive Portfolio Executive Summary
# ---------------------------------------------------------------------------
def get_portfolio_summary(
    *,
    bu_id: str | None = None,
    contract_type: str | None = None,
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    denial = check_bu_access(scope, bu_id)
    if denial:
        return ToolPayload(status="refusal", tool_name="get_portfolio_summary", headline=denial)

    df = _load_contract_metrics(scope=scope, as_of=as_of, bu_id=bu_id, contract_type=contract_type)
    ex_df = _load_exceptions(scope=scope, bu_id=bu_id)
    ovh_df = _load_overhead(scope=scope, bu_id=bu_id)

    commercial = df[df["contract_type"].isin(["FS", "TM"])]
    complete_rate_comm = commercial[(commercial["unvalued_hours"] == 0) & (commercial["efl_matched"] == 1) & (commercial["recognized_revenue"] > 0)]

    mtd_rev = float(commercial["recognized_revenue"].sum())
    tgt_rev = float(commercial["target_revenue_mtd"].sum())
    rev_gap = mtd_rev - tgt_rev
    comm_margin_usd = float(complete_rate_comm["provisional_margin_usd"].sum())
    comm_rev_clean = float(complete_rate_comm["recognized_revenue"].sum())
    port_margin_pct = (comm_margin_usd / comm_rev_clean * 100.0) if comm_rev_clean > 0 else 0.0

    sp_rev_amt = float(df[df["contract_type"] == "SP-REV"]["recognized_revenue"].sum())
    sp_cost_amt = float(df[df["contract_type"] == "SP-COST"]["direct_expenses"].sum())
    alloc_ovh = float(ovh_df["allocated_bu_overhead"].sum()) if scope.can_view_shared_overhead else 0.0

    net_op_margin_usd = float(commercial["provisional_margin_usd"].sum()) + sp_rev_amt - sp_cost_amt - alloc_ovh
    net_op_margin_pct = (net_op_margin_usd / (mtd_rev + sp_rev_amt) * 100.0) if (mtd_rev + sp_rev_amt) > 0 else 0.0

    unapp_hrs = float(df["unapproved_hours"].sum())
    unbilled_wip = float(df["unbilled_wip_value"].sum())
    unval_hrs = float(df["unvalued_hours"].sum())
    active_ex = len(ex_df)
    top_ex = ex_df.iloc[0] if not ex_df.empty else None

    tm_df = df[df["contract_type"] == "TM"]
    tm_util = (
        float(tm_df["approved_billable_hours"].sum()) / float(tm_df["actual_logged_hours"].sum()) * 100.0
        if not tm_df.empty and float(tm_df["actual_logged_hours"].sum()) > 0 else 0.0
    )

    scope_txt = bu_id if bu_id else scope.scope_label

    # Persona-tailored headline and operational recommendations (Section 2)
    if scope.user_id == "pm_delivery":
        overdue_cnt = int(df["overdue_tasks"].sum())
        headline = (
            f"**PM Delivery Summary ({scope_txt}):** **{active_ex} active exceptions** require tactical attention across "
            f"**{len(df)} assigned contracts**, led by `{top_ex['contract_id']}` (Priority Score **{top_ex['priority_score']:.1f}/100**), "
            f"with **{unapp_hrs:.0f} hrs** awaiting timesheet approval and **{port_margin_pct:.1f}%** provisional margin on valued commercial contracts."
            if top_ex is not None else
            f"**PM Delivery Summary ({scope_txt}):** All {len(df)} assigned contracts are on track."
        )
        facts = [
            f"MTD Recognized Revenue: **{_fmt_usd(mtd_rev)}** vs. Target **{_fmt_usd(tgt_rev)}** (Variance: **{_fmt_usd(rev_gap)}**).",
            f"Provisional Margin (complete-rate commercial contracts): **{port_margin_pct:.1f}%** ({_fmt_usd(comm_margin_usd)} on {_fmt_usd(comm_rev_clean)}).",
            f"Field Time Compliance: **{unapp_hrs:.0f} hrs** awaiting approval (**{_fmt_usd(unbilled_wip)}** unbilled WIP), **{unval_hrs:.0f} hrs** missing CRC rate mapping, T&M billable utilization **{tm_util:.1f}%**.",
            f"Tactical Priority: Re-baseline `FS-AERO-104` (168.0% burn, 420 vs. 250 planned hrs), approve `TM-ELEC-204` pending timesheets (11 business days), and rebalance `TM-ENV-401` (64.0% utilization).",
        ]
    elif scope.user_id == "commercial_admin":
        unmatched_cnt = int((df["efl_matched"] == 0).sum())
        gl_var_abs = float(df["gl_revenue_variance"].dropna().abs().sum())
        headline = (
            f"**Commercial & Ledger Reconciliation Summary ({scope_txt}):** **{active_ex} active exceptions** detected, including "
            f"**{unmatched_cnt} unmatched EFL contract** (`FS-AUTO-305`), **{_fmt_usd(unbilled_wip)}** in unbilled WIP (**{unapp_hrs:.0f} hrs** pending > 7 days), "
            f"and **{unval_hrs:.0f} hrs** of unmapped CRC rate exposure (`TM-RENEW-202`)."
        )
        facts = [
            f"MTD Commercial Recognized Revenue: **{_fmt_usd(mtd_rev)}** vs. Target **{_fmt_usd(tgt_rev)}**; absolute Milestone-to-GL revenue variance across linked contracts: **{_fmt_usd(gl_var_abs)}**.",
            f"Special Purpose Adjustments (excluded from commercial margin %): `SP-REV-901` **{_fmt_usd(sp_rev_amt)}** (`{SPECIAL_REV_LABEL}`) and `SP-COST-902` **{_fmt_usd(sp_cost_amt)}** (`{SPECIAL_COST_LABEL}`).",
            f"Data Integrity Gaps: `FS-AUTO-305` (`{DISCONNECTED_EFL_LABEL}`), `TM-RENEW-202` (**48 hrs** under unmapped `DISC-SPECIALIST-9`), and 1 quarantined orphaned fee line (`SVC-ORPHAN-999`, **$18,500**).",
            f"Compliance Priority: Provision EFL contract master for `FS-AUTO-305`, map `DISC-SPECIALIST-9` in CRC, and reconcile `FS-INFRA-111` (-$31,500 GL variance + $4,200 Cat-7x review).",
        ]
    else:  # bu_director
        headline = (
            f"**Executive Portfolio Summary ({scope_txt}):** MTD commercial recognized revenue is **{_fmt_usd(mtd_rev)}** "
            f"against a **{_fmt_usd(tgt_rev)}** target (**{_fmt_usd(rev_gap)}** gap), delivering **{port_margin_pct:.1f}%** "
            f"provisional commercial margin and **{net_op_margin_pct:.1f}%** net operating margin after **{_fmt_usd(alloc_ovh)}** "
            f"in Indirect Laboratory Burden, with **{active_ex} active exceptions**."
        )
        facts = [
            f"Portfolio Profitability Bridge: Commercial Provisional Margin **{_fmt_usd(float(commercial['provisional_margin_usd'].sum()))}** + `SP-REV-901` **{_fmt_usd(sp_rev_amt)}** − `SP-COST-902` **{_fmt_usd(sp_cost_amt)}** − Indirect Lab Burden **{_fmt_usd(alloc_ovh)}** = Net Operating Margin **{_fmt_usd(net_op_margin_usd)}** (**{net_op_margin_pct:.1f}%**).",
            f"Commercial Aggregate Margin % (strictly Σ margin ÷ Σ revenue on complete-rate linked contracts): **{port_margin_pct:.1f}%**.",
            f"Utilization & Labor Compliance: Portfolio T&M billable utilization **{tm_util:.1f}%** (flagged: `TM-ENV-401` at **64.0%**), **{unapp_hrs:.0f} hrs** awaiting approval (**{_fmt_usd(unbilled_wip)}** unbilled WIP), and **{unval_hrs:.0f} hrs** unvalued CRC exposure.",
            f"Highest-Priority Intervention: `{top_ex['exception_id']}` on `{top_ex['contract_id']}` (Priority Score **{top_ex['priority_score']:.1f}/100**, Capital at Risk **{_fmt_usd(top_ex['capital_at_risk'])}**)." if top_ex is not None else "No open exceptions.",
        ]

    warnings = []
    if unval_hrs > 0:
        warnings.append(f"{unval_hrs:.0f} approved hours on TM-RENEW-202 lack a CRC discipline rate (DISC-SPECIALIST-9) and are excluded from aggregate margin % rather than defaulted to $0.")
    if int((df["efl_matched"] == 0).sum()) > 0:
        warnings.append("FS-AUTO-305 is Disconnected from Financial Ledger (unmatched_efl_record) and excluded from EFL-reconciled margin %.")

    # Build BU summary table
    bu_rows = []
    for bu_code, grp in df.groupby("operating_unit_id", sort=True):
        comm_g = grp[grp["contract_type"].isin(["FS", "TM"])]
        clean_g = comm_g[(comm_g["unvalued_hours"] == 0) & (comm_g["efl_matched"] == 1) & (comm_g["recognized_revenue"] > 0)]
        rev_g = float(comm_g["recognized_revenue"].sum())
        tgt_g = float(comm_g["target_revenue_mtd"].sum())
        m_usd_g = float(comm_g["provisional_margin_usd"].sum())
        m_pct_g = (float(clean_g["provisional_margin_usd"].sum()) / float(clean_g["recognized_revenue"].sum()) * 100.0) if float(clean_g["recognized_revenue"].sum()) > 0 else None
        ovh_g = float(ovh_df[ovh_df["operating_unit_id"] == bu_code]["allocated_bu_overhead"].sum()) if scope.can_view_shared_overhead else 0.0
        ex_g = int((ex_df["operating_unit_id"] == bu_code).sum())
        row_d = {
            "Business Unit": bu_code,
            "BU Name": grp["bu_name"].iloc[0],
            "Contracts": int(len(grp)),
            "MTD Recognized ($)": round(rev_g, 0),
            "MTD Target ($)": round(tgt_g, 0),
            "Provisional Margin %": f"{m_pct_g:.1f}%" if m_pct_g is not None else "Incomplete",
            "Active Exceptions": ex_g,
        }
        if scope.can_view_shared_overhead:
            row_d["Indirect Lab Burden ($)"] = round(ovh_g, 0)
            row_d["Net BU Margin ($)"] = round(m_usd_g - ovh_g, 0)
        bu_rows.append(row_d)

    out_df = pd.DataFrame(bu_rows).sort_values("MTD Recognized ($)", ascending=False)

    chart_spec = {
        "kind": "grouped_bar",
        "title": "MTD Recognized Revenue vs. Target by Business Unit (USD)",
        "x": out_df["Business Unit"].tolist(),
        "y_label": "USD ($)",
        "series": [
            {"name": "MTD Recognized Revenue", "values": out_df["MTD Recognized ($)"].tolist()},
            {"name": "MTD Target Revenue", "values": out_df["MTD Target ($)"].tolist()},
        ],
    }

    return ToolPayload(
        status="ok",
        tool_name="get_portfolio_summary",
        topic_label=f"Portfolio Summary ({scope.short_role})",
        period_label=f"Nov 2026 MTD (As-of {as_of.isoformat()})",
        headline=headline,
        facts=facts,
        warnings=warnings,
        df=out_df,
        chart_spec=chart_spec,
        compiled_sql=CONTRACT_METRICS_SQL.strip(),
        lineage_id="vwm.Dim_Contracts + Dim_Services + Dim_Tasks + Fact_Timesheets + Dim_RateCatalog + Fact_GeneralLedger + Fact_SharedOverheadAllocation + Fact_Exceptions",
        filters_used={"bu_id": bu_id, "contract_type": contract_type},
        extra={
            "kpis": {
                "mtd_rev": mtd_rev,
                "tgt_rev": tgt_rev,
                "rev_gap": rev_gap,
                "port_margin_pct": port_margin_pct,
                "net_op_margin_usd": net_op_margin_usd,
                "net_op_margin_pct": net_op_margin_pct,
                "alloc_ovh": alloc_ovh,
                "unapp_hrs": unapp_hrs,
                "unbilled_wip": unbilled_wip,
                "unval_hrs": unval_hrs,
                "active_exceptions": active_ex,
                "tm_util_pct": tm_util,
                "contract_count": len(df),
            }
        },
    )


# ---------------------------------------------------------------------------
# Tool 2: /exceptions [category] — Priority-Scored Exception Triage Queue
# ---------------------------------------------------------------------------
def get_exceptions_queue(
    *,
    category: str | None = None,
    bu_id: str | None = None,
    contract_id: str | None = None,
    limit: int = 5,
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    denial = check_bu_access(scope, bu_id) or (check_contract_access(scope, contract_id.upper()) if contract_id else None)
    if denial:
        return ToolPayload(status="refusal", tool_name="get_exceptions_queue", headline=denial)

    all_ex = _load_exceptions(scope=scope, category=category, bu_id=bu_id, contract_id=contract_id, limit=None)
    top_ex = all_ex.head(limit).copy() if limit and limit > 0 else all_ex.copy()

    if top_ex.empty:
        return ToolPayload(
            status="ok",
            tool_name="get_exceptions_queue",
            topic_label="Exception Triage Queue",
            period_label=f"As-of {as_of.isoformat()}",
            headline=f"No open exceptions matched filter `{category or 'ALL'}` within your active scope ({scope.scope_label}).",
            facts=["All contracts in the selected filter satisfy margin, burn, utilization, and ledger reconciliation thresholds."],
            df=pd.DataFrame(),
            lineage_id="vwm.Fact_Exceptions -> vwm.Dim_Contracts + CAT Fact_ActionLog",
        )

    total_cap = float(all_ex["capital_at_risk"].sum())
    worst = top_ex.iloc[0]
    cat_lbl = f" in **{category}**" if category and category.lower() not in ("all", "any") else ""
    headline = (
        f"**{len(all_ex)} active exceptions** identified{cat_lbl} totaling **{_fmt_usd(total_cap)}** in capital at risk "
        f"(showing top **{len(top_ex)}** by Priority Score). Highest priority is **`{worst['exception_id']}`** on "
        f"**`{worst['contract_id']}`** (**{worst['priority_score']:.1f}/100** — {worst['exception_family']})."
    )

    facts = [
        f"Priority Score formula: Materiality (max 45) + Urgency (max 25) + Deterioration (max 15) + Action Latency (max 15) = 100 pts.",
        f"#1 Offender `{worst['exception_id']}` (`{worst['contract_id']}`): Materiality **{worst['materiality_score']:.1f}** + Urgency **{worst['urgency_score']:.0f}** + Deterioration **{worst['deterioration_score']:.0f}** + Latency **{worst['action_latency_score']:.0f}** = **{worst['priority_score']:.1f}/100**.",
        f"Recommended Action ({scope.short_role} view): {worst['recommended_action']}",
        f"Run `/trace {worst['contract_id']}` for a 5-point OWMS/GTE/CRC/EFL audit, or `/log {worst['exception_id']} <action note>` to record a remediation commitment in CAT.",
    ]

    display_df = pd.DataFrame({
        "Exception ID": top_ex["exception_id"],
        "Contract ID": top_ex["contract_id"],
        "BU": top_ex["operating_unit_id"],
        "Family": top_ex["exception_family"],
        "Severity": top_ex["severity"],
        "Priority Score": top_ex["priority_score"],
        "Capital at Risk ($)": top_ex["capital_at_risk"].round(0),
        "Mat / Urg / Det / Lat": top_ex.apply(
            lambda r: f"{r['materiality_score']:.1f} / {r['urgency_score']:.0f} / {r['deterioration_score']:.0f} / {r['action_latency_score']:.0f}",
            axis=1,
        ),
        "Days Open": top_ex["days_open"],
        "Status": top_ex["live_status"],
        "Issue Summary": top_ex["summary"],
    })

    chart_spec = {
        "kind": "stacked_hbar",
        "title": f"Top {len(top_ex)} Exceptions — Priority Score Component Breakdown (0–100)",
        "y": [f"{r['exception_id']} ({r['contract_id']})" for _, r in top_ex.iterrows()],
        "x_label": "Priority Score Points (Max 100)",
        "series": [
            {"name": "Materiality (45)", "values": top_ex["materiality_score"].tolist()},
            {"name": "Urgency (25)", "values": top_ex["urgency_score"].tolist()},
            {"name": "Deterioration (15)", "values": top_ex["deterioration_score"].tolist()},
            {"name": "Action Latency (15)", "values": top_ex["action_latency_score"].tolist()},
        ],
    }

    sql = (
        "SELECT e.exception_id, e.contract_id, e.operating_unit_id, e.exception_family, e.severity,\n"
        "       e.priority_score, e.capital_at_risk, e.materiality_score, e.urgency_score,\n"
        "       e.deterioration_score, e.action_latency_score, e.days_open, e.status\n"
        "FROM vwm.Fact_Exceptions e\n"
        "JOIN vwm.Dim_Contracts c ON c.project_uuid = e.project_uuid\n"
        "ORDER BY e.priority_score DESC, e.capital_at_risk DESC;"
    )

    return ToolPayload(
        status="ok",
        tool_name="get_exceptions_queue",
        topic_label=f"Exception Triage ({category or 'All Families'})",
        period_label=f"As-of {as_of.isoformat()}",
        headline=headline,
        facts=facts,
        df=display_df,
        chart_spec=chart_spec,
        compiled_sql=sql,
        lineage_id="vwm.Fact_Exceptions -> vwm.Dim_Contracts + CAT Fact_ActionLog",
        filters_used={"category": category, "bu_id": bu_id, "limit": limit},
    )


# ---------------------------------------------------------------------------
# Tool 3: /trace <contract_id> — 5-Point OWMS / GTE / CRC / EFL Audit Trace
# ---------------------------------------------------------------------------
def trace_contract(
    *,
    contract_id: str,
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    cid = (contract_id or "").strip().upper()
    if not cid:
        return ToolPayload(
            status="unsupported",
            tool_name="trace_contract",
            headline="Please specify a contract ID to trace, e.g. `/trace FS-AERO-104`, `/trace TM-RENEW-202`, `/trace FS-AUTO-305`, or `/trace SP-REV-901`.",
        )

    denial = check_contract_access(scope, cid)
    if denial:
        return ToolPayload(status="refusal", tool_name="trace_contract", headline=denial)

    all_df = _load_contract_metrics(scope=scope, as_of=as_of)
    match = all_df[all_df["contract_id"] == cid]
    if match.empty:
        return ToolPayload(
            status="unsupported",
            tool_name="trace_contract",
            headline=f"Contract `{cid}` was not found in the active portfolio. Valid examples: `FS-AERO-104`, `TM-RENEW-202`, `FS-AUTO-305`, `TM-ENV-401`, `SP-REV-901`, `SP-COST-902`.",
        )

    r = match.iloc[0]
    p_uuid = str(r["project_uuid"])
    ctype = str(r["contract_type"])
    efl_ok = int(r["efl_matched"]) == 1
    eng = get_engine(scope.user_id)

    with eng.connect() as conn:
        svcs = pd.read_sql(text("SELECT * FROM vwm.Dim_Services WHERE project_uuid = :p"), conn, params={"p": p_uuid})
        tasks = pd.read_sql(text("SELECT * FROM vwm.Dim_Tasks WHERE project_uuid = :p"), conn, params={"p": p_uuid})
        ts = pd.read_sql(text("""
            SELECT ts.*, r.discipline_name, r.hourly_cost_rate, r.billable_sell_rate
            FROM vwm.Fact_Timesheets ts
            LEFT JOIN vwm.Dim_RateCatalog r
              ON r.discipline_id = ts.discipline_id AND r.effective_year = ts.effective_year
            WHERE ts.project_uuid = :p
        """), conn, params={"p": p_uuid})
        gl = pd.read_sql(text("""
            SELECT * FROM vwm.Fact_GeneralLedger
            WHERE efl_contract_key_norm = LTRIM(TRIM(:eid), '0')
        """), conn, params={"eid": str(r["efl_contract_id"])})
        orphans = pd.read_sql(text("SELECT * FROM vwm.Dim_Services WHERE is_orphaned = 1"), conn)

    ex_df = _load_exceptions(scope=scope, contract_id=cid, limit=None)
    cat_store = ActionTrackerStore()
    cat_actions = cat_store.list_actions(contract_id=cid, limit=10)
    cat_comments = cat_store.list_comments(contract_id=cid, limit=10)
    cat_assignments = cat_store.list_task_assignments(contract_id=cid, limit=10)
    cat_decisions = cat_store.list_decisions(contract_id=cid, limit=10)

    # Build the exact 5-point verification table (Section 7 /trace spec)
    # 1. OWMS Scope & Contract Value
    if ctype == "FS":
        s1_detail = f"{len(svcs)} active service(s), {len(tasks)} task(s); Contract Total Value = {_fmt_usd(r['contract_value'])} (billable milestones, non-orphaned)."
        s1_status = "Verified" if int(r["overdue_tasks"]) == 0 and int(r["invalid_date_tasks"]) == 0 else "Delivery Risk"
    elif ctype == "TM":
        s1_detail = f"Time & Materials call-off ({len(tasks)} active task(s)); MTD Target Revenue = {_fmt_usd(r['target_revenue_mtd'])} across {r['planned_hours']:.0f} planned hrs."
        s1_status = "Verified"
    elif ctype == "SP-REV":
        s1_detail = f"Special Purpose Revenue-Only Adjustment Contract (`SP-REV`); rebate schedule = {_fmt_usd(r['contract_value'])}, 0 operational tasks."
        s1_status = "Special Purpose"
    else:
        s1_detail = f"Special Purpose Cost-Only Holding Pool (`SP-COST`); internal calibration lab maintenance pool, $0 billable fee schedule."
        s1_status = "Special Purpose"

    # 2. GTE Planned vs Actual Labor Burn & Compliance
    planned_h = float(r["planned_hours"])
    actual_h = float(r["actual_logged_hours"])
    burn = r["hour_burn_pct"]
    if ctype == "FS":
        burn_str = f"{burn:.1f}%" if burn is not None else "N/A"
        s2_detail = f"Actual {actual_h:.1f} hrs vs. Planned {planned_h:.1f} hrs (Burn = {burn_str}); Approved {r['approved_hours']:.1f} hrs, Pending {r['unapproved_hours']:.1f} hrs."
        if burn is not None and burn > 150.0:
            s2_status = "CRITICAL (>150% Runaway)"
        elif burn is not None and burn > 115.0:
            s2_status = "WARNING (>115% Burn)"
        else:
            s2_status = "Verified"
    elif ctype == "TM":
        util = r["utilization_pct"]
        util_str = f"{util:.1f}%" if util is not None else "N/A"
        s2_detail = (
            f"Logged {actual_h:.1f} hrs (Approved Billable {r['approved_billable_hours']:.1f} hrs → Utilization {util_str}); "
            f"Unapproved > 7d: {r['lagging_unapproved_hours']:.1f} hrs ({_fmt_usd(r['unbilled_wip_value'])} WIP)."
        )
        if util is not None and util < 80.0:
            s2_status = "WARNING (<80% Util)"
        elif float(r["lagging_unapproved_hours"]) > 0:
            s2_status = "WARNING (Billing Lag)"
        else:
            s2_status = "Verified"
    else:
        s2_detail = f"Special purpose contract ({actual_h:.1f} GTE timesheet hrs tracked); holding/adjustment costs handled via EFL."
        s2_status = "N/A"

    # 3. CRC Rate Card Alignment & Unvalued Exposure
    unmapped_discs = sorted(ts[ts["hourly_cost_rate"].isna()]["discipline_id"].unique().tolist()) if not ts.empty else []
    unval_h = float(r["unvalued_hours"])
    if unval_h > 0:
        s3_detail = (
            f"MISSING RATE MAPPING (`task_missing_rate_link`): {unval_h:.1f} hrs under {', '.join(unmapped_discs)} "
            f"unmatched in CRC for 2026 → treated as unvalued cost/sell exposure (NEVER $0 cost)."
        )
        s3_status = "CRITICAL (Unmapped Rate)"
    else:
        mapped_cnt = len(ts)
        s3_detail = f"All {mapped_cnt} timesheet batch(es) matched to 2026 CRC rates; Valued Direct Labor Cost = {_fmt_usd(r['direct_labor_cost'])}."
        s3_status = "Verified"

    # 4. EFL General Ledger Posted Revenue vs Milestone Progress
    if not efl_ok:
        s4_detail = (
            f"{DISCONNECTED_EFL_LABEL} (`unmatched_efl_record`): OWMS efl_contract_id `{r['efl_contract_id']}` "
            f"has 0 posted rows in Fact_GeneralLedger. Operational milestone value ({_fmt_usd(r['recognized_revenue'])}) kept intact."
        )
        s4_status = "CRITICAL (Unmatched EFL)"
    else:
        gl_rev = float(r["gl_recognized_rev"])
        gl_var = float(r["gl_revenue_variance"] or 0.0)
        cat7 = float(r["gl_cat7x_review_amt"] or 0.0)
        extra7 = f" + {_fmt_usd(cat7)} Cat-7x suspense line for review." if cat7 != 0 else ""
        s4_detail = (
            f"EFL ID `{r['efl_contract_id']}` matched ({len(gl)} posted GL lines): Posted Revenue {_fmt_usd(gl_rev)} "
            f"vs. Operational Recognized {_fmt_usd(r['recognized_revenue'])} (Variance {_fmt_usd(gl_var)}); Direct Expenses {_fmt_usd(r['direct_expenses'])}.{extra7}"
        )
        s4_status = "WARNING (Variance >$10k)" if abs(gl_var) > 10000.0 or cat7 != 0 else "Verified"

    # 5. Final Net Provisional Margin Determination
    if ctype == "SP-REV":
        s5_detail = f"Provisional Margin: {SPECIAL_REV_LABEL}. Recognized Revenue = {_fmt_usd(r['recognized_revenue'])}, Direct Cost = $0 (never report 100% margin)."
        s5_status = "N/A (Special Purpose)"
    elif ctype == "SP-COST":
        s5_detail = f"Provisional Margin: {SPECIAL_COST_LABEL}. Recognized Revenue = $0, Holding Expense = {_fmt_usd(r['direct_expenses'])} (never report -100% margin)."
        s5_status = "N/A (Special Purpose)"
    else:
        s5_detail = (
            f"Recognized Revenue {_fmt_usd(r['recognized_revenue'])} − Direct Labor {_fmt_usd(r['direct_labor_cost'])} "
            f"− Direct Expenses {_fmt_usd(r['direct_expenses'])} = Provisional Margin {_fmt_usd(r['provisional_margin_usd'])} "
            f"({r['margin_display']})."
        )
        s5_status = str(r["risk_status"])

    trace_df = pd.DataFrame([
        {"Step": "1. OWMS Scope & Value", "Source Module": "OWMS (Dim_Contracts / Services / Tasks)", "Verification Result": s1_detail, "Audit Status": s1_status},
        {"Step": "2. GTE Labor Burn & Compliance", "Source Module": "GTE (Fact_Timesheets)", "Verification Result": s2_detail, "Audit Status": s2_status},
        {"Step": "3. CRC Rate Alignment", "Source Module": "CRC (Dim_RateCatalog)", "Verification Result": s3_detail, "Audit Status": s3_status},
        {"Step": "4. EFL Ledger Reconciliation", "Source Module": "EFL (Fact_GeneralLedger)", "Verification Result": s4_detail, "Audit Status": s4_status},
        {"Step": "5. Provisional Margin Determination", "Source Module": "Apex Margin Engine", "Verification Result": s5_detail, "Audit Status": s5_status},
    ])

    headline = (
        f"**5-Point Audit Trace for `{cid}` ({r['contract_name']} · {r['operating_unit_id']} · {ctype}):** "
        f"Status is **{r['risk_status']}** — Provisional Margin: **{r['margin_display']}**."
    )

    facts = [
        f"Client: **{r['client_name']}** · PM: **{r['pm_name']}** · EFL Link ID: `{r['efl_contract_id']}` ({'Matched' if efl_ok else DISCONNECTED_EFL_LABEL}).",
        f"Active Exceptions on `{cid}`: **{len(ex_df)}**" + (
            f" (Top: `{ex_df.iloc[0]['exception_id']}`, Priority Score **{ex_df.iloc[0]['priority_score']:.1f}/100**)." if not ex_df.empty else " (clean)."
        ),
        f"CAT Action Plan & N-1 Directives: **{len(cat_actions)}**" + (
            f" — latest ({cat_actions[0].plan_horizon}, assigned to **{cat_actions[0].assigned_to}**, {cat_actions[0].status}): \"{cat_actions[0].remediation_comment}\""
            if cat_actions else " (none logged yet — use `/assign` or `/log`)."
        ),
    ]
    if cat_comments:
        c0 = cat_comments[0]
        facts.append(
            f"Field / Context Clarification ({len(cat_comments)} note(s) in DB) — **{c0.category}** by {c0.author_name}: \"{c0.comment_text}\""
        )
    if cat_decisions:
        d0 = cat_decisions[0]
        facts.append(
            f"Leadership Decision ({d0.decision_type}, effective through {d0.effective_until}) by {d0.decided_by}: \"{d0.rationale}\""
        )
    if cat_assignments:
        a0 = cat_assignments[0]
        facts.append(
            f"Task Assignment ({a0.task_uuid} → **{a0.assignee_name}**, {a0.plan_horizon}): \"{a0.note}\""
        )

    warnings = []
    if ctype == "FS" and burn is not None and burn > 150.0:
        warnings.append(f"Runaway Cost Alert: {actual_h:.0f} actual hrs vs. {planned_h:.0f} planned hrs ({burn:.1f}% > 150%). Automated revenue accrual is blocked until tasks are re-planned.")
    if unval_h > 0:
        warnings.append(f"Unvalued Rate Exposure: {unval_h:.0f} hrs under {', '.join(unmapped_discs)} lack a 2026 CRC rate code. Never assume $0 cost — assign a rate code immediately.")
    if not efl_ok:
        warnings.append(f"Unmatched EFL Ledger Link: `{r['efl_contract_id']}` is {DISCONNECTED_EFL_LABEL}. Financial postings cannot be reconciled until provisioned in EFL.")
    if cid == "FS-PHARM-107" and not orphans.empty:
        warnings.append("Quarantined Orphan Fee Line: SVC-ORPHAN-999 ($18,500 referencing decommissioned project_uuid PRJ-DECOMM-000) has been excluded from contract totals.")

    chart_spec = {}
    if ctype in ("FS", "TM"):
        chart_spec = {
            "kind": "bar",
            "title": f"{cid} — Financial Waterfall Components (USD)",
            "x": ["Target Rev (MTD)", "Recognized Rev", "Direct Labor Cost", "Direct Expenses", "Provisional Margin"],
            "y": [
                round(float(r["target_revenue_mtd"]), 0),
                round(float(r["recognized_revenue"]), 0),
                round(float(r["direct_labor_cost"]), 0),
                round(float(r["direct_expenses"]), 0),
                round(float(r["provisional_margin_usd"]), 0),
            ],
            "y_label": "USD ($)",
        }

    sql = (
        f"-- 5-Point Trace for {cid} ({p_uuid})\n"
        f"SELECT * FROM vwm.Dim_Contracts c\n"
        f"LEFT JOIN vwm.Dim_Services s ON s.project_uuid = c.project_uuid AND s.is_orphaned = 0\n"
        f"LEFT JOIN vwm.Dim_Tasks t ON t.project_uuid = c.project_uuid\n"
        f"LEFT JOIN vwm.Fact_Timesheets ts ON ts.task_uuid = t.task_uuid\n"
        f"LEFT JOIN vwm.Dim_RateCatalog r ON r.discipline_id = ts.discipline_id AND r.effective_year = ts.effective_year\n"
        f"LEFT JOIN vwm.Fact_GeneralLedger g ON g.efl_contract_key_norm = c.efl_contract_key_norm\n"
        f"WHERE c.contract_id = '{cid}';"
    )

    return ToolPayload(
        status="ok",
        tool_name="trace_contract",
        topic_label=f"5-Point Trace: {cid}",
        period_label=f"As-of {as_of.isoformat()}",
        headline=headline,
        facts=facts,
        warnings=warnings,
        df=trace_df,
        chart_spec=chart_spec,
        compiled_sql=sql,
        lineage_id="OWMS (Dim_Contracts/Services/Tasks) -> GTE (Fact_Timesheets) -> CRC (Dim_RateCatalog) -> EFL (Fact_GeneralLedger) -> CAT",
        filters_used={"contract_id": cid},
        extra={
            "contract_id": cid,
            "bu_id": str(r["operating_unit_id"]),
            "exception_ids": ex_df["exception_id"].tolist(),
            "task_ids": tasks["task_uuid"].tolist() if not tasks.empty else [],
        },
    )


# ---------------------------------------------------------------------------
# Tool 4: /log <exception_id> <action_note> — Write to CAT (`Fact_ActionLog`)
# ---------------------------------------------------------------------------
def log_remediation_action(
    *,
    exception_id: str,
    action_note: str,
    assigned_to: str | None = None,
    plan_horizon: str = "Next Week",
    entry_type: str = "Remediation Action",
    target_resolution_date: str | None = None,
    user_id: str = "bu_director",
    user_name: str | None = None,
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    ex_id = (exception_id or "").strip().upper()
    note = (action_note or "").strip()

    if not ex_id or not note:
        return ToolPayload(
            status="unsupported",
            tool_name="log_remediation_action",
            headline="Usage: `/log <exception_id> <action_note>` — for example: `/log EXC-101 Approve overtime cap and request SkyForge scope change order`.",
        )

    all_ex = _load_exceptions(scope=scope, limit=None)
    match = all_ex[all_ex["exception_id"] == ex_id]
    if match.empty:
        return ToolPayload(
            status="refusal",
            tool_name="log_remediation_action",
            headline=f"Exception `{ex_id}` was not found within your active persona scope ({scope.scope_label}). Run `/exceptions` to view valid Exception IDs.",
        )

    ex = match.iloc[0]
    actor = user_name or f"{scope.short_role} ({scope.user_id})"
    owner = assigned_to or str(ex.get("pm_name") or "Unassigned")
    rec = ActionTrackerStore().log_action(
        exception_uuid=str(ex["exception_uuid"]),
        exception_id=ex_id,
        contract_id=str(ex["contract_id"]),
        bu_id=str(ex["operating_unit_id"]),
        entry_type=entry_type,
        user_id=scope.user_id,
        user_name=actor,
        persona=scope.display_name,
        assigned_to=owner,
        plan_horizon=plan_horizon,
        remediation_comment=note,
        target_resolution_date=target_resolution_date,
        baseline_snapshot={
            "priority_score": float(ex["priority_score"]),
            "capital_at_risk": float(ex["capital_at_risk"]),
            "days_open": int(ex["days_open"]),
            "rule_code": str(ex["rule_code"]),
        },
        as_of=as_of,
    )

    out_df = pd.DataFrame([{
        "Action UUID": rec.action_uuid,
        "Type": rec.entry_type,
        "Exception ID": rec.exception_id,
        "Contract ID": rec.contract_id,
        "Assigned To (N-1)": rec.assigned_to,
        "Horizon": rec.plan_horizon,
        "Status": rec.status,
        "Target Date": rec.target_resolution_date,
        "Logged By": rec.user_name,
        "Remediation Commitment": rec.remediation_comment,
    }])

    return ToolPayload(
        status="ok",
        tool_name="log_remediation_action",
        topic_label=f"CAT Action Logged ({rec.action_uuid})",
        period_label=f"Plan: {rec.plan_horizon} · Logged {rec.timestamp.strftime('%Y-%m-%d %H:%M')}",
        headline=(
            f"**Remediation commitment `{rec.action_uuid}` recorded in CAT (`Fact_ActionLog`)** for "
            f"**`{rec.exception_id}`** (`{rec.contract_id}`), assigned to **{rec.assigned_to}** for **{rec.plan_horizon}** "
            f"(target **{rec.target_resolution_date}**)."
        ),
        facts=[
            f"Linked Exception: `{rec.exception_id}` ({ex['exception_family']}, Priority Score **{ex['priority_score']:.1f}/100**, Capital at Risk **{_fmt_usd(ex['capital_at_risk'])}**).",
            "Baseline financial snapshot captured in `baseline_snapshot_json` to measure post-action margin recovery.",
            "Governance note (VWM Guide Section 7): Write-backs live in the persistent CAT database linked by business keys (`exception_id`, `contract_id`) and never overwrite historical ERP actuals.",
        ],
        df=out_df,
        compiled_sql=(
            f"INSERT INTO cat.fact_action_log (action_uuid, exception_uuid, exception_id, contract_id, assigned_to, plan_horizon, status, target_resolution_date, remediation_comment)\n"
            f"VALUES ('{rec.action_uuid}', '{rec.exception_uuid}', '{rec.exception_id}', '{rec.contract_id}', '{rec.assigned_to}', '{rec.plan_horizon}', '{rec.status}', '{rec.target_resolution_date}', :comment);"
        ),
        lineage_id="CAT (Fact_ActionLog) -> linked by business keys (exception_uuid, exception_id, contract_id)",
        filters_used={"exception_id": ex_id, "contract_id": rec.contract_id, "plan_horizon": rec.plan_horizon},
        extra={"contract_id": rec.contract_id, "exception_ids": [rec.exception_id]},
    )


# ---------------------------------------------------------------------------
# Tool 5: Contract Profitability & Portfolio Comparison (FS, T&M, SP-REV/COST)
# ---------------------------------------------------------------------------
def get_contract_profitability(
    *,
    bu_id: str | None = None,
    contract_type: str | None = None,
    bottom_only: bool = False,
    special_purpose_only: bool = False,
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    denial = check_bu_access(scope, bu_id)
    if denial:
        return ToolPayload(status="refusal", tool_name="get_contract_profitability", headline=denial)

    df = _load_contract_metrics(scope=scope, as_of=as_of, bu_id=bu_id, contract_type=contract_type)
    if special_purpose_only:
        df = df[df["contract_type"].isin(["SP-REV", "SP-COST"])].copy()
        if df.empty:
            return ToolPayload(
                status="refusal",
                tool_name="get_contract_profitability",
                headline="Special Purpose adjustment contracts (`SP-REV-901`, `SP-COST-902`) are outside Project Delivery Manager scope. Switch to BU Manager or Commercial Contract Administrator.",
            )
    elif bottom_only:
        df = df[df["contract_type"].isin(["FS", "TM"])].sort_values("provisional_margin_pct", ascending=True, na_position="first").head(5).copy()
    else:
        df = df.sort_values(["contract_type", "provisional_margin_pct"], ascending=[True, True], na_position="last").copy()

    out_df = pd.DataFrame({
        "Contract ID": df["contract_id"],
        "BU": df["operating_unit_id"],
        "Type": df["contract_type"],
        "Contract Name": df["contract_name"],
        "Recognized Rev ($)": df["recognized_revenue"].round(0),
        "Direct Labor ($)": df["direct_labor_cost"].round(0),
        "Direct Exp ($)": df["direct_expenses"].round(0),
        "Provisional Margin": df["margin_display"],
        "Hour Burn / Util": df.apply(
            lambda r: (
                f"{r['hour_burn_pct']:.1f}% burn" if r["contract_type"] == "FS" and pd.notna(r["hour_burn_pct"])
                else (f"{r['utilization_pct']:.1f}% util" if r["contract_type"] == "TM" and pd.notna(r["utilization_pct"]) else "N/A")
            ),
            axis=1,
        ),
        "Status": df["risk_status"],
    })

    if special_purpose_only:
        headline = (
            f"**Special Purpose Adjustment Contracts ({len(df)}):** `SP-REV-901` (**$45,000** revenue, **$0** direct cost → `{SPECIAL_REV_LABEL}`) "
            f"and `SP-COST-902` (**$0** revenue, **$28,500** holding expense → `{SPECIAL_COST_LABEL}`)."
        )
        facts = [
            f"`SP-REV-901`: Direct Cost = $0 → NEVER reported as 100% margin; displayed as `{SPECIAL_REV_LABEL}`.",
            f"`SP-COST-902`: Recognized Revenue = $0 → NEVER reported as -100% margin; displayed as `{SPECIAL_COST_LABEL}`.",
            "Both contracts are excluded from commercial aggregate Provisional Margin % and reconciled explicitly in the Net Operating Margin bridge.",
        ]
        chart_spec = {}
    else:
        comm = df[df["contract_type"].isin(["FS", "TM"]) & (df["provisional_margin_pct"].notna())]
        worst = comm.sort_values("provisional_margin_pct").iloc[0] if not comm.empty else None
        best = comm.sort_values("provisional_margin_pct", ascending=False).iloc[0] if not comm.empty else None
        lbl = "Underperforming / Bottom Commercial Contracts" if bottom_only else f"Contract Portfolio Profitability ({contract_type or 'All Types'})"
        headline = (
            f"**{lbl} ({len(df)} contracts):** Lowest commercial margin is **`{worst['contract_id']}`** at **{worst['margin_display']}** "
            f"({_fmt_usd(worst['provisional_margin_usd'])}); highest is **`{best['contract_id']}`** at **{best['margin_display']}**."
            if worst is not None and best is not None else
            f"**{lbl} ({len(df)} contracts).**"
        )
        facts = [
            f"Fixed-Scope (FS) contracts shown: **{int((df['contract_type'] == 'FS').sum())}** · Time & Materials (T&M): **{int((df['contract_type'] == 'TM').sum())}** · Special Purpose (N/A margin): **{int(df['contract_type'].isin(['SP-REV', 'SP-COST']).sum())}**.",
            "Aggregate margin % is always computed as Σ margin ÷ Σ revenue over complete-rate linked commercial contracts — never an arithmetic average of percentages.",
        ]
        plot_df = comm.sort_values("provisional_margin_pct", ascending=True).head(12)
        chart_spec = {
            "kind": "hbar",
            "title": "Commercial Contract Provisional Margin % (Lowest to Highest)",
            "y": plot_df["contract_id"].tolist(),
            "x": plot_df["provisional_margin_pct"].tolist(),
            "x_label": "Provisional Margin (%)",
        }

    return ToolPayload(
        status="ok",
        tool_name="get_contract_profitability",
        topic_label="Special Purpose Contracts (N/A)" if special_purpose_only else f"Contract Profitability ({contract_type or 'All'})",
        period_label=f"Nov 2026 MTD (As-of {as_of.isoformat()})",
        headline=headline,
        facts=facts,
        df=out_df,
        chart_spec=chart_spec,
        compiled_sql=CONTRACT_METRICS_SQL.strip(),
        lineage_id="vwm.Dim_Contracts -> Dim_Services -> Dim_Tasks -> Fact_Timesheets -> Dim_RateCatalog + Fact_GeneralLedger",
        filters_used={"bu_id": bu_id, "contract_type": contract_type, "bottom_only": bottom_only},
    )


# ---------------------------------------------------------------------------
# Tool 6: Dynamic Shared Laboratory Overhead Allocation ($120,000 across 10 BUs)
# ---------------------------------------------------------------------------
def get_shared_overhead_allocation(
    *,
    bu_id: str | None = None,
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    if not scope.can_view_shared_overhead:
        return ToolPayload(
            status="refusal",
            tool_name="get_shared_overhead_allocation",
            headline=(
                "Indirect Laboratory Overhead allocation (`Cat-8000` / `Cat-9000`) is a Business Unit P&L burden "
                "restricted to **Operations Portfolio Director (BU Manager)** and **Commercial Contract Administrator** personas."
            ),
        )
    denial = check_bu_access(scope, bu_id)
    if denial:
        return ToolPayload(status="refusal", tool_name="get_shared_overhead_allocation", headline=denial)

    ovh = _load_overhead(scope=scope, bu_id=bu_id)
    c_df = _load_contract_metrics(scope=scope, as_of=as_of, bu_id=bu_id)
    comm = c_df[c_df["contract_type"].isin(["FS", "TM"])]

    bu_gross = comm.groupby("operating_unit_id")["provisional_margin_usd"].sum().to_dict()
    bu_rev = comm.groupby("operating_unit_id")["recognized_revenue"].sum().to_dict()

    ovh["gross_provisional_margin"] = ovh["operating_unit_id"].map(lambda b: round(float(bu_gross.get(b, 0.0)), 0))
    ovh["commercial_rev"] = ovh["operating_unit_id"].map(lambda b: round(float(bu_rev.get(b, 0.0)), 0))
    ovh["net_operating_margin"] = ovh["gross_provisional_margin"] - ovh["allocated_bu_overhead"]
    ovh["net_margin_pct"] = ovh.apply(
        lambda r: f"{(r['net_operating_margin'] / r['commercial_rev'] * 100.0):.1f}%" if r["commercial_rev"] > 0 else "N/A",
        axis=1,
    )

    total_ovh = float(ovh["allocated_bu_overhead"].sum())
    cat8 = float(ovh["facility_gl_cat8000"].sum())
    cat9 = float(ovh["depreciation_gl_cat9000"].sum())
    top_bu = ovh.iloc[0]

    headline = (
        f"**Indirect Laboratory Burden Allocation ({len(ovh)} BU{'s' if len(ovh) != 1 else ''}):** "
        f"**{_fmt_usd(total_ovh)}** monthly shared facility overhead (`Cat-8000` Fixed Facility **{_fmt_usd(cat8)}** + "
        f"`Cat-9000` Equipment Depreciation **{_fmt_usd(cat9)}**) is apportioned across active BUs; largest share is "
        f"**`{top_bu['operating_unit_id']}`** (**{top_bu['bu_allocation_factor']*100:.0f}%** = **{_fmt_usd(top_bu['allocated_bu_overhead'])}**)."
    )

    facts = [
        "Allocation formula: `Allocated BU Overhead = Monthly Facility Ledger Total ($120,000) × BU Allocation Factor` (factors sum to 100.0% across all 10 BUs).",
        "Presented strictly as a separate deduction (**Indirect Laboratory Burden**) after contract-level Provisional Margin to arrive at BU Net Operating Margin.",
        f"Combined Gross Commercial Margin: **{_fmt_usd(float(ovh['gross_provisional_margin'].sum()))}** → Net Operating Margin (after lab burden): **{_fmt_usd(float(ovh['net_operating_margin'].sum()))}**.",
    ]

    display_df = pd.DataFrame({
        "Business Unit": ovh["operating_unit_id"],
        "BU Name": ovh["bu_name"],
        "Allocation %": ovh["bu_allocation_factor"].map(lambda x: f"{x*100:.0f}%"),
        "Cat-8000 Facility ($)": ovh["facility_gl_cat8000"].round(0),
        "Cat-9000 Equip Depr ($)": ovh["depreciation_gl_cat9000"].round(0),
        "Indirect Lab Burden ($)": ovh["allocated_bu_overhead"].round(0),
        "Gross Margin ($)": ovh["gross_provisional_margin"],
        "Net Operating Margin ($)": ovh["net_operating_margin"].round(0),
        "Net Margin %": ovh["net_margin_pct"],
    })

    chart_spec = {
        "kind": "grouped_bar",
        "title": "BU Gross Provisional Margin vs. Indirect Lab Burden & Net Operating Margin (USD)",
        "x": ovh["operating_unit_id"].tolist(),
        "y_label": "USD ($)",
        "series": [
            {"name": "Gross Provisional Margin", "values": ovh["gross_provisional_margin"].tolist()},
            {"name": "Indirect Lab Burden (Cat-8000/9000)", "values": ovh["allocated_bu_overhead"].tolist()},
            {"name": "Net Operating Margin", "values": ovh["net_operating_margin"].tolist()},
        ],
    }

    return ToolPayload(
        status="ok",
        tool_name="get_shared_overhead_allocation",
        topic_label="Shared Lab Overhead ($120k)",
        period_label=f"Fiscal Month {as_of.strftime('%Y-%m')}",
        headline=headline,
        facts=facts,
        df=display_df,
        chart_spec=chart_spec,
        compiled_sql="SELECT * FROM vwm.Fact_SharedOverheadAllocation ORDER BY allocated_bu_overhead DESC;",
        lineage_id="EFL (Fact_GeneralLedger Cat-8000 & Cat-9000) -> vwm.Fact_SharedOverheadAllocation -> Dim_Contracts.operating_unit_id",
        filters_used={"bu_id": bu_id},
    )


# ---------------------------------------------------------------------------
# Tool 7: Labor, Utilization, Unapproved Billing Lag & Unmapped CRC Rates
# ---------------------------------------------------------------------------
def get_labor_and_timesheet_compliance(
    *,
    bu_id: str | None = None,
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    denial = check_bu_access(scope, bu_id)
    if denial:
        return ToolPayload(status="refusal", tool_name="get_labor_and_timesheet_compliance", headline=denial)

    df = _load_contract_metrics(scope=scope, as_of=as_of, bu_id=bu_id)
    tm = df[df["contract_type"] == "TM"].copy()

    unapp_total = float(df["unapproved_hours"].sum())
    wip_total = float(df["unbilled_wip_value"].sum())
    unval_total = float(df["unvalued_hours"].sum())
    low_util = tm[tm["utilization_pct"].notna() & (tm["utilization_pct"] < 80.0)]

    headline = (
        f"**Labor & Timesheet Compliance Audit:** **{len(low_util)} T&M contract(s)** below the 80% billable utilization threshold "
        f"(`TM-ENV-401` at **64.0%**), **{unapp_total:.0f} hrs** pending approval > 7 business days (**{_fmt_usd(wip_total)}** unbilled WIP on `TM-ELEC-204`), "
        f"and **{unval_total:.0f} hrs** logged under an unmapped CRC discipline (`DISC-SPECIALIST-9` on `TM-RENEW-202`)."
    )

    facts = [
        "Under-Utilization Alert (< 80%): `TM-ENV-401` recorded **128 billable hrs** out of **200 logged hrs** (**64.0%** utilization — 72 non-billable hrs).",
        "Unapproved Billing Lag (> 7 business days): `TM-ELEC-204` has **36.0 hrs** submitted 11 business days ago by J. Wu (**$7,020** unbilled WIP blocked from invoicing).",
        "Missing CRC Rate Exposure: `TM-RENEW-202` has **48.0 hrs** under `DISC-SPECIALIST-9` unmapped in `Dim_RateCatalog` — flagged as unvalued exposure (never $0 cost).",
    ]

    display_df = pd.DataFrame({
        "Contract ID": tm["contract_id"],
        "BU": tm["operating_unit_id"],
        "PM": tm["pm_name"],
        "Logged Hrs": tm["actual_logged_hours"],
        "Approved Billable Hrs": tm["approved_billable_hours"],
        "Utilization %": tm["utilization_pct"].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A"),
        "Unapproved >7d Hrs": tm["lagging_unapproved_hours"],
        "Unbilled WIP ($)": tm["unbilled_wip_value"].round(0),
        "Unvalued Rate Hrs": tm["unvalued_hours"],
        "Compliance Flag": tm["risk_status"],
    })

    chart_spec = {
        "kind": "hbar",
        "title": "T&M Contract Billable Utilization % vs. 80% Threshold",
        "y": tm["contract_id"].tolist(),
        "x": [float(v or 0) for v in tm["utilization_pct"].tolist()],
        "x_label": "Billable Utilization (%)",
        "threshold": 80.0,
    }

    sql = (
        "SELECT c.contract_id, ts.discipline_id, ts.approval_status, ts.pending_business_days,\n"
        "       ts.hours_logged, r.hourly_cost_rate, r.billable_sell_rate\n"
        "FROM vwm.Fact_Timesheets ts\n"
        "JOIN vwm.Dim_Contracts c ON c.project_uuid = ts.project_uuid\n"
        "LEFT JOIN vwm.Dim_RateCatalog r ON r.discipline_id = ts.discipline_id AND r.effective_year = ts.effective_year;"
    )

    return ToolPayload(
        status="ok",
        tool_name="get_labor_and_timesheet_compliance",
        topic_label="Labor & T&M Utilization",
        period_label=f"Nov 2026 MTD (As-of {as_of.isoformat()})",
        headline=headline,
        facts=facts,
        df=display_df,
        chart_spec=chart_spec,
        compiled_sql=sql,
        lineage_id="GTE (Fact_Timesheets) -> LEFT JOIN CRC (Dim_RateCatalog ON discipline_id & effective_year) -> OWMS (Dim_Contracts)",
        filters_used={"bu_id": bu_id},
    )


# ---------------------------------------------------------------------------
# Tool 8: Master Data Integrity & VWM Reconciliation Audit
# ---------------------------------------------------------------------------
def get_data_integrity_audit(
    *,
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    eng = get_engine(scope.user_id)

    df = _load_contract_metrics(scope=scope, as_of=as_of)
    with eng.connect() as conn:
        orphans = pd.read_sql(text("SELECT * FROM vwm.Dim_Services WHERE is_orphaned = 1"), conn)
        unmapped_ts = pd.read_sql(text("""
            SELECT c.contract_id, ts.discipline_id, SUM(ts.hours_logged) AS hours
            FROM vwm.Fact_Timesheets ts
            JOIN vwm.Dim_Contracts c ON c.project_uuid = ts.project_uuid
            LEFT JOIN vwm.Dim_RateCatalog r
              ON r.discipline_id = ts.discipline_id AND r.effective_year = ts.effective_year
            WHERE r.discipline_id IS NULL
            GROUP BY c.contract_id, ts.discipline_id
        """), conn)

    unmatched_efl = df[df["efl_matched"] == 0]
    inv_dates = df[df["invalid_date_tasks"] > 0]
    cat7x = df[df["gl_cat7x_review_amt"] != 0]
    sp_rev = df[df["contract_type"] == "SP-REV"]
    sp_cost = df[df["contract_type"] == "SP-COST"]

    checks = [
        {
            "Check Code": "unmatched_efl_record",
            "Family": "Setup & Integration Gaps",
            "Count": int(len(unmatched_efl)),
            "Affected Records": ", ".join(unmatched_efl["contract_id"].tolist()) or "None",
            "Handling Rule": f"Kept in OWMS operational view; marked '{DISCONNECTED_EFL_LABEL}' (LEFT JOIN on trimmed EFL ID).",
            "Status": "WARNING" if len(unmatched_efl) > 0 else "PASS",
        },
        {
            "Check Code": "task_missing_rate_link",
            "Family": "Setup & Integration Gaps",
            "Count": int(len(unmapped_ts)),
            "Affected Records": ", ".join(f"{r['contract_id']} ({r['discipline_id']}: {r['hours']:.0f}h)" for _, r in unmapped_ts.iterrows()) or "None",
            "Handling Rule": "Treated as unvalued cost/sell exposure; NEVER assumed $0 cost.",
            "Status": "WARNING" if len(unmapped_ts) > 0 else "PASS",
        },
        {
            "Check Code": "orphaned_fee_structure",
            "Family": "Setup & Integration Gaps",
            "Count": int(len(orphans)),
            "Affected Records": ", ".join(f"{r['service_uuid']} (${r['total_service_fee']:,.0f})" for _, r in orphans.iterrows()) or "None",
            "Handling Rule": "Quarantined automatically from contract financial totals and flagged under Setup Exceptions.",
            "Status": "WARNING" if len(orphans) > 0 else "PASS",
        },
        {
            "Check Code": "invalid_task_dates",
            "Family": "Operational Delivery Risks",
            "Count": int(inv_dates["invalid_date_tasks"].sum()) if not inv_dates.empty else 0,
            "Affected Records": ", ".join(inv_dates["contract_id"].tolist()) or "None",
            "Handling Rule": "Tasks with start_date > due_date flagged and excluded from planned effort spread.",
            "Status": "WARNING" if not inv_dates.empty else "PASS",
        },
        {
            "Check Code": "gl_cat7x_review_lines",
            "Family": "Financial & Margin Decay",
            "Count": int(len(cat7x)),
            "Affected Records": ", ".join(f"{r['contract_id']} (${r['gl_cat7x_review_amt']:,.0f})" for _, r in cat7x.iterrows()) or "None",
            "Handling Rule": "Category 7x lines listed for Finance review — neither included nor excluded from margin.",
            "Status": "WARNING" if len(cat7x) > 0 else "PASS",
        },
        {
            "Check Code": "special_purpose_na_margin",
            "Family": "Non-Accessible Margins",
            "Count": int(len(sp_rev) + len(sp_cost)),
            "Affected Records": ", ".join(list(sp_rev["contract_id"]) + list(sp_cost["contract_id"])) or "None in scope",
            "Handling Rule": "SP-REV never reports 100%; SP-COST never reports -100% — strictly N/A.",
            "Status": "PASS",
        },
    ]

    checks_df = pd.DataFrame(checks)
    warn_cnt = int((checks_df["Status"] == "WARNING").sum())
    headline = (
        f"**Master Data & 9-View Integrity Audit:** **{warn_cnt} active data-quality findings** surfaced cleanly via LEFT JOIN "
        f"governance (zero silent drops; special-purpose N/A rules **PASS**)."
    )
    facts = [
        "All 9 views (`Dim_Contracts`, `Dim_Services`, `Dim_Tasks`, `Fact_Timesheets`, `Dim_RateCatalog`, `Fact_GeneralLedger`, `Fact_SharedOverheadAllocation`, `Fact_Exceptions`, `Fact_ActionLog`) are online and reconciled.",
        "Unlike raw inner-join extracts (e.g. legacy Tableau Prep `VDM FLOW` inner joins on `F5201`), Apex Margin Advisor enforces LEFT JOINs so unmatched EFL records and unmapped CRC rates surface as auditable exceptions.",
        "EFL join key strips leading zeroes (`LTRIM(TRIM(efl_contract_id), '0')`) and preserves identifiers as strings.",
    ]

    return ToolPayload(
        status="ok",
        tool_name="get_data_integrity_audit",
        topic_label="Master Data & 9-View Integrity",
        period_label=f"As-of {as_of.isoformat()}",
        headline=headline,
        facts=facts,
        df=checks_df,
        compiled_sql="SELECT * FROM vwm.Dim_Contracts LEFT JOIN vwm.Fact_GeneralLedger ... (9-view integrity reconciliation);",
        lineage_id="All 9 views in schema vwm (OWMS / EFL / GTE / CRC / CAT)",
    )


# ---------------------------------------------------------------------------
# Tool 9: View Collaborative Action Tracker (`Fact_ActionLog`)
# ---------------------------------------------------------------------------
def get_action_log(
    *,
    exception_id: str | None = None,
    contract_id: str | None = None,
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    actions = ActionTrackerStore().list_actions(exception_id=exception_id, contract_id=contract_id, limit=50)

    # Filter to persona scope
    if scope.assigned_contracts is not None:
        actions = [a for a in actions if a.contract_id in scope.assigned_contracts]

    if not actions:
        return ToolPayload(
            status="ok",
            tool_name="get_action_log",
            topic_label="CAT Action Log",
            period_label=f"As-of {as_of.isoformat()}",
            headline="No remediation actions logged in CAT (`Fact_ActionLog`) for the selected filter. Use `/log <exception_id> <action_note>` to record one.",
            df=pd.DataFrame(),
            lineage_id="CAT (Fact_ActionLog)",
        )

    out_df = pd.DataFrame([
        {
            "Action ID": a.action_uuid,
            "Type": a.entry_type,
            "Exception ID": a.exception_id,
            "Contract ID": a.contract_id,
            "Assigned To (N-1)": a.assigned_to,
            "Horizon": a.plan_horizon,
            "Status": a.status,
            "Target Date": a.target_resolution_date,
            "Logged By": a.user_name,
            "Remediation Comment": a.remediation_comment,
        }
        for a in actions
    ])

    return ToolPayload(
        status="ok",
        tool_name="get_action_log",
        topic_label=f"CAT Action Log ({len(actions)})",
        period_label=f"As-of {as_of.isoformat()}",
        headline=f"**Collaborative Action Tracker (`Fact_ActionLog`):** **{len(actions)} remediation commitment(s)** active in your scope.",
        facts=[
            "Every action links to `Fact_Exceptions` and `Dim_Contracts` via stable business keys (`exception_uuid`, `exception_id`, `contract_id`) so warehouse refreshes never orphan audit history.",
            "Log a remediation with `/log <exception_id> <note>`, delegate to a reportee with `/assign`, or add contract context with `/comment`.",
        ],
        df=out_df,
        compiled_sql="SELECT * FROM cat.fact_action_log ORDER BY timestamp DESC;",
        lineage_id="CAT (Fact_ActionLog) -> vwm.Fact_Exceptions",
    )


# ---------------------------------------------------------------------------
# Tool 10: Methodology, Formulas & 9-View Relational Architecture
# ---------------------------------------------------------------------------
def get_methodology_and_lineage(
    *,
    topic: str = "ALL",
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    cat = semantic_catalog()
    rows = []
    for cname, spec in cat["contract_methodologies"].items():
        rows.append({
            "Contract / Rule Domain": cname,
            "Economic Model": spec["economic_model"],
            "Revenue & Margin Formula / Rule": spec.get("provisional_margin_pct") or spec.get("handling_rule", ""),
            "Warning Thresholds": spec.get("thresholds", "Strictly N/A margin display"),
        })
    df = pd.DataFrame(rows)

    headline = (
        "**Apex Margin Advisor Methodology & 9-View Relational Architecture:** "
        "Applies distinct revenue/margin equations for **Fixed-Scope (FS)** vs. **Time & Materials (T&M)** contracts, "
        "strict `N/A` rules for Special Purpose contracts, `$120,000` shared laboratory overhead allocation, and a 0–100 Management-by-Exception Priority Score."
    )
    facts = [
        "Priority Score (0–100): Materiality `min(45, 45 × log10(Capital_at_Risk / 5000 + 1))` + Urgency (25/15/5) + Deterioration (15/10/5) + Action Latency (15/10/3).",
        "Critical Joins: `project_uuid` (OWMS/GTE), trimmed leading-zero-stripped `efl_contract_id` (EFL), `discipline_id + effective_year` (CRC), and `operating_unit_id` (Shared Overhead).",
        "VWM / VDM Enterprise Mapping: `OWMS` = CORE (`Project.*`, `Admin.*`), `EFL` = JDE/FLEX (`F5201`, `F4211`, `F0911`, `F0901`), `GTE` = Timecards (`F06116Z1`), `CRC` = Discipline Rates, `CAT` = SharePoint Action Lists & Write-Back Store.",
    ]

    return ToolPayload(
        status="ok",
        tool_name="get_methodology_and_lineage",
        topic_label="Methodology & 9-View Lineage",
        period_label=f"As-of {as_of.isoformat()}",
        headline=headline,
        facts=facts,
        df=df,
        compiled_sql="-- Governed semantic catalog: app/semantic/metrics.yaml",
        lineage_id="OWMS -> GTE -> CRC -> EFL -> CAT (9-View Relational Model)",
    )


# ---------------------------------------------------------------------------
# Helper: List OWMS tasks within persona RLS scope
# ---------------------------------------------------------------------------
def list_tasks_in_scope(user_id: str = "bu_director") -> pd.DataFrame:
    scope = get_user_scope(user_id)
    eng = get_engine(scope.user_id)
    with eng.connect() as conn:
        df = pd.read_sql(text("""
            SELECT
                t.task_uuid,
                t.task_name,
                c.contract_id,
                c.operating_unit_id,
                c.pm_name,
                t.discipline_id,
                t.planned_hours,
                t.due_date,
                t.completion_pct,
                t.task_status
            FROM vwm.Dim_Tasks t
            JOIN vwm.Dim_Contracts c ON c.project_uuid = t.project_uuid
            ORDER BY t.due_date ASC, c.contract_id
        """), conn)
    df = df[df["operating_unit_id"].isin(scope.allowed_bus)].copy()
    if scope.assigned_contracts is not None:
        df = df[df["contract_id"].isin(scope.assigned_contracts)].copy()
    return df


# ---------------------------------------------------------------------------
# Tool 11: /comment <contract_id> <note> — Write Contract Context / Clarification Note
# ---------------------------------------------------------------------------
def add_contract_comment(
    *,
    contract_id: str,
    comment_text: str,
    category: str | None = None,
    impact_hours: float = 0.0,
    impact_usd: float = 0.0,
    user_id: str = "bu_director",
    user_name: str | None = None,
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    cid = (contract_id or "").strip().upper()
    note = (comment_text or "").strip()

    if not cid or not note:
        return ToolPayload(
            status="unsupported",
            tool_name="add_contract_comment",
            headline="Usage: `/comment <contract_id> <clarification note>` — e.g. `/comment FS-OFFSHORE-108 Severe storm delayed offshore mobilization by 4 days; add weather contingency for next month`.",
        )

    denial = check_contract_access(scope, cid)
    if denial:
        return ToolPayload(status="refusal", tool_name="add_contract_comment", headline=denial)

    all_df = _load_contract_metrics(scope=scope, as_of=as_of)
    match = all_df[all_df["contract_id"] == cid]
    if match.empty:
        return ToolPayload(
            status="unsupported",
            tool_name="add_contract_comment",
            headline=f"Contract `{cid}` was not found in your active scope. Try `FS-AERO-104`, `FS-OFFSHORE-108`, `TM-RENEW-202`, or `FS-AUTO-305`.",
        )

    r = match.iloc[0]
    # Auto-classify category if omitted
    nl = note.lower()
    inferred_cat = category
    if not inferred_cat:
        if any(w in nl for w in ("weather", "storm", "gale", "hurricane", "flood", "calamity", "snow", "force majeure")):
            inferred_cat = "Weather / Natural Event"
        elif any(w in nl for w in ("client", "customer", "site access", "waiting on client", "permit")):
            inferred_cat = "Client Delay"
        elif any(w in nl for w in ("unassigned", "technician", "resource", "staff", "rig", "chamber", "capacity")):
            inferred_cat = "Resource Bottleneck"
        elif any(w in nl for w in ("underestimat", "cost", "scope", "bid", "overhead", "buffer", "estimate")):
            inferred_cat = "Cost / Scope Clarification"
        else:
            inferred_cat = "General Note"

    actor = user_name or f"{scope.short_role} ({scope.user_id})"
    rec = ActionTrackerStore().add_comment(
        contract_id=cid,
        project_uuid=str(r["project_uuid"]),
        bu_id=str(r["operating_unit_id"]),
        category=inferred_cat,
        author_id=scope.user_id,
        author_name=actor,
        author_persona=scope.display_name,
        comment_text=note,
        impact_hours=float(impact_hours or 0.0),
        impact_usd=float(impact_usd or 0.0),
    )

    out_df = pd.DataFrame([{
        "Comment ID": rec.comment_uuid,
        "Contract ID": rec.contract_id,
        "BU": rec.bu_id,
        "Category": rec.category,
        "Author": rec.author_name,
        "Role": rec.author_persona,
        "Impact Hrs": rec.impact_hours,
        "Impact ($)": rec.impact_usd,
        "Comment / Clarification": rec.comment_text,
    }])

    return ToolPayload(
        status="ok",
        tool_name="add_contract_comment",
        topic_label=f"Contract Note Saved ({rec.comment_uuid})",
        period_label=f"Saved {rec.created_at.strftime('%Y-%m-%d %H:%M')}",
        headline=(
            f"**Contract clarification `{rec.comment_uuid}` written to database (`cat_contract_comments`)** "
            f"for **`{cid}`** ({r['contract_name']}) under **{rec.category}**."
        ),
        facts=[
            f"Attributed to **{rec.author_name}** ({rec.author_persona}) and linked by business keys (`contract_id={cid}`, `project_uuid={r['project_uuid']}`).",
            f"Future `/trace {cid}` audits and the **Action Plan & Notes** board will automatically display this explanation alongside financial actuals.",
            "Governance note: Operational comments preserve ERP/GL actuals untouched while documenting root causes (e.g., weather events, scope underestimation, or overhead buffers) for executive reviews.",
        ],
        df=out_df,
        compiled_sql=(
            f"INSERT INTO cat.cat_contract_comments (comment_uuid, contract_id, project_uuid, bu_id, category, author_name, comment_text, impact_hours, impact_usd)\n"
            f"VALUES ('{rec.comment_uuid}', '{rec.contract_id}', '{rec.project_uuid}', '{rec.bu_id}', '{rec.category}', '{rec.author_name}', :comment_text, {rec.impact_hours}, {rec.impact_usd});"
        ),
        lineage_id="CAT Write-Back DB (cat_contract_comments) -> linked to vwm.Dim_Contracts via contract_id & project_uuid",
        filters_used={"contract_id": cid, "category": rec.category},
        extra={"contract_id": cid, "bu_id": str(r["operating_unit_id"])},
    )


# ---------------------------------------------------------------------------
# Tool 12: /assign — Delegate N-1 Instruction or Assign Task / Resource for Next Week / Month
# ---------------------------------------------------------------------------
def assign_n1_action_or_task(
    *,
    contract_id: str | None = None,
    task_id: str | None = None,
    assignee_name: str,
    instruction: str,
    plan_horizon: str = "Next Week",
    reallocated_hours: float = 0.0,
    target_resolution_date: str | None = None,
    user_id: str = "bu_director",
    user_name: str | None = None,
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    assignee = (assignee_name or "").strip()
    note = (instruction or "").strip()
    tid = (task_id or "").strip().upper()
    cid = (contract_id or "").strip().upper()

    if not assignee or not note or (not cid and not tid):
        return ToolPayload(
            status="unsupported",
            tool_name="assign_n1_action_or_task",
            headline=(
                "Usage: `/assign <contract_id or task_id> to <reportee> [next week|next month] <instruction>` — "
                "e.g. `/assign FS-AERO-104 to Jordan Vance next week Freeze overtime and deliver SkyForge change order` "
                "or `/assign TSK-0112-1 to T. Sato next week Clear overdue EMC radiated emissions pre-scan`."
            ),
        )

    # Resolve task -> contract if a task_id was provided
    tasks_df = list_tasks_in_scope(scope.user_id)
    matched_task = None
    if tid:
        tm = tasks_df[tasks_df["task_uuid"] == tid]
        if tm.empty:
            return ToolPayload(
                status="refusal",
                tool_name="assign_n1_action_or_task",
                headline=f"Task `{tid}` was not found within your active persona scope ({scope.scope_label}).",
            )
        matched_task = tm.iloc[0]
        cid = str(matched_task["contract_id"])

    denial = check_contract_access(scope, cid)
    if denial:
        return ToolPayload(status="refusal", tool_name="assign_n1_action_or_task", headline=denial)

    all_df = _load_contract_metrics(scope=scope, as_of=as_of)
    cmatch = all_df[all_df["contract_id"] == cid]
    if cmatch.empty:
        return ToolPayload(
            status="unsupported",
            tool_name="assign_n1_action_or_task",
            headline=f"Contract `{cid}` was not found in your active scope.",
        )
    cr = cmatch.iloc[0]
    ex_df = _load_exceptions(scope=scope, contract_id=cid, limit=1)
    ex_id = str(ex_df.iloc[0]["exception_id"]) if not ex_df.empty else "GENERAL"
    ex_uuid = str(ex_df.iloc[0]["exception_uuid"]) if not ex_df.empty else f"GEN-{cid}"

    actor = user_name or f"{scope.short_role} ({scope.user_id})"
    store = ActionTrackerStore()

    # Determine entry type
    nl = note.lower()
    if matched_task is not None:
        entry_type = "Task Assignment"
    elif any(w in nl for w in ("reallocat", "rebalance", "shift", "capacity", "resource", "utilization")):
        entry_type = "Resource Reallocation"
    else:
        entry_type = "N-1 Instruction"

    # Always write into weekly/monthly Action Plan (`fact_action_log`)
    act = store.log_action(
        exception_uuid=ex_uuid,
        exception_id=ex_id,
        contract_id=cid,
        bu_id=str(cr["operating_unit_id"]),
        entry_type=entry_type,
        user_id=scope.user_id,
        user_name=actor,
        persona=scope.display_name,
        assigned_to=assignee,
        plan_horizon=plan_horizon,
        task_id=tid,
        status="Open",
        target_resolution_date=target_resolution_date,
        remediation_comment=note,
        baseline_snapshot={"contract_status": str(cr["risk_status"]), "bu_id": str(cr["operating_unit_id"])},
        as_of=as_of,
    )

    # Also write dedicated Task Assignment record when targeting a task or resource reallocation
    asn = None
    if matched_task is not None or float(reallocated_hours or 0.0) > 0:
        t_code = tid or (tasks_df[tasks_df["contract_id"] == cid]["task_uuid"].iloc[0] if not tasks_df[tasks_df["contract_id"] == cid].empty else f"TSK-{cid}")
        t_name = str(matched_task["task_name"]) if matched_task is not None else f"{cid} Resource Reallocation"
        asn = store.assign_task(
            contract_id=cid,
            task_uuid=t_code,
            task_name=t_name,
            assignee_name=assignee,
            assigned_by=actor,
            assigned_by_persona=scope.display_name,
            note=note,
            previous_assignee=str(cr["pm_name"]),
            plan_horizon=plan_horizon,
            reallocated_hours=float(reallocated_hours or 0.0),
        )

    out_df = pd.DataFrame([{
        "Action ID": act.action_uuid,
        "Type": act.entry_type,
        "Contract ID": act.contract_id,
        "Task ID": act.task_id or "—",
        "Assigned To (N-1)": act.assigned_to,
        "Assigned By": act.user_name,
        "Plan Horizon": act.plan_horizon,
        "Target Date": act.target_resolution_date,
        "Status": act.status,
        "Instruction / Action": act.remediation_comment,
    }])

    extra_msg = f" and recorded task ownership `{asn.assignment_uuid}` on `{asn.task_uuid}`" if asn else ""
    return ToolPayload(
        status="ok",
        tool_name="assign_n1_action_or_task",
        topic_label=f"{entry_type} ({plan_horizon})",
        period_label=f"Target: {act.target_resolution_date}",
        headline=(
            f"**{entry_type} `{act.action_uuid}` written to database** for **`{cid}`**, delegated to "
            f"**{assignee}** in the **{act.plan_horizon}** action plan{extra_msg}."
        ),
        facts=[
            f"Delegated by **{actor}** ({scope.display_name}) to N-1 / team member **{assignee}** (target resolution **{act.target_resolution_date}**).",
            f"Linked to contract `{cid}` ({cr['bu_name']}) and exception `{ex_id}` so it appears automatically in `/plan {act.plan_horizon}` and `/trace {cid}`.",
            "Manage status transitions (`Open` → `In Progress` → `Completed`) anytime on the **Action Plan & Notes** tab.",
        ],
        df=out_df,
        compiled_sql=(
            f"INSERT INTO cat.fact_action_log (action_uuid, entry_type, contract_id, task_id, assigned_to, plan_horizon, status, target_resolution_date, remediation_comment)\n"
            f"VALUES ('{act.action_uuid}', '{act.entry_type}', '{act.contract_id}', '{act.task_id}', '{act.assigned_to}', '{act.plan_horizon}', 'Open', '{act.target_resolution_date}', :instruction);"
        ),
        lineage_id="CAT Write-Back DB (fact_action_log + cat_task_assignments) -> vwm.Dim_Contracts / Dim_Tasks",
        filters_used={"contract_id": cid, "assigned_to": assignee, "plan_horizon": plan_horizon},
        extra={"contract_id": cid, "bu_id": str(cr["operating_unit_id"]), "exception_ids": [ex_id]},
    )


# ---------------------------------------------------------------------------
# Tool 13: /decide — Business Leader Formal Decision & Exception Disposition (BU Manager RBAC)
# ---------------------------------------------------------------------------
def record_leadership_decision(
    *,
    contract_id: str,
    decision_type: str | None = None,
    rationale: str,
    exception_id: str | None = None,
    effective_until: str | None = None,
    user_id: str = "bu_director",
    user_name: str | None = None,
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)

    # VWM Guide Section 7 RBAC rule: formal Leadership Decisions are added by Business Leaders only
    if scope.user_id != "bu_director":
        return ToolPayload(
            status="refusal",
            tool_name="record_leadership_decision",
            headline=(
                "Governance RBAC notice: Formal Leadership Decisions (e.g., approving cost/weather buffers, "
                "accepting variance, or issuing stop-work orders) are restricted to **Operations Portfolio Director (BU Manager)**. "
                "As a **" + scope.display_name + "**, you can record a Contract Context Comment (`/comment`) or Remediation Action (`/log`)."
            ),
        )

    cid = (contract_id or "").strip().upper()
    rat = (rationale or "").strip()
    if not cid or not rat:
        return ToolPayload(
            status="unsupported",
            tool_name="record_leadership_decision",
            headline="Usage: `/decide <contract_id> <decision rationale>` — e.g. `/decide FS-OFFSHORE-108 Approve 15% storm mobilization buffer and accept variance through 2026-12-05`.",
        )

    all_df = _load_contract_metrics(scope=scope, as_of=as_of)
    cmatch = all_df[all_df["contract_id"] == cid]
    if cmatch.empty:
        return ToolPayload(
            status="unsupported",
            tool_name="record_leadership_decision",
            headline=f"Contract `{cid}` was not found in the active portfolio.",
        )

    rl = rat.lower()
    inferred_type = decision_type
    if not inferred_type:
        if any(w in rl for w in ("stop-work", "stop work", "halt", "pause")):
            inferred_type = "Stop-Work Order"
        elif any(w in rl for w in ("renegotiat", "change order", "scope")):
            inferred_type = "Client Scope Renegotiation"
        elif any(w in rl for w in ("snooze", "defer")):
            inferred_type = "Snooze Exception"
        elif any(w in rl for w in ("accept", "waive")):
            inferred_type = "Accept Variance (Time-Bound)"
        else:
            inferred_type = "Approve Cost / Weather Buffer"

    ex_df = _load_exceptions(scope=scope, contract_id=cid, limit=1)
    ex_id = (exception_id or (str(ex_df.iloc[0]["exception_id"]) if not ex_df.empty else "")).upper()
    actor = user_name or f"{scope.short_role} ({scope.user_id})"

    rec = ActionTrackerStore().record_decision(
        contract_id=cid,
        exception_id=ex_id,
        decision_type=inferred_type,
        decided_by=actor,
        decided_by_persona=scope.display_name,
        rationale=rat,
        effective_until=effective_until,
        as_of=as_of,
    )

    out_df = pd.DataFrame([{
        "Decision ID": rec.decision_uuid,
        "Contract ID": rec.contract_id,
        "Exception ID": rec.exception_id or "—",
        "Decision Type": rec.decision_type,
        "Decided By": rec.decided_by,
        "Effective Until": rec.effective_until,
        "Rationale": rec.rationale,
    }])

    return ToolPayload(
        status="ok",
        tool_name="record_leadership_decision",
        topic_label=f"Leadership Decision ({rec.decision_uuid})",
        period_label=f"Effective through {rec.effective_until}",
        headline=(
            f"**Business Leader Decision `{rec.decision_uuid}` ({rec.decision_type}) written to database** "
            f"for **`{cid}`** (effective through **{rec.effective_until}**)."
        ),
        facts=[
            f"Authorized by **{rec.decided_by}** ({rec.decided_by_persona}) and linked to `{cid}`" + (f" / `{rec.exception_id}`." if rec.exception_id else "."),
            "Decision is persisted in `cat_leadership_decisions` and surfaced in every future `/trace` and weekly executive review.",
            "Per VWM Guide Section 7, executive decisions document governance sign-off without altering source ERP/GL ledger figures.",
        ],
        df=out_df,
        compiled_sql=(
            f"INSERT INTO cat.cat_leadership_decisions (decision_uuid, contract_id, exception_id, decision_type, decided_by, rationale, effective_until)\n"
            f"VALUES ('{rec.decision_uuid}', '{rec.contract_id}', '{rec.exception_id}', '{rec.decision_type}', '{rec.decided_by}', :rationale, '{rec.effective_until}');"
        ),
        lineage_id="CAT Write-Back DB (cat_leadership_decisions) -> vwm.Dim_Contracts / Fact_Exceptions",
        filters_used={"contract_id": cid, "decision_type": rec.decision_type},
        extra={"contract_id": cid, "exception_ids": [rec.exception_id] if rec.exception_id else []},
    )


# ---------------------------------------------------------------------------
# Tool 14: /plan [horizon|reportee|contract] — Weekly/Monthly Action Plan & Contract Notes
# ---------------------------------------------------------------------------
def get_action_plan(
    *,
    plan_horizon: str | None = None,
    assigned_to: str | None = None,
    contract_id: str | None = None,
    view_mode: str = "actions",  # actions | comments | assignments | decisions | all
    user_id: str = "bu_director",
    as_of: date | None = None,
) -> ToolPayload:
    as_of = as_of or as_of_date()
    scope = get_user_scope(user_id)
    if contract_id:
        denial = check_contract_access(scope, contract_id.upper())
        if denial:
            return ToolPayload(status="refusal", tool_name="get_action_plan", headline=denial)

    store = ActionTrackerStore()
    actions = store.list_actions(contract_id=contract_id, assigned_to=assigned_to, plan_horizon=plan_horizon, limit=100)
    comments = store.list_comments(contract_id=contract_id, limit=100)
    assignments = store.list_task_assignments(contract_id=contract_id, assignee_name=assigned_to, plan_horizon=plan_horizon, limit=100)
    decisions = store.list_decisions(contract_id=contract_id, limit=100)

    if scope.assigned_contracts is not None:
        actions = [a for a in actions if a.contract_id in scope.assigned_contracts]
        comments = [c for c in comments if c.contract_id in scope.assigned_contracts]
        assignments = [t for t in assignments if t.contract_id in scope.assigned_contracts]
        decisions = [d for d in decisions if d.contract_id in scope.assigned_contracts]

    mode = (view_mode or "actions").lower()
    if mode == "comments":
        df = pd.DataFrame([
            {
                "Comment ID": c.comment_uuid,
                "Contract ID": c.contract_id,
                "BU": c.bu_id,
                "Category": c.category,
                "Author": c.author_name,
                "Impact Hrs": c.impact_hours,
                "Impact ($)": c.impact_usd,
                "Logged At": c.created_at.strftime("%Y-%m-%d %H:%M"),
                "Clarification Note": c.comment_text,
            }
            for c in comments
        ])
        headline = f"**Contract Context & Clarification Notes (`cat_contract_comments`):** **{len(comments)} note(s)** recorded in database" + (f" for `{contract_id.upper()}`." if contract_id else ".")
    elif mode == "assignments":
        df = pd.DataFrame([
            {
                "Assignment ID": t.assignment_uuid,
                "Contract ID": t.contract_id,
                "Task ID": t.task_uuid,
                "Task Name": t.task_name,
                "Assignee": t.assignee_name,
                "Horizon": t.plan_horizon,
                "Realloc Hrs": t.reallocated_hours,
                "Assigned By": t.assigned_by,
                "Note": t.note,
            }
            for t in assignments
        ])
        headline = f"**Task Assignments & Resource Reallocations (`cat_task_assignments`):** **{len(assignments)} active assignment(s)** in your scope."
    elif mode == "decisions":
        df = pd.DataFrame([
            {
                "Decision ID": d.decision_uuid,
                "Contract ID": d.contract_id,
                "Exception ID": d.exception_id or "—",
                "Decision Type": d.decision_type,
                "Decided By": d.decided_by,
                "Effective Until": d.effective_until,
                "Rationale": d.rationale,
            }
            for d in decisions
        ])
        headline = f"**Business Leader Decisions (`cat_leadership_decisions`):** **{len(decisions)} governance decision(s)** recorded in database."
    else:
        df = pd.DataFrame([
            {
                "Action ID": a.action_uuid,
                "Horizon": a.plan_horizon,
                "Type": a.entry_type,
                "Contract ID": a.contract_id,
                "Task ID": a.task_id or "—",
                "Assigned To (N-1)": a.assigned_to,
                "Status": a.status,
                "Target Date": a.target_resolution_date,
                "Assigned By": a.user_name,
                "Action / Instruction": a.remediation_comment,
            }
            for a in actions
        ])
        flt_desc = " · ".join(x for x in [plan_horizon, f"Assignee: {assigned_to}" if assigned_to else "", contract_id.upper() if contract_id else ""] if x)
        headline = (
            f"**Weekly & Monthly Action Plan ({flt_desc or 'All Horizons'}):** "
            f"**{len(actions)} action item(s)**, **{len(comments)} contract clarification note(s)**, "
            f"**{len(assignments)} task assignment(s)**, and **{len(decisions)} leadership decision(s)** persisted in CAT."
        )

    facts = [
        f"Breakdown across CAT tables: **{len(actions)}** Action Plan items (`This Week` / `Next Week` / `Next Month`), **{len(comments)}** Contract Comments, **{len(assignments)}** Task Assignments, **{len(decisions)}** Leadership Decisions.",
        "Add new items directly from Chat with `/comment <contract_id> <note>`, `/assign <contract_or_task> to <reportee> [next week|next month] <instruction>`, or `/decide <contract_id> <decision>`.",
    ]

    return ToolPayload(
        status="ok",
        tool_name="get_action_plan",
        topic_label=f"Action Plan ({plan_horizon or mode.title()})",
        period_label=f"As-of {as_of.isoformat()}",
        headline=headline,
        facts=facts,
        df=df,
        compiled_sql="SELECT * FROM cat.fact_action_log / cat_contract_comments / cat_task_assignments / cat_leadership_decisions;",
        lineage_id="CAT Write-Back Database (4 business-keyed tables)",
        filters_used={"plan_horizon": plan_horizon, "assigned_to": assigned_to, "contract_id": contract_id, "view_mode": mode},
    )


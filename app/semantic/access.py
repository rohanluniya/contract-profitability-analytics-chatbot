"""Multi-persona security scope (RLS), operational focus, and tone adaptation."""
from __future__ import annotations

from dataclasses import dataclass

# PM Jordan Vance owns 6 active operational contracts across Aero, Renewables, Env, Offshore, Elec
PM_ASSIGNED_CONTRACTS: tuple[str, ...] = (
    "FS-AERO-104",
    "FS-RENEW-101",
    "FS-OFFSHORE-108",
    "TM-RENEW-202",
    "TM-ENV-401",
    "TM-ELEC-204",
)

ALL_BUSINESS_UNITS: tuple[str, ...] = (
    "BU-RENEW-01",
    "BU-AERO-02",
    "BU-ELEC-03",
    "BU-ENV-04",
    "BU-PHARM-05",
    "BU-OFFSHORE-06",
    "BU-AGRI-07",
    "BU-AUTO-08",
    "BU-INFRA-09",
    "BU-CONSUM-10",
)


@dataclass(frozen=True)
class UserScope:
    user_id: str
    persona_key: str
    display_name: str
    short_role: str
    scope_label: str
    tone: str
    allowed_bus: tuple[str, ...]
    assigned_contracts: tuple[str, ...] | None  # None means all contracts within allowed_bus
    can_view_gl_reconciliation: bool
    can_view_shared_overhead: bool
    can_view_special_purpose: bool
    action_orientation: str


SCOPES: dict[str, UserScope] = {
    "bu_director": UserScope(
        user_id="bu_director",
        persona_key="Operations Portfolio Director (BU Manager)",
        display_name="Operations Portfolio Director (BU Manager)",
        short_role="BU Manager",
        scope_label="All 10 Business Units · 20 Portfolio Contracts",
        tone="Executive, strategic, risk-weighted, variance-focused",
        allowed_bus=ALL_BUSINESS_UNITS,
        assigned_contracts=None,
        can_view_gl_reconciliation=True,
        can_view_shared_overhead=True,
        can_view_special_purpose=True,
        action_orientation="Strategic decisions: client scope renegotiation, stop-work orders, cross-BU resource balancing.",
    ),
    "pm_delivery": UserScope(
        user_id="pm_delivery",
        persona_key="Project Delivery Manager (PM)",
        display_name="Project Delivery Manager (PM)",
        short_role="PM",
        scope_label="Assigned Delivery Portfolio · 6 Active Field/Lab Contracts (PM: Jordan Vance)",
        tone="Practical, action-focused, field-oriented, milestone-driven",
        allowed_bus=("BU-AERO-02", "BU-RENEW-01", "BU-ENV-04", "BU-OFFSHORE-06", "BU-ELEC-03"),
        assigned_contracts=PM_ASSIGNED_CONTRACTS,
        can_view_gl_reconciliation=False,
        can_view_shared_overhead=False,
        can_view_special_purpose=False,
        action_orientation="Direct tactical interventions: approve timesheets, reallocate technicians, re-baseline task hours.",
    ),
    "commercial_admin": UserScope(
        user_id="commercial_admin",
        persona_key="Commercial Contract Administrator",
        display_name="Commercial Contract Administrator",
        short_role="Contract Admin",
        scope_label="Cross-BU Commercial Contracts & EFL Financial Ledger Reconciliation (All 20 Contracts)",
        tone="Rigorous, compliance-oriented, auditable, detail-driven",
        allowed_bus=ALL_BUSINESS_UNITS,
        assigned_contracts=None,
        can_view_gl_reconciliation=True,
        can_view_shared_overhead=True,
        can_view_special_purpose=True,
        action_orientation="Financial remediation: billing adjustments, GL journal reclassifications, master rate catalog fixes.",
    ),
}

ALIAS_TO_USER_ID: dict[str, str] = {
    "bu_director": "bu_director",
    "bu manager": "bu_director",
    "operations portfolio director (bu manager)": "bu_director",
    "operations portfolio director": "bu_director",
    "pm_delivery": "pm_delivery",
    "pm": "pm_delivery",
    "project delivery manager (pm)": "pm_delivery",
    "project delivery manager": "pm_delivery",
    "commercial_admin": "commercial_admin",
    "commercial contract administrator": "commercial_admin",
    "contract admin": "commercial_admin",
}


def get_user_scope(user_id: str | None) -> UserScope:
    key = ALIAS_TO_USER_ID.get((user_id or "bu_director").strip().lower(), "bu_director")
    return SCOPES[key]


def check_contract_access(scope: UserScope, contract_id: str) -> str | None:
    """Return a clean RLS denial message if the active persona cannot access the requested contract."""
    if scope.assigned_contracts is not None and contract_id not in scope.assigned_contracts:
        return (
            f"Access scope notice: `{contract_id}` is outside your assigned Project Delivery Manager scope "
            f"({', '.join(scope.assigned_contracts)}). Switch to **Operations Portfolio Director (BU Manager)** "
            f"or **Commercial Contract Administrator** in Settings to inspect cross-portfolio contracts."
        )
    return None


def check_bu_access(scope: UserScope, bu_id: str | None) -> str | None:
    if bu_id and bu_id not in scope.allowed_bus:
        return (
            f"Access scope notice: Business Unit `{bu_id}` is outside your active persona scope "
            f"({scope.scope_label})."
        )
    return None

"""Collaborative Action Tracker (CAT) persistent write-back database.

Follows VWM Data Analyst Guide Section 7: management records live outside the read-only
analytical warehouse and link strictly by stable business keys (`contract_id`, `project_uuid`,
`exception_id`, `exception_uuid`, `task_uuid`) so daily ERP/warehouse refreshes never orphan
human comments, N-1 instructions, task assignments, or leadership decisions.

Persisted tables in `data/cat_actions.sqlite`:
  1. `fact_action_log`         — Remediation actions & N-1 manager-to-reportee instructions (weekly/monthly plan)
  2. `cat_contract_comments`   — Contract/project context & clarification notes (weather, scope underestimation, etc.)
  3. `cat_task_assignments`    — Task ownership assignments & technician resource reallocations
  4. `cat_leadership_decisions`— Business Leader formal decisions & exception dispositions (BU Manager RBAC)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    MetaData,
    Table,
    Unicode,
    UnicodeText,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from app.config import ROOT, env

PLAN_HORIZONS = ("This Week", "Next Week", "Next Month")
ACTION_STATUSES = ("Open", "In Progress", "Completed")
COMMENT_CATEGORIES = (
    "Weather / Natural Event",
    "Cost / Scope Clarification",
    "Client Delay",
    "Resource Bottleneck",
    "General Note",
)
DECISION_TYPES = (
    "Approve Cost / Weather Buffer",
    "Client Scope Renegotiation",
    "Accept Variance (Time-Bound)",
    "Snooze Exception",
    "Stop-Work Order",
)

TEAM_DIRECTORY: list[dict[str, str]] = [
    {"name": "Jordan Vance", "role": "Project Delivery Manager (PM)", "bu": "BU-AERO-02 / BU-RENEW-01 / BU-ENV-04"},
    {"name": "Elena Rostova", "role": "Project Delivery Manager (PM)", "bu": "BU-AUTO-08 / BU-CONSUM-10"},
    {"name": "Marcus Thorne", "role": "Project Delivery Manager (PM)", "bu": "BU-INFRA-09 / BU-OFFSHORE-06"},
    {"name": "Priya Nair", "role": "Project Delivery Manager (PM)", "bu": "BU-PHARM-05 / BU-ELEC-03 / BU-AGRI-07"},
    {"name": "Claire Bennett", "role": "Commercial Contract Administrator", "bu": "Cross-BU Finance & CRC"},
    {"name": "Dr. A. Kovacs", "role": "Principal Metallurgist", "bu": "BU-AERO-02"},
    {"name": "L. Hansen", "role": "Lead NDT Inspector", "bu": "BU-OFFSHORE-06"},
    {"name": "T. Sato", "role": "EMC Compliance Engineer", "bu": "BU-CONSUM-10"},
    {"name": "E. Gallagher", "role": "Environmental Field Lead", "bu": "BU-ENV-04"},
    {"name": "J. Wu", "role": "Semiconductor Cleanroom Engineer", "bu": "BU-ELEC-03"},
]


@dataclass
class ActionRecord:
    action_uuid: str
    exception_uuid: str
    exception_id: str
    contract_id: str
    bu_id: str
    entry_type: str
    user_id: str
    user_name: str
    persona: str
    assigned_to: str
    plan_horizon: str
    task_id: str
    status: str
    timestamp: datetime
    target_resolution_date: str
    remediation_comment: str
    baseline_snapshot_json: str


@dataclass
class ContractComment:
    comment_uuid: str
    contract_id: str
    project_uuid: str
    bu_id: str
    category: str
    author_id: str
    author_name: str
    author_persona: str
    comment_text: str
    impact_hours: float
    impact_usd: float
    created_at: datetime


@dataclass
class TaskAssignment:
    assignment_uuid: str
    contract_id: str
    task_uuid: str
    task_name: str
    assignee_name: str
    previous_assignee: str
    plan_horizon: str
    reallocated_hours: float
    assigned_by: str
    assigned_by_persona: str
    note: str
    status: str
    created_at: datetime


@dataclass
class LeadershipDecision:
    decision_uuid: str
    contract_id: str
    exception_id: str
    decision_type: str
    decided_by: str
    decided_by_persona: str
    rationale: str
    effective_until: str
    created_at: datetime


def _tables() -> tuple[MetaData, Table, Table, Table, Table]:
    md = MetaData()
    actions = Table(
        "fact_action_log",
        md,
        Column("action_uuid", Unicode(40), primary_key=True),
        Column("exception_uuid", Unicode(64), nullable=False, index=True),
        Column("exception_id", Unicode(32), nullable=False, index=True),
        Column("contract_id", Unicode(32), nullable=False, index=True),
        Column("bu_id", Unicode(32), nullable=False, default=""),
        Column("entry_type", Unicode(48), nullable=False, default="Remediation Action"),
        Column("user_id", Unicode(80), nullable=False),
        Column("user_name", Unicode(120), nullable=False),
        Column("persona", Unicode(80), nullable=False),
        Column("assigned_to", Unicode(120), nullable=False, default="Unassigned"),
        Column("plan_horizon", Unicode(32), nullable=False, default="Next Week"),
        Column("task_id", Unicode(40), nullable=False, default=""),
        Column("status", Unicode(24), nullable=False, default="Open"),
        Column("timestamp", DateTime, nullable=False),
        Column("target_resolution_date", Unicode(16), nullable=False),
        Column("remediation_comment", UnicodeText, nullable=False),
        Column("baseline_snapshot_json", UnicodeText, nullable=False, default="{}"),
    )
    comments = Table(
        "cat_contract_comments",
        md,
        Column("comment_uuid", Unicode(40), primary_key=True),
        Column("contract_id", Unicode(32), nullable=False, index=True),
        Column("project_uuid", Unicode(40), nullable=False, default=""),
        Column("bu_id", Unicode(32), nullable=False, default=""),
        Column("category", Unicode(64), nullable=False, default="Cost / Scope Clarification"),
        Column("author_id", Unicode(80), nullable=False),
        Column("author_name", Unicode(120), nullable=False),
        Column("author_persona", Unicode(80), nullable=False),
        Column("comment_text", UnicodeText, nullable=False),
        Column("impact_hours", Float, nullable=False, default=0.0),
        Column("impact_usd", Float, nullable=False, default=0.0),
        Column("created_at", DateTime, nullable=False),
    )
    assignments = Table(
        "cat_task_assignments",
        md,
        Column("assignment_uuid", Unicode(40), primary_key=True),
        Column("contract_id", Unicode(32), nullable=False, index=True),
        Column("task_uuid", Unicode(40), nullable=False, index=True),
        Column("task_name", Unicode(160), nullable=False, default=""),
        Column("assignee_name", Unicode(120), nullable=False),
        Column("previous_assignee", Unicode(120), nullable=False, default="Unassigned"),
        Column("plan_horizon", Unicode(32), nullable=False, default="Next Week"),
        Column("reallocated_hours", Float, nullable=False, default=0.0),
        Column("assigned_by", Unicode(120), nullable=False),
        Column("assigned_by_persona", Unicode(80), nullable=False),
        Column("note", UnicodeText, nullable=False),
        Column("status", Unicode(24), nullable=False, default="Assigned"),
        Column("created_at", DateTime, nullable=False),
    )
    decisions = Table(
        "cat_leadership_decisions",
        md,
        Column("decision_uuid", Unicode(40), primary_key=True),
        Column("contract_id", Unicode(32), nullable=False, index=True),
        Column("exception_id", Unicode(32), nullable=False, default=""),
        Column("decision_type", Unicode(64), nullable=False),
        Column("decided_by", Unicode(120), nullable=False),
        Column("decided_by_persona", Unicode(80), nullable=False),
        Column("rationale", UnicodeText, nullable=False),
        Column("effective_until", Unicode(16), nullable=False),
        Column("created_at", DateTime, nullable=False),
    )
    return md, actions, comments, assignments, decisions


@lru_cache(maxsize=4)
def _sqlite_engine(path: str) -> Engine:
    return create_engine(f"sqlite:///{path}")


def clear_cat_cache() -> None:
    _sqlite_engine.cache_clear()


class ActionTrackerStore:
    def __init__(self, engine: Engine | None = None):
        if engine is None:
            path = ROOT / (env("CAT_ACTION_DB", "data/cat_actions.sqlite") or "data/cat_actions.sqlite")
            path.parent.mkdir(parents=True, exist_ok=True)
            engine = _sqlite_engine(str(path))
        self.engine = engine
        self.md, self.tbl, self.comments_tbl, self.assignments_tbl, self.decisions_tbl = _tables()
        self.md.create_all(engine)

    def reset_and_seed(
        self,
        seed_actions: list[dict],
        seed_comments: list[dict] | None = None,
        seed_assignments: list[dict] | None = None,
        seed_decisions: list[dict] | None = None,
    ) -> dict[str, int]:
        # Recreate schema cleanly on reset so new columns always exist
        self.md.drop_all(self.engine)
        self.md.create_all(self.engine)
        with self.engine.begin() as conn:
            if seed_actions:
                conn.execute(insert(self.tbl), seed_actions)
            if seed_comments:
                conn.execute(insert(self.comments_tbl), seed_comments)
            if seed_assignments:
                conn.execute(insert(self.assignments_tbl), seed_assignments)
            if seed_decisions:
                conn.execute(insert(self.decisions_tbl), seed_decisions)
        return {
            "actions": len(seed_actions or []),
            "comments": len(seed_comments or []),
            "assignments": len(seed_assignments or []),
            "decisions": len(seed_decisions or []),
        }

    # ------------------------------------------------------------------
    # 1. Remediation Actions & N-1 Action Plan Items
    # ------------------------------------------------------------------
    def log_action(
        self,
        *,
        exception_uuid: str,
        exception_id: str,
        contract_id: str,
        user_id: str,
        user_name: str,
        persona: str,
        remediation_comment: str,
        bu_id: str = "",
        entry_type: str = "Remediation Action",
        assigned_to: str = "Unassigned",
        plan_horizon: str = "Next Week",
        task_id: str = "",
        status: str = "Open",
        target_resolution_date: str | None = None,
        baseline_snapshot: dict | None = None,
        as_of: date | None = None,
    ) -> ActionRecord:
        now = datetime.now()
        base_d = as_of or date.today()
        default_days = 3 if plan_horizon == "This Week" else (14 if plan_horizon == "Next Month" else 7)
        tgt = target_resolution_date or (base_d + timedelta(days=default_days)).isoformat()
        rec = ActionRecord(
            action_uuid=f"ACT-{uuid.uuid4().hex[:8].upper()}",
            exception_uuid=exception_uuid,
            exception_id=(exception_id or "GENERAL").upper(),
            contract_id=contract_id.upper(),
            bu_id=bu_id,
            entry_type=entry_type,
            user_id=user_id,
            user_name=user_name,
            persona=persona,
            assigned_to=assigned_to or "Unassigned",
            plan_horizon=plan_horizon if plan_horizon in PLAN_HORIZONS else "Next Week",
            task_id=task_id.upper() if task_id else "",
            status=status if status in ACTION_STATUSES else "Open",
            timestamp=now,
            target_resolution_date=tgt,
            remediation_comment=remediation_comment.strip(),
            baseline_snapshot_json=json.dumps(baseline_snapshot or {}, default=str),
        )
        with self.engine.begin() as conn:
            conn.execute(insert(self.tbl).values(**rec.__dict__))
        return rec

    def update_action_status(self, action_uuid: str, new_status: str) -> bool:
        if new_status not in ACTION_STATUSES:
            return False
        with self.engine.begin() as conn:
            res = conn.execute(
                update(self.tbl).where(self.tbl.c.action_uuid == action_uuid).values(status=new_status)
            )
            return res.rowcount > 0

    def list_actions(
        self,
        *,
        exception_id: str | None = None,
        contract_id: str | None = None,
        assigned_to: str | None = None,
        plan_horizon: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ActionRecord]:
        t = self.tbl
        stmt = select(t).order_by(t.c.timestamp.desc()).limit(limit)
        if exception_id:
            stmt = stmt.where(t.c.exception_id == exception_id.upper())
        if contract_id:
            stmt = stmt.where(t.c.contract_id == contract_id.upper())
        if assigned_to and assigned_to.lower() not in ("all", "any"):
            stmt = stmt.where(t.c.assigned_to.ilike(f"%{assigned_to.strip()}%"))
        if plan_horizon and plan_horizon.lower() not in ("all", "any"):
            stmt = stmt.where(t.c.plan_horizon == plan_horizon)
        if status and status.lower() not in ("all", "any"):
            stmt = stmt.where(t.c.status == status)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [ActionRecord(**dict(r._mapping)) for r in rows]

    # ------------------------------------------------------------------
    # 2. Contract Context & Clarification Comments (Weather, Scope, etc.)
    # ------------------------------------------------------------------
    def add_comment(
        self,
        *,
        contract_id: str,
        project_uuid: str,
        bu_id: str,
        category: str,
        author_id: str,
        author_name: str,
        author_persona: str,
        comment_text: str,
        impact_hours: float = 0.0,
        impact_usd: float = 0.0,
    ) -> ContractComment:
        rec = ContractComment(
            comment_uuid=f"CMT-{uuid.uuid4().hex[:8].upper()}",
            contract_id=contract_id.upper(),
            project_uuid=project_uuid,
            bu_id=bu_id,
            category=category if category in COMMENT_CATEGORIES else "Cost / Scope Clarification",
            author_id=author_id,
            author_name=author_name,
            author_persona=author_persona,
            comment_text=comment_text.strip(),
            impact_hours=float(impact_hours or 0.0),
            impact_usd=float(impact_usd or 0.0),
            created_at=datetime.now(),
        )
        with self.engine.begin() as conn:
            conn.execute(insert(self.comments_tbl).values(**rec.__dict__))
        return rec

    def list_comments(
        self,
        *,
        contract_id: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[ContractComment]:
        t = self.comments_tbl
        stmt = select(t).order_by(t.c.created_at.desc()).limit(limit)
        if contract_id:
            stmt = stmt.where(t.c.contract_id == contract_id.upper())
        if category and category.lower() not in ("all", "any"):
            stmt = stmt.where(t.c.category == category)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [ContractComment(**dict(r._mapping)) for r in rows]

    # ------------------------------------------------------------------
    # 3. Task Assignments & Resource Reallocations
    # ------------------------------------------------------------------
    def assign_task(
        self,
        *,
        contract_id: str,
        task_uuid: str,
        task_name: str,
        assignee_name: str,
        assigned_by: str,
        assigned_by_persona: str,
        note: str,
        previous_assignee: str = "Unassigned",
        plan_horizon: str = "Next Week",
        reallocated_hours: float = 0.0,
    ) -> TaskAssignment:
        rec = TaskAssignment(
            assignment_uuid=f"ASN-{uuid.uuid4().hex[:8].upper()}",
            contract_id=contract_id.upper(),
            task_uuid=task_uuid.upper(),
            task_name=task_name,
            assignee_name=assignee_name.strip(),
            previous_assignee=previous_assignee,
            plan_horizon=plan_horizon if plan_horizon in PLAN_HORIZONS else "Next Week",
            reallocated_hours=float(reallocated_hours or 0.0),
            assigned_by=assigned_by,
            assigned_by_persona=assigned_by_persona,
            note=note.strip(),
            status="Assigned",
            created_at=datetime.now(),
        )
        with self.engine.begin() as conn:
            conn.execute(insert(self.assignments_tbl).values(**rec.__dict__))
        return rec

    def list_task_assignments(
        self,
        *,
        contract_id: str | None = None,
        assignee_name: str | None = None,
        plan_horizon: str | None = None,
        limit: int = 100,
    ) -> list[TaskAssignment]:
        t = self.assignments_tbl
        stmt = select(t).order_by(t.c.created_at.desc()).limit(limit)
        if contract_id:
            stmt = stmt.where(t.c.contract_id == contract_id.upper())
        if assignee_name and assignee_name.lower() not in ("all", "any"):
            stmt = stmt.where(t.c.assignee_name.ilike(f"%{assignee_name.strip()}%"))
        if plan_horizon and plan_horizon.lower() not in ("all", "any"):
            stmt = stmt.where(t.c.plan_horizon == plan_horizon)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [TaskAssignment(**dict(r._mapping)) for r in rows]

    # ------------------------------------------------------------------
    # 4. Business Leader Decisions & Exception Dispositions
    # ------------------------------------------------------------------
    def record_decision(
        self,
        *,
        contract_id: str,
        exception_id: str,
        decision_type: str,
        decided_by: str,
        decided_by_persona: str,
        rationale: str,
        effective_until: str | None = None,
        as_of: date | None = None,
    ) -> LeadershipDecision:
        base_d = as_of or date.today()
        eff = effective_until or (base_d + timedelta(days=30)).isoformat()
        rec = LeadershipDecision(
            decision_uuid=f"DEC-{uuid.uuid4().hex[:8].upper()}",
            contract_id=contract_id.upper(),
            exception_id=(exception_id or "").upper(),
            decision_type=decision_type if decision_type in DECISION_TYPES else "Approve Cost / Weather Buffer",
            decided_by=decided_by,
            decided_by_persona=decided_by_persona,
            rationale=rationale.strip(),
            effective_until=eff,
            created_at=datetime.now(),
        )
        with self.engine.begin() as conn:
            conn.execute(insert(self.decisions_tbl).values(**rec.__dict__))
        return rec

    def list_decisions(
        self,
        *,
        contract_id: str | None = None,
        limit: int = 100,
    ) -> list[LeadershipDecision]:
        t = self.decisions_tbl
        stmt = select(t).order_by(t.c.created_at.desc()).limit(limit)
        if contract_id:
            stmt = stmt.where(t.c.contract_id == contract_id.upper())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [LeadershipDecision(**dict(r._mapping)) for r in rows]

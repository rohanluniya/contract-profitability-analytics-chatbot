"""Action Plan & Write-Back Hub: Weekly/Monthly N-1 Directives, Contract Clarifications, Task Assignments & Decisions."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from app.cat.store import (
    ACTION_STATUSES,
    COMMENT_CATEGORIES,
    DECISION_TYPES,
    PLAN_HORIZONS,
    TEAM_DIRECTORY,
    ActionTrackerStore,
)
from app.semantic import service as Svc
from app.semantic.access import get_user_scope
from app.ui import common as C
from app.viz.tables import TABLE_CSS, render_html, to_csv_bytes


def render() -> None:
    cfg = st.session_state["cfg"]
    scope = get_user_scope(cfg["user_id"])
    store = ActionTrackerStore()

    st.markdown("### 🗓️ Action Plan, Contract Clarifications & Database Write-Back")
    st.info(
        "**Governed Write-Back Database (VWM Section 7 Architecture):** Comments, N-1 reportee instructions, "
        "task assignments, and leadership decisions write directly to the persistent CAT database linked by stable business keys "
        "(`contract_id`, `project_uuid`, `task_uuid`, `exception_id`). Historical ERP/GL actuals are never overwritten."
    )

    # Load scoped contracts & live CAT counts
    contracts_res = Svc.get_contract_profitability(user_id=cfg["user_id"], as_of=cfg["as_of"])
    contract_ids = contracts_res.df["Contract ID"].tolist() if not contracts_res.df.empty else []
    tasks_df = Svc.list_tasks_in_scope(cfg["user_id"])

    all_actions = store.list_actions(limit=200)
    all_comments = store.list_comments(limit=200)
    all_assignments = store.list_task_assignments(limit=200)
    all_decisions = store.list_decisions(limit=200)

    if scope.assigned_contracts is not None:
        all_actions = [a for a in all_actions if a.contract_id in scope.assigned_contracts]
        all_comments = [c for c in all_comments if c.contract_id in scope.assigned_contracts]
        all_assignments = [t for t in all_assignments if t.contract_id in scope.assigned_contracts]
        all_decisions = [d for d in all_decisions if d.contract_id in scope.assigned_contracts]

    open_cnt = sum(1 for a in all_actions if a.status != "Completed")
    next_wk = sum(1 for a in all_actions if a.plan_horizon == "Next Week" and a.status != "Completed")
    next_mo = sum(1 for a in all_actions if a.plan_horizon == "Next Month" and a.status != "Completed")

    cards = [
        ("Active Action Plan Items", f"{open_cnt}", f"{len(all_actions)} total logged", f"{next_wk} Next Week · {next_mo} Next Month", "blue"),
        ("Contract Clarifications", f"{len(all_comments)}", "cat_contract_comments", "Weather delays, scope & cost context notes", ""),
        ("Task & Resource Assignments", f"{len(all_assignments)}", "cat_task_assignments", "Owner handoffs & capacity reallocations", "warn"),
        ("Leadership Decisions", f"{len(all_decisions)}", "cat_leadership_decisions", "Buffers, scope changes & dispositions", ""),
    ]
    cols = st.columns(4)
    for idx, (title, val, period, sub, cls) in enumerate(cards):
        cols[idx].markdown(
            f"<div class='ax-kpi-card {cls}'>"
            f"<div class='k-title'>{C.esc(title)}</div>"
            f"<div class='k-val'>{C.esc(val)}</div>"
            f"<div class='k-period'>{C.esc(period)}</div>"
            f"<div class='k-sub'>{C.esc(sub)}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    st.write("")

    t_plan, t_notes, t_tasks, t_dec = st.tabs([
        "📅 Weekly / Monthly Action Plan (N-1)",
        "📝 Contract Comments & Clarifications",
        "🎯 Task Assignments & Resources",
        "🏛️ Business Leader Decisions",
    ])

    team_names = [t["name"] for t in TEAM_DIRECTORY]

    # ------------------------------------------------------------------
    # Tab 1: Weekly / Monthly Action Plan & N-1 Instructions
    # ------------------------------------------------------------------
    with t_plan:
        f1, f2, f3 = st.columns(3)
        h_pick = f1.selectbox("Plan Horizon", ["All Horizons", *PLAN_HORIZONS])
        a_pick = f2.selectbox("Assigned To (N-1 / Reportee)", ["All Reportees"] + sorted(set(team_names + [a.assigned_to for a in all_actions])))
        s_pick = f3.selectbox("Status", ["All Statuses", *ACTION_STATUSES])

        filtered = all_actions
        if h_pick != "All Horizons":
            filtered = [a for a in filtered if a.plan_horizon == h_pick]
        if a_pick != "All Reportees":
            filtered = [a for a in filtered if a.assigned_to == a_pick]
        if s_pick != "All Statuses":
            filtered = [a for a in filtered if a.status == s_pick]

        if filtered:
            plan_df = pd.DataFrame([
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
                    "Instruction / Action": a.remediation_comment,
                }
                for a in filtered
            ])
            st.markdown(TABLE_CSS + render_html(plan_df), unsafe_allow_html=True)
            st.download_button(
                "⬇️ Download Action Plan (CSV)",
                to_csv_bytes(plan_df),
                file_name="apex_action_plan.csv",
                mime="text/csv",
            )

            with st.expander("🔄 Update Action Item Status in Database", expanded=False):
                u1, u2, u3 = st.columns([2, 1, 1], vertical_alignment="bottom")
                act_map = {f"{a.action_uuid} — {a.contract_id} ({a.assigned_to}, {a.status})": a.action_uuid for a in filtered}
                sel_act = u1.selectbox("Select Action Item", list(act_map.keys()))
                new_st = u2.selectbox("New Status", list(ACTION_STATUSES), index=1)
                if u3.button("Save Status", type="primary", width="stretch"):
                    store.update_action_status(act_map[sel_act], new_st)
                    st.success(f"Updated `{act_map[sel_act]}` status to **{new_st}** in database.")
                    st.rerun()
        else:
            st.caption("No action items match the selected filters.")

        st.divider()
        st.markdown("#### ✍️ Delegate New N-1 Instruction / Weekly-Monthly Action Item")
        with st.form("new_n1_action_form", clear_on_submit=True):
            r1, r2, r3, r4 = st.columns([1.2, 1.3, 1, 1])
            cid_pick = r1.selectbox("Contract ID", contract_ids)
            rep_pick = r2.selectbox("Assign To (N-1 / Reportee)", team_names)
            hor_pick = r3.selectbox("Plan Horizon", list(PLAN_HORIZONS), index=1)
            due_pick = r4.date_input("Target Date", value=cfg["as_of"] + timedelta(days=7))
            instr = st.text_area(
                "Instruction / Deliverable for Reportee",
                placeholder="e.g. Freeze weekend overtime, prepare client weather-delay claim, and re-baseline remaining task hours before Monday review.",
                height=80,
            )
            ok = st.form_submit_button("Write N-1 Instruction to Database", type="primary")
        if ok:
            if not instr.strip():
                st.warning("Please enter an instruction before saving.")
            else:
                res = Svc.assign_n1_action_or_task(
                    contract_id=cid_pick,
                    assignee_name=rep_pick,
                    instruction=instr.strip(),
                    plan_horizon=hor_pick,
                    target_resolution_date=due_pick.isoformat(),
                    user_id=cfg["user_id"],
                    user_name=st.session_state.get("auth_name"),
                    as_of=cfg["as_of"],
                )
                if res.status == "ok":
                    st.success(res.headline)
                    st.rerun()
                else:
                    st.error(res.headline)

    # ------------------------------------------------------------------
    # Tab 2: Contract Context & Clarification Notes (Weather, Scope, Cost)
    # ------------------------------------------------------------------
    with t_notes:
        st.markdown("Capture real-world field & commercial context — such as **severe weather delays, natural events, underestimated bid hours, or client site holds** — directly on the contract record.")
        if all_comments:
            cdf = pd.DataFrame([
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
                for c in all_comments
            ])
            st.markdown(TABLE_CSS + render_html(cdf), unsafe_allow_html=True)
        else:
            st.caption("No contract clarification notes logged yet.")

        st.divider()
        st.markdown("#### ✍️ Write Contract Clarification / Field Context Comment")
        with st.form("new_comment_form", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns([1.2, 1.5, 0.9, 0.9])
            c_cid = c1.selectbox("Contract ID", contract_ids, key="cmt_cid")
            c_cat = c2.selectbox("Context Category", list(COMMENT_CATEGORIES))
            c_hrs = c3.number_input("Est. Impact Hrs", min_value=0.0, value=0.0, step=4.0)
            c_usd = c4.number_input("Est. Impact ($)", min_value=0.0, value=0.0, step=500.0)
            c_txt = st.text_area(
                "Contract Clarification / Root Cause Note",
                placeholder="e.g. Heavy storm delayed site mobilization by 4 days and added standby vessel cost; request overhead buffer in December forecast.",
                height=85,
            )
            c_ok = st.form_submit_button("Save Comment to Database", type="primary")
        if c_ok:
            if not c_txt.strip():
                st.warning("Please enter a comment before saving.")
            else:
                res = Svc.add_contract_comment(
                    contract_id=c_cid,
                    comment_text=c_txt.strip(),
                    category=c_cat,
                    impact_hours=float(c_hrs),
                    impact_usd=float(c_usd),
                    user_id=cfg["user_id"],
                    user_name=st.session_state.get("auth_name"),
                    as_of=cfg["as_of"],
                )
                if res.status == "ok":
                    st.success(res.headline)
                    st.rerun()
                else:
                    st.error(res.headline)

    # ------------------------------------------------------------------
    # Tab 3: Task Assignments & Resource Reallocation
    # ------------------------------------------------------------------
    with t_tasks:
        st.markdown("Assign open or unassigned OWMS tasks to technicians/PMs and log cross-project capacity reallocations.")
        if all_assignments:
            adf = pd.DataFrame([
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
                for t in all_assignments
            ])
            st.markdown(TABLE_CSS + render_html(adf), unsafe_allow_html=True)

        st.divider()
        st.markdown("#### ✍️ Assign Task / Reallocate Resource Hours")
        if not tasks_df.empty:
            task_opts = [
                f"{r['task_uuid']} — {r['contract_id']} · {r['task_name']} ({r['task_status']}, due {r['due_date']})"
                for _, r in tasks_df.iterrows()
            ]
            with st.form("new_task_assign_form", clear_on_submit=True):
                t1, t2, t3, t4 = st.columns([2.2, 1.2, 1, 0.9])
                sel_t = t1.selectbox("OWMS Task", task_opts)
                t_rep = t2.selectbox("Assign To Technician / PM", team_names, key="t_rep")
                t_hor = t3.selectbox("Horizon", list(PLAN_HORIZONS), index=1, key="t_hor")
                t_hrs = t4.number_input("Hours Allocated", min_value=0.0, value=24.0, step=4.0)
                t_note = st.text_area(
                    "Assignment / Resource Instruction",
                    placeholder="e.g. Task was open without an owner; assign chamber slot next week and shift 24 hrs from bench capacity.",
                    height=75,
                )
                t_ok = st.form_submit_button("Write Task Assignment to Database", type="primary")
            if t_ok:
                tid = sel_t.split("—")[0].strip()
                if not t_note.strip():
                    st.warning("Please enter an assignment note.")
                else:
                    res = Svc.assign_n1_action_or_task(
                        task_id=tid,
                        assignee_name=t_rep,
                        instruction=t_note.strip(),
                        plan_horizon=t_hor,
                        reallocated_hours=float(t_hrs),
                        user_id=cfg["user_id"],
                        user_name=st.session_state.get("auth_name"),
                        as_of=cfg["as_of"],
                    )
                    if res.status == "ok":
                        st.success(res.headline)
                        st.rerun()
                    else:
                        st.error(res.headline)

    # ------------------------------------------------------------------
    # Tab 4: Business Leader Decisions (BU Manager RBAC)
    # ------------------------------------------------------------------
    with t_dec:
        if all_decisions:
            ddf = pd.DataFrame([
                {
                    "Decision ID": d.decision_uuid,
                    "Contract ID": d.contract_id,
                    "Exception ID": d.exception_id or "—",
                    "Decision Type": d.decision_type,
                    "Decided By": d.decided_by,
                    "Effective Until": d.effective_until,
                    "Rationale": d.rationale,
                }
                for d in all_decisions
            ])
            st.markdown(TABLE_CSS + render_html(ddf), unsafe_allow_html=True)
        else:
            st.caption("No formal leadership decisions recorded yet.")

        st.divider()
        if scope.user_id != "bu_director":
            st.warning(
                "🔒 **Business Leader RBAC (VWM Guide Section 7):** Formal Leadership Decisions "
                "(approving cost/weather buffers, accepting variance, or issuing stop-work orders) can only be logged by "
                "**Operations Portfolio Director (BU Manager)**. Switch persona in Settings to record an executive decision."
            )
        else:
            st.markdown("#### ✍️ Record Official Business Leader Decision")
            with st.form("new_decision_form", clear_on_submit=True):
                d1, d2, d3 = st.columns([1.2, 1.6, 1])
                d_cid = d1.selectbox("Contract ID", contract_ids, key="dec_cid")
                d_type = d2.selectbox("Decision Type", list(DECISION_TYPES))
                d_eff = d3.date_input("Effective Until", value=cfg["as_of"] + timedelta(days=30))
                d_rat = st.text_area(
                    "Executive Rationale & Conditions",
                    placeholder="e.g. Approved 15% weather mobilization buffer through Dec 5 while PM negotiates shared standby recovery.",
                    height=80,
                )
                d_ok = st.form_submit_button("Record Leadership Decision", type="primary")
            if d_ok:
                if not d_rat.strip():
                    st.warning("Please enter the decision rationale.")
                else:
                    res = Svc.record_leadership_decision(
                        contract_id=d_cid,
                        decision_type=d_type,
                        rationale=d_rat.strip(),
                        effective_until=d_eff.isoformat(),
                        user_id=cfg["user_id"],
                        user_name=st.session_state.get("auth_name"),
                        as_of=cfg["as_of"],
                    )
                    if res.status == "ok":
                        st.success(res.headline)
                        st.rerun()
                    else:
                        st.error(res.headline)

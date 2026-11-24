# Appendix — Apex Margin Advisor Architecture, VWM Mapping & Verification Details

This appendix documents the 9-view relational design, injected benchmark scenarios, alignment with the enterprise `VWM Data Analyst Guide` and `VDM FLOW` artifacts, and production lift considerations.

---

## 1. 9-View Relational Data Architecture (`schema: vwm`)

All semantic queries execute exclusively against the nine governed views in `vwm` backed by five module schemas (`owms`, `efl`, `gte`, `crc`, `cat`):

1. `vwm.Dim_Contracts` — Contract master with normalized `efl_contract_key_norm = LTRIM(TRIM(efl_contract_id), '0')` and `efl_matched` LEFT JOIN indicator.
2. `vwm.Dim_Services` — Service fee lines (`milestone_fee`, `other_billable_fee`, `is_billable`, `is_orphaned` quarantine flag).
3. `vwm.Dim_Tasks` — Deliverable tasks with `planned_hours`, `completion_pct`, dates, and `invalid_dates_flag`.
4. `vwm.Fact_Timesheets` — Field and lab labor logs with `effective_year`, `is_billable_pay_type`, `approval_status`, `pending_business_days`, and `has_header`.
5. `vwm.Dim_RateCatalog` — Standardized discipline cost rates (`$52`–`$145/hr`) and billable sell rates (`$85`–`$275/hr`) keyed by `(discipline_id, effective_year)`.
6. `vwm.Fact_GeneralLedger` — Posted EFL general ledger entries (`gl_post_status = 'P'`) with credit sign reversal on revenue categories `1` and `2`, `7x` review items, and `8000`/`9000` overhead categories.
7. `vwm.Fact_SharedOverheadAllocation` — Monthly `$120,000` facility (`Cat-8000`: `$78,000`) and equipment depreciation (`Cat-9000`: `$42,000`) pool distributed across the 10 BUs (`SUM(bu_allocation_factor) = 1.0000`).
8. `vwm.Fact_Exceptions` — Weekly exception triage register across 4 families with Materiality (45), Urgency (25), Deterioration (15), and Action Latency (15) priority scores.
9. `vwm.Fact_ActionLog` — Remediation commitments joined by stable business keys (`exception_uuid`, `exception_id`, `contract_id`); live writes persist to `data/cat_actions.sqlite` (`app/cat/store.py`) so daily analytical warehouse refreshes never orphan manager commitments.

---

## 2. Verification of the 5 Injected Benchmark Scenarios

| Scenario | Contract / Object | Verified Rule & Measured Output |
|---|---|---|
| **1. Runaway Cost Alert** | `FS-AERO-104` (`BU-AERO-02`) | `420 hrs` logged vs. `250 hrs` planned (**168.0%** burn > 150%); automated revenue accrual blocked; provisional margin `-21.6%` (`-$12,300`); Priority Score **100.0/100** (`EXC-101`). |
| **2. Missing CRC Rate Card** | `TM-RENEW-202` (`BU-RENEW-01`) | `48.0 hrs` logged under unmapped `DISC-SPECIALIST-9` (`task_missing_rate_link`); treated strictly as unvalued cost/sell exposure (never `$0` cost); excluded from aggregate margin % (`EXC-105`). |
| **3. Unmatched EFL Record** | `FS-AUTO-305` (`BU-AUTO-08`) | Active OWMS contract (`$185,000`, `216 hrs` logged) with 0 rows in EFL for `0009305` (`unmatched_efl_record`); operational data preserved and marked `Disconnected from Financial Ledger` (`EXC-102`). |
| **4. T&M Under-Utilization** | `TM-ENV-401` (`BU-ENV-04`) | `128` approved billable hrs out of `200` logged capacity hrs (**64.0%** utilization < 80% threshold, `EXC-107`). |
| **5. Shared Lab Overhead** | All 10 BUs (`Cat-8000` / `9000`) | `$120,000` monthly pool apportioned across 10 BUs (`BU-AERO-02` highest at `15%` = `$18,000`) and deducted separately as **Indirect Laboratory Burden** before Net Operating Margin. |
| **Special Purpose N/A Rules** | `SP-REV-901`, `SP-COST-902` | `SP-REV-901` (`$45,000`, `$0` cost) displays `N/A (Commercial Revenue Adjustment Contract)` (never `100%`); `SP-COST-902` (`$0` rev, `$28,500` cost) displays `N/A (Internal Operational Holding Pool)` (never `-100%`). |
| **Orphaned Fee Quarantine** | `SVC-ORPHAN-999` (`$18,500`) | References decommissioned `project_uuid = 'PRJ-DECOMM-000'`; automatically excluded from contract value totals and surfaced under Setup Exceptions (`EXC-109`). |

---

## 3. Enterprise VWM / VDM Source Mapping & Join Hygiene

The synthetic platform modules align directly with the enterprise `VWM Data Analyst Guide` and unpacked Tableau Prep `VDM FLOW`:

| Synthetic Module | Enterprise VWM / VDM Source Objects | Key Engineering Note |
|---|---|---|
| **OWMS** | CORE `Project.Project`, `ProjectService`, `ProjectPhase`, `ProjectTask`, `ProjectServiceInvoiceMilestone`, `ProjectBillable`, `Admin.*` | Contract type `FS` (`billing_method_id IN (1, 5)`) vs. `T&M`; project status `Active` (`3`) or `Complete` (`6`). |
| **EFL** | JD Edwards / FLEX `proddta.F5201` (`G4DOCO`), `F4211` (`SDDOCO`), `F0911` + `F0901` (`GLAID = GMAID`, `GLLT IN ('AA','GP','UE')`, `GLPOST = 'P'`) | Legacy Tableau Prep `VDM FLOW` uses **INNER joins** on `F5201` and `F4211`, which drop unmatched contracts; Apex Margin Advisor strictly enforces **LEFT JOIN** with trimmed leading-zero-stripped keys so `unmatched_efl_record` surfaces cleanly. |
| **GTE** | CORE `TimecardRow` / `Timecard` headers & FLEX `proddta.F06116Z1` / `F069116` (`YCPDBA`, `YCPR03`, `YCPR08`) | Approved time drives cost/revenue; unapproved time > 7 business days surfaces by employee/week for billing lag triage. |
| **CRC** | CORE `Admin.Discipline`, `Admin.DivisionDiscipline`, `Project.ProjectDiscipline` | Joined on `(discipline_id, effective_year)`; missing rates never default to `$0`. |
| **CAT** | SharePoint Lists (`VWM Actions`, `VWM Comments`, `VWM Decisions`, `VWM Exception States`, `VWM Commitments`) | Stored outside the read-only warehouse and linked solely by business keys so refreshes never orphan commitments. |

---

## 4. Multi-Persona Row-Level Security (RLS) Matrix

- **`Operations Portfolio Director (BU Manager)` (`bu_director`):** Full access to all 10 BUs, 20 contracts, `$120,000` shared lab overhead allocation, special-purpose bridges, and GL reconciliation.
- **`Project Delivery Manager (PM)` (`pm_delivery`):** Scoped strictly to 6 assigned delivery contracts (`FS-AERO-104`, `FS-RENEW-101`, `FS-OFFSHORE-108`, `TM-RENEW-202`, `TM-ENV-401`, `TM-ELEC-204`). Cross-portfolio contracts (e.g., `FS-AUTO-305`) and BU-level overhead P&L return fail-closed access notices.
- **`Commercial Contract Administrator` (`commercial_admin`):** Cross-BU access to all 20 contracts with emphasis on unbilled WIP, Milestone-to-GL revenue variance (`FS-INFRA-111`), `unmatched_efl_record` (`FS-AUTO-305`), unmapped CRC rates (`TM-RENEW-202`), orphaned fee lines (`SVC-ORPHAN-999`), and `SP-REV-901`/`SP-COST-902` reconciliation.

---

## 5. Caveats & Optional LLM Model Licenses

- Only deterministic `rules` mode was executed in the local evaluation recorded in `results/eval/eval_report.md`; cloud/local LLM backends via LiteLLM (`ollama/qwen2.5-coder:14b`, `ollama/gpt-oss:20b`, `gemini/gemini-2.5-flash`, `openai/gpt-4o-mini`) are wired in `app/agent/llm.py` with automatic fallback to verified deterministic prose if offline or if a numeric/anomaly guardrail triggers.
- Optional local Ollama models listed in `.env.example` carry **Apache-2.0** licenses (`qwen2.5-coder:14b`; `gpt-oss:20b` subject to OpenAI's usage policy). Commercial cloud APIs (`gemini/*`, `openai/*`) require user-supplied API keys and compliance with vendor terms.
- Enterprise production lift requires connecting read-only warehouse replicas (CORE/FLEX/JDE), binding corporate SSO (Microsoft Entra ID) to SQL Server `SESSION_CONTEXT`, verifying effective-dated discipline rate history, and confirming Finance treatment of Category `7x` suspense lines and non-USD postings.

# Apex Margin Advisor — Executive Presentation & Video Kit

This folder contains the 12-slide executive presentation decks, 5 modular 1080p H.264 (`yuv420p`) live demo chapters, the concatenated master walkthrough video, and 21 companion 1080p screenshots captured directly from **Apex Margin Advisor** (`http://localhost:8503`).

## Slide Decks

| Artifact | Format | Purpose |
|---|---|---|
| `Apex_Margin_Advisor_Executive_Presentation.pptx` | Native 16:9 PowerPoint | 12-slide executive presentation with 9-view & CAT architecture visuals, 3-persona RBAC comparison, embedded 1080p MP4 demo chapters, poster frames, companion screenshots, and speaker notes. |
| `Apex_Margin_Advisor_Executive_Deck.html` | Standalone HTML5 Deck | Interactive browser presentation (`ArrowLeft` / `ArrowRight`) embedding all 5 live 1080p MP4 demo chapters directly in Slides 5–9. |

## Video Chapters (`videos/`)

| File | Persona & Scope Demonstrated |
|---|---|
| `00_apex_margin_master_walkthrough.mp4` | Complete end-to-end executive walkthrough concatenating Chapters 1–5 in 1080p H.264. |
| `01_bu_manager_summary_and_triage.mp4` | **BU Manager Use Case:** Sign-in, executive KPI strip, `/summary` BU rollup, `/exceptions` priority-scored queue (`EXC-101` `FS-AERO-104` at `100.0/100`), and 5-point `/trace FS-AERO-104` + SQL lineage drawer. |
| `02_pm_persona_rls_and_weather_comment.mp4` | **Project Manager Use Case + Write-Back:** Switching to `Project Delivery Manager (PM)` (scoped to 6 contracts), RLS refusal on out-of-scope `FS-AUTO-305`, writing a severe winter storm delay & standby cost comment on `FS-OFFSHORE-108` (`/comment`), and verifying it surfaces immediately inside `/trace FS-OFFSHORE-108`. |
| `03_writeback_n1_action_plan_and_decisions.mp4` | **Closed-Loop Write-Back Use Case:** BU Manager delegates an N-1 instruction to PM Jordan Vance for `Next Week` (`/assign`), assigns overdue task `TSK-0112-1` to `T. Sato`, records an official Business Leader weather-buffer decision (`/decide`), runs `/plan next week`, and explores the 4-tab **Action Plan & Notes** workspace. |
| `04_commercial_anomalies_and_overhead.mp4` | **Commercial Contract Admin Use Case:** Unmapped CRC rate exposure (`TM-RENEW-202`, `48 hrs` `DISC-SPECIALIST-9`), unmatched EFL ledger link (`FS-AUTO-305`), Special Purpose `N/A` margin protection (`SP-REV-901`, `SP-COST-902`), and the `$120,000` Shared Laboratory Overhead (`Cat-8000`/`Cat-9000`) waterfall across 10 BUs. |
| `05_data_catalog_integrity_and_guardrails.mp4` | **Governance & Catalog:** Navigating **Exception Triage**, **Data Catalog** (9-view schema & VWM/VDM mapping, live Master Data Integrity Audit with quarantined orphan fee `SVC-ORPHAN-999`), and fail-closed prompt-injection defense. |

## Reproducing the Kit

```bash
# 1. Ensure Apex Margin Advisor is running on http://localhost:8503
# 2. Record all 5 1080p MP4 chapters, master walkthrough, and 21 screenshots
APP_ACCESS_CODE=apex-demo-2026 uv run python scripts/record_presentation_kit.py http://localhost:8503 presentation_kit

# 3. Build both the 12-slide .pptx and interactive .html executive decks
uv run python scripts/build_executive_deck.py
```

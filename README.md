# Apex Margin Advisor

**Apex Margin Advisor** is a conversational **TIC Portfolio Margin & Exception Intelligence Assistant** modeled on the same governed architecture as `rl-finbot` (IRIS) and `core-pulse`, with full database write-back for contract clarifications, N-1 instructions, task assignments, and leadership decisions. Across **19 automated `pytest` and headless Streamlit UI checks** and a **24-question Golden Evaluation** (`results/eval/eval_report.md`), deterministic `rules` mode achieves **24/24** status, MCP tool, grounded fact, and guardrail accuracy (**0.018 s** median latency) over a 9-view synthetic TIC warehouse (`10` Business Units, `20` contracts, `9` priority-scored exceptions) and a 4-table persistent CAT write-back database.

> **Synthetic data — prototype for demonstration only.** All organizations, contracts, people, and financial figures are fictional.

---

## Model, Framework & Hardware

| Component | Implementation |
|---|---|
| **App & UI Stack** | Streamlit (`app/ui/streamlit_app.py`, port `8503`), 7 pages including **Action Plan & Notes**, inline chat write-back drawer, Plotly interactive charts, persistent last-10 conversation history, demo sign-in, multi-persona RLS, and CSV/Excel exports |
| **9-View Relational Warehouse** | DuckDB (`data/apex_margin.duckdb`, default local zero-dependency) via SQLAlchemy 2 Core (`app/db.py`), with SQL Server 2022 (`SESSION_CONTEXT` RLS) support; exposes all 9 `vwm.*` views across `OWMS`, `EFL`, `GTE`, `CRC`, and `CAT` |
| **MCP Semantic & CAT Write-Back Layer** | Standalone JSON-RPC 2.0 MCP server (`mcp_server/server.py`) exposing **14 typed tools** and **5 metadata resources**; governed write-back persists remediation actions, N-1 weekly/monthly directives, contract clarifications, task assignments, and BU leadership decisions to `data/cat_actions.sqlite` via business keys |
| **Routing & LLM Layer** | Deterministic `rules` mode (no external model required, measured below) plus optional LiteLLM integration (`app/agent/llm.py`) supporting Ollama (`ollama/qwen2.5-coder:14b`, Apache-2.0; `ollama/gpt-oss:20b`, Apache-2.0 with OpenAI usage policy), Gemini (`gemini/gemini-2.5-flash`), or OpenAI (`openai/gpt-4o-mini`) with numeric and anomaly guardrails |
| **Measured Hardware** | Local Apple Silicon macOS laptop (`CPython 3.12.8`, CPU only, zero external network calls in `rules` mode) |

---

## Main Results

### 1. Golden Evaluation (`results/eval/eval_report.md`)

Evaluated across all 3 personas (`Operations Portfolio Director (BU Manager)`, `Project Delivery Manager (PM)`, `Commercial Contract Administrator`), all 8 slash commands (`/summary`, `/exceptions`, `/trace`, `/log`, `/comment`, `/assign`, `/decide`, `/plan`), all 5 injected TIC anomaly scenarios, RLS & RBAC denials, and prompt-injection/out-of-scope guardrails:

| Mode | Questions | Status Match | MCP Tool Match | Grounded Fact Match | Guardrail Pass | Median Latency (s) | P95 Latency (s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `rules` (no LLM) | 24 | **24/24** | **24/24** | **24/24** | **24/24** | **0.018** | 0.038 |

- **Automated Test Suite (`pytest`):** **19/19 passed** (`4.09 s`), covering the 9-view warehouse, priority-scoring math, all 5 injected anomalies, special-purpose `N/A` margin rules, all 4 CAT write-back tables, BU-only leadership decision RBAC, JSON-RPC 2.0 MCP calls, and headless Streamlit `AppTest` checks across all 7 pages (`Chat`, `Exception Triage`, `Action Plan & Notes`, `Portfolio & Overhead`, `Data Catalog`, `User Guide`, `About`).

### 2. Measured Synthetic Benchmark Portfolio (`AS_OF_DATE = 2026-11-20`)

| Portfolio Metric | Measured Value | Scope / Integrity Note |
|---|---:|---|
| **Contracts / Business Units** | **20 / 10** | `12 FS`, `6 T&M`, `1 SP-REV-901`, `1 SP-COST-902` across `BU-RENEW-01` .. `BU-CONSUM-10` |
| **MTD Commercial Recognized vs. Target Revenue** | **$1,297,980** vs. $1,606,100 | Gap of **-$308,120** across `FS` and `T&M` contracts |
| **Commercial Provisional Margin %** | **59.9%** | `Σ margin ÷ Σ revenue` over complete-rate EFL-linked contracts (excludes `SP-REV`/`SP-COST`) |
| **Indirect Laboratory Burden (`Cat-8000` / `9000`)** | **$120,000** | Apportioned across all 10 BUs (`$78,000` Fixed Facility + `$42,000` Equipment Depreciation) |
| **Portfolio Net Operating Margin** | **$700,743 (52.2%)** | Includes `SP-REV-901` (+$45,000), `SP-COST-902` (-$28,500), and Indirect Lab Burden (-$120,000) |
| **Active Priority-Scored Exceptions** | **9** | Led by `EXC-101` on `FS-AERO-104` (**100.0/100**, 168.0% burn, accrual blocked) |
| **Unapproved WIP / Unmapped CRC Exposure** | **36 h ($7,020)** / **48 h** | `TM-ELEC-204` (>7 business day lag) and `TM-RENEW-202` (`DISC-SPECIALIST-9`, unvalued) |

---

## How to Reproduce

```bash
# 1. Install dependencies in an isolated uv environment (Python 3.12)
cp .env.example .env
uv sync --python 3.12

# 2. Seed the 9-view DuckDB warehouse and baseline CAT write-back tables
uv run python scripts/reset_demo_data.py

# 3. Run all 19 automated backend, write-back, MCP, and headless Streamlit UI tests
DB_BACKEND=duckdb uv run pytest -v

# 4. Run the 24-question Golden Evaluation
DB_BACKEND=duckdb uv run python scripts/run_evaluation.py --models "rules"

# 5. Launch Apex Margin Advisor on http://localhost:8503 (demo sign-in code: apex-demo-2026)
DB_BACKEND=duckdb uv run streamlit run app/ui/streamlit_app.py --server.port 8503

# 6. Optional: Run the JSON-RPC 2.0 MCP server over stdio
DB_BACKEND=duckdb uv run python -m mcp_server.server
```

### Supported Interactive Slash Commands

- `/summary` (or `/summary BU-AERO-02`) — Persona-adaptive executive KPI card and BU rollup
- `/exceptions [category]` (e.g., `/exceptions Setup`, `/exceptions Financial`, `/exceptions all`) — Priority-scored exception queue
- `/trace <contract_id>` (e.g., `/trace FS-AERO-104`, `/trace FS-OFFSHORE-108`) — 5-point OWMS / GTE / CRC / EFL audit trace + live CAT comments & directives
- `/comment <contract_id> <note>` — Write contract context/clarification notes (weather delays, natural events, underestimated costs, client holds) to `cat_contract_comments`
- `/assign <contract_or_task> to <reportee> [this week|next week|next month] <instruction>` — Delegate N-1 instructions, assign unassigned tasks (`TSK-...`), or reallocate resource hours
- `/decide <contract_id> <rationale>` — Record official Business Leader decisions (weather/cost buffers, variance acceptance, stop-work orders; BU Manager RBAC)
- `/log <exception_id> <action_note>` — Record a remediation commitment on an exception in `Fact_ActionLog`
- `/plan [this week|next week|next month|reportee|comments|assignments|decisions]` — View the weekly/monthly Action Plan and written-back records

---

## Further Details

- **[`APPENDIX.md`](APPENDIX.md):** Full 9-view schema, Priority Score rubric, verification of all 5 injected benchmark scenarios, enterprise `VWM / VDM FLOW` (`CORE` / `FLEX` / `JD Edwards`) mapping notes, and production lift caveats.
- **[`presentation_kit/`](presentation_kit/README.md):** Executive 12-slide PowerPoint ([`Apex_Margin_Advisor_Executive_Presentation.pptx`](presentation_kit/Apex_Margin_Advisor_Executive_Presentation.pptx)) and interactive HTML5 deck ([`Apex_Margin_Advisor_Executive_Deck.html`](presentation_kit/Apex_Margin_Advisor_Executive_Deck.html)) with 5 embedded 1080p H.264 MP4 persona & write-back demo chapters, a master walkthrough video, and 21 companion screenshots.
- **[`results/eval/`](results/eval/):** Raw Golden Evaluation outputs ([`eval_report.md`](results/eval/eval_report.md), [`evaluation_summary.json`](results/eval/evaluation_summary.json)).

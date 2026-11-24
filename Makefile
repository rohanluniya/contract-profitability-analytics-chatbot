.PHONY: setup seed test eval run mcp

setup:
	uv sync --python 3.12

seed:
	uv run python scripts/reset_demo_data.py

test:
	DB_BACKEND=duckdb uv run pytest -v

eval:
	DB_BACKEND=duckdb uv run python scripts/run_evaluation.py --models "rules"

run:
	DB_BACKEND=duckdb uv run streamlit run app/ui/streamlit_app.py --server.port 8503

mcp:
	DB_BACKEND=duckdb uv run python -m mcp_server.server

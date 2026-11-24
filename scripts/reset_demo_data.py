"""Reset and rebuild the deterministic Apex Margin Advisor 9-view warehouse and CAT seed data.

Usage:
    uv run python scripts/reset_demo_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.cat.store import clear_cat_cache  # noqa: E402
from app.config import backend, data_as_of_date  # noqa: E402
from app.db import clear_engine_cache, duckdb_path, get_engine  # noqa: E402
from pipelines.warehouse import build_warehouse  # noqa: E402


def reset_all() -> dict:
    if backend() == "duckdb":
        p = duckdb_path()
        if p.exists():
            p.unlink()
    clear_engine_cache()
    clear_cat_cache()
    eng = get_engine(admin=True)
    summary = build_warehouse(eng, as_of=data_as_of_date(), reset_cat=True)
    summary["backend"] = backend()
    clear_engine_cache()
    return summary


if __name__ == "__main__":
    res = reset_all()
    print("RESET_APEX_WAREHOUSE_COMPLETE", json.dumps(res, indent=2), flush=True)

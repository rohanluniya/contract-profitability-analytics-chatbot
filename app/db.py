"""Database access for Apex Margin Advisor (DuckDB default + SQL Server 2022 option) via SQLAlchemy 2 Core."""
from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine

from app.config import ROOT, backend, env

QUERY_TIMEOUT_SECONDS = 30
SCHEMAS = ("owms", "efl", "gte", "crc", "cat", "vwm")
_ACTIVE_ENGINES: list[Engine] = []


def mssql_url(admin: bool = False, database: str | None = None) -> URL:
    app_u = env("APEX_MSSQL_APP_USER") or env("MSSQL_APP_USER", "apex_reader")
    db_n = database if database is not None else (env("APEX_DB_NAME") or env("DB_NAME", "apex_margin"))
    user = env("MSSQL_SA_USER", "sa") if admin else app_u
    password = env("MSSQL_SA_PASSWORD") if admin else env("MSSQL_APP_PASSWORD")
    query = {
        "driver": env("ODBC_DRIVER", "ODBC Driver 18 for SQL Server"),
        "Encrypt": "yes",
        "TrustServerCertificate": env("MSSQL_TRUST_SERVER_CERT", "yes"),
    }
    return URL.create(
        "mssql+pyodbc",
        username=user,
        password=password,
        host=env("DB_HOST", "localhost"),
        port=int(env("DB_PORT", "1433")),
        database=db_n,
        query=query,
    )


def duckdb_path() -> Path:
    raw = env("APEX_DUCKDB_PATH") or env("DUCKDB_PATH", "data/apex_margin.duckdb") or "data/apex_margin.duckdb"
    p = ROOT / raw
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def clear_engine_cache() -> None:
    while _ACTIVE_ENGINES:
        eng = _ACTIVE_ENGINES.pop()
        try:
            eng.dispose()
        except Exception:  # noqa: BLE001
            pass
    get_engine.cache_clear()


@lru_cache(maxsize=32)
def get_engine(user_id: str | None = None, admin: bool = False) -> Engine:
    """Engine per (user_id, admin). App queries open DuckDB read-only; warehouse builds use admin=True."""
    if backend() == "duckdb":
        path = duckdb_path()
        eng = create_engine(
            f"duckdb:///{path}",
            connect_args={"read_only": (not admin) and path.exists()},
        )
        _ACTIVE_ENGINES.append(eng)
        return eng

    engine = create_engine(
        mssql_url(admin=admin),
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=4,
        fast_executemany=True,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover
        dbapi_conn.timeout = QUERY_TIMEOUT_SECONDS
        if user_id and not admin and user_id != "__history__":
            cur = dbapi_conn.cursor()
            cur.execute(
                "EXEC sp_set_session_context @key=N'user_id', @value=?, @read_only=1;",
                user_id,
            )
            cur.close()

    _ACTIVE_ENGINES.append(engine)
    return engine


def run_with_timeout(conn, fn, seconds: int = QUERY_TIMEOUT_SECONDS):
    if backend() != "duckdb":
        raw = conn.connection.dbapi_connection
        prev = getattr(raw, "timeout", 0)
        raw.timeout = seconds
        try:
            return fn()
        finally:
            raw.timeout = prev
    raw = conn.connection.dbapi_connection
    timer = threading.Timer(seconds, lambda: raw.interrupt())
    timer.start()
    try:
        return fn()
    finally:
        timer.cancel()

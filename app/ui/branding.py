"""Apex Margin Advisor branding constants — single source of truth across UI and docs."""
from __future__ import annotations

from pathlib import Path

from app.config import settings

_CFG = settings()

APP_NAME = _CFG.get("app_name", "Apex Margin Advisor")
APP_FULL_NAME = _CFG.get("app_full_name", "TIC Portfolio Margin & Exception Intelligence Assistant")
TAGLINE = _CFG.get("tagline", "Management by Exception across OWMS, EFL, GTE, CRC & CAT")
VERSION = _CFG.get("version", "1.0.0")

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS / "apex_margin_logo.svg"

EMERALD = "#065F46"
ROYAL = "#1E3A8A"
INK = "#0B1F3A"


def page_title(page: str | None = None) -> str:
    if page:
        return f"{APP_NAME} · {page}"
    return f"{APP_NAME} · {APP_FULL_NAME}" if APP_FULL_NAME else APP_NAME


def footer_line() -> str:
    return f"{APP_NAME} v{VERSION} · {TAGLINE}"

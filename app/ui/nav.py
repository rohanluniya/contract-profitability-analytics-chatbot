"""Top navigation registry (Chat, Exception Triage, Portfolio & Overhead, Data Catalog, User Guide, About)."""
from __future__ import annotations

import streamlit as st

PAGES: dict[str, "st.Page"] = {}


def build() -> list:
    from app.ui.views import about, action_plan, catalog, chat, exceptions, portfolio, user_guide

    PAGES.clear()
    PAGES["chat"] = st.Page(chat.render, title="Chat", icon="💬", url_path="chat", default=True)
    PAGES["exceptions"] = st.Page(exceptions.render, title="Exception Triage", icon="🚨", url_path="exceptions")
    PAGES["plan"] = st.Page(action_plan.render, title="Action Plan & Notes", icon="🗓️", url_path="action-plan")
    PAGES["portfolio"] = st.Page(portfolio.render, title="Portfolio & Overhead", icon="📋", url_path="portfolio")
    PAGES["catalog"] = st.Page(catalog.render, title="Data Catalog", icon="🗂️", url_path="catalog")
    PAGES["guide"] = st.Page(user_guide.render, title="User Guide", icon="📘", url_path="guide")
    PAGES["about"] = st.Page(about.render, title="About", icon="ℹ️", url_path="about")
    return list(PAGES.values())


def go(name: str) -> None:
    st.switch_page(PAGES[name])

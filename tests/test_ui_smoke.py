"""Headless Streamlit AppTest smoke verification for Apex Margin Advisor UI."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from scripts.reset_demo_data import reset_all

APP_PATH = str(Path(__file__).resolve().parents[1] / "app" / "ui" / "streamlit_app.py")


def test_streamlit_signin_and_chat_smoke():
    reset_all()
    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.run()
    assert not at.exception

    # Sign in via demo gate (set both form fields before clicking submit)
    at.text_input[0].input("Jordan Vance")
    at.text_input[1].input("apex-demo-2026")
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state["auth_user"] == "jordan_vance"

    # Submit /trace FS-AERO-104 in chat input
    at.chat_input[0].set_value("/trace FS-AERO-104").run()
    assert not at.exception
    msgs = at.session_state["messages"]
    assert len(msgs) >= 2
    assert msgs[-1]["role"] == "assistant"
    assert "FS-AERO-104" in msgs[-1]["answer"]["answer_markdown"]
    assert "168.0%" in str(msgs[-1]["answer"]["table_records"])


def test_all_ui_views_render_cleanly():
    """Verify every view function imports and renders with zero uncaught exceptions."""
    reset_all()
    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.session_state["auth_user"] = "smoke_tester"
    at.session_state["auth_name"] = "Smoke Tester"
    at.run()
    assert not at.exception

    for page_key in ("exceptions", "plan", "portfolio", "catalog", "guide", "about", "chat"):
        at.session_state["nav_goto"] = page_key
        at.run()
        assert not at.exception, f"View '{page_key}' raised exception: {at.exception}"

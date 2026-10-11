"""Off-limits apps and sites: Jarvis never controls them."""
import asyncio

from app.automation import guard, selection
from app.tools.builtin import control, screen_click


def test_password_managers_terminals_and_settings_are_off_limits():
    for app in ("1Password", "System Settings", "Terminal", "Keychain Access", "iTerm2"):
        assert "off-limits" in guard.app_reason(app)
    assert guard.app_reason("Safari") == "" and guard.app_reason("Finder") == ""


def test_banking_and_account_pages_are_off_limits():
    assert "off-limits" in guard.site_reason("https://www.santanderbank.co.uk/login")
    assert "off-limits" in guard.site_reason("https://www.paypal.com/myaccount")
    assert guard.site_reason("https://www.youtube.com/watch?v=1") == ""


def test_control_tools_refuse_in_an_off_limits_app(monkeypatch):
    monkeypatch.setattr(control, "_accessibility_ok", lambda: True)
    monkeypatch.setattr(selection, "user_app", lambda: "1Password")
    assert "off-limits" in asyncio.run(control.ui_press("Unlock"))
    assert "off-limits" in asyncio.run(control.ui_type("hunter2"))
    assert "off-limits" in control.ui_elements()
    monkeypatch.setattr(screen_click, "_accessibility_ok", lambda: True)
    assert "off-limits" in screen_click.screen_click("Copy password")


def test_routines_never_control_the_screen():
    from app import routines
    from app.chat import service
    token = service.channels.current.set(routines.RoutineSession())
    try:
        out = {}

        async def run():
            async for _ in service._execute_with_permission("scroll", {"direction": "down"}, [], out):
                pass
        asyncio.run(run())
    finally:
        service.channels.current.reset(token)
    assert "routines never do" in out["output"]

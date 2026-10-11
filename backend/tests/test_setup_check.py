"""The setup check lists every permission and model with a status."""
import asyncio

from app import setup_check


def test_setup_check_reports_every_area(monkeypatch):
    monkeypatch.setattr(setup_check, "automation_status", lambda b, ask=False: 0)

    async def up():
        return False
    monkeypatch.setattr(setup_check.ollama_client, "is_up", up)
    result = asyncio.run(setup_check.run_all())
    ids = {c["id"] for c in result["checks"]}
    assert {"ollama", "accessibility", "screen", "calendar", "telegram"} <= ids
    assert any(i.startswith("automation:") for i in ids)
    ollama = next(c for c in result["checks"] if c["id"] == "ollama")
    assert ollama["status"] == "missing" and ollama["fix"] == "start"
    for c in result["checks"]:
        assert c["status"] in ("ok", "missing", "ask", "unknown", "optional", "restart")
        assert c["why"]


def test_a_grant_the_backend_cant_see_yet_asks_for_a_restart(monkeypatch):
    import ApplicationServices as AS
    import Quartz
    monkeypatch.setattr(AS, "AXIsProcessTrusted", lambda: False)
    monkeypatch.setattr(Quartz, "CGPreflightScreenCaptureAccess", lambda: False)
    # Switched on, but only a freshly started process sees it.
    ax = setup_check._accessibility(fresh=True)
    assert ax["status"] == "restart" and ax["fix"] == "restart"
    # Not switched on anywhere (or switched on for an older build): ask again.
    screen = setup_check._screen(fresh=False)
    assert screen["status"] == "missing" and screen["fix"] == "prompt"
    assert "remove it" in screen["detail"]


def test_fresh_grants_come_from_a_new_process():
    grants = setup_check._fresh_grants()
    assert grants is None or (len(grants) == 2 and all(isinstance(g, bool) for g in grants))


def test_images_are_shrunk_before_the_vision_model():
    from pathlib import Path

    import pytest
    from app.vision import ocr
    src = Path("/System/Library/Desktop Pictures/iMac Blue.heic")   # a big macOS picture
    if not src.exists():
        pytest.skip("macOS picture not available")
    out = ocr.shrink_for_vision(src.read_bytes())
    assert out[:2] == b"\xff\xd8"              # JPEG now
    assert len(out) < src.stat().st_size


def test_calendar_and_reminders_need_full_access(monkeypatch):
    import sys
    import types
    status = {}
    store = types.SimpleNamespace(authorizationStatusForEntityType_=lambda e: status[e])
    monkeypatch.setitem(sys.modules, "EventKit", types.SimpleNamespace(
        EKEventStore=store, EKEntityTypeEvent="event", EKEntityTypeReminder="reminder"))
    for code, expected, fix in [(0, "ask", "prompt"), (2, "missing", "settings"),
                                (3, "ok", ""), (4, "missing", "settings")]:
        status.update(event=code, reminder=code)
        for check in (setup_check._calendar(), setup_check._reminders()):
            assert (check["status"], check["fix"]) == (expected, fix), (code, check)
    assert "Full Access" in setup_check._reminders()["detail"]   # write-only can't read

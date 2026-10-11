"""Offering help when the same error stays on screen."""
from app.config import settings
from app.vision import proactive

ERR = "ModuleNotFoundError: No module named 'requests'"


def setup_function():
    proactive.reset()
    settings.update({"proactive": {"enabled": True}})


def teardown_function():
    settings.update({"proactive": {"enabled": False}})


def test_offers_after_the_same_error_persists(monkeypatch):
    monkeypatch.setattr(proactive, "_in_meeting", lambda: False)
    screen = f"main.py\n{ERR}\nline 3"
    t0 = 1_000_000.0
    assert proactive.observe(screen, t0) is None
    assert proactive.observe(screen, t0 + 300) is None            # only 5 minutes
    offer = proactive.observe(screen, t0 + 600)                   # 3rd sighting, 10 min
    assert offer and "No module named" in offer["text"] and "10 minutes" in offer["text"]
    assert "requests" in offer["action"]["prompt"]
    assert proactive.observe(screen, t0 + 900) is None            # not again so soon


def test_a_fixed_error_resets_and_unrelated_screens_dont_trigger(monkeypatch):
    monkeypatch.setattr(proactive, "_in_meeting", lambda: False)
    t0 = 2_000_000.0
    proactive.observe(ERR, t0)
    proactive.observe("all good now", t0 + 300)                   # error gone
    assert proactive.observe(ERR, t0 + 600) is None               # streak restarted
    for i in range(5):
        assert proactive.observe("Reading the news about football", t0 + 900 + 300 * i) is None


def test_off_by_default_and_quiet_in_meetings(monkeypatch):
    settings.update({"proactive": {"enabled": False}})
    t0 = 3_000_000.0
    for i in range(4):
        assert proactive.observe(ERR, t0 + 300 * i) is None
    settings.update({"proactive": {"enabled": True}})
    monkeypatch.setattr(proactive, "_in_meeting", lambda: True)
    for i in range(4):
        assert proactive.observe(ERR, t0 + 300 * i) is None

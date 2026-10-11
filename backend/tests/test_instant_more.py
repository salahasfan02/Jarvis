"""Timers, reminders, volume, time, sums, undo and files as instant commands."""
import asyncio
import datetime

from app import timers, ui_bridge
from app.chat import quick, timeparse
from app.tools.builtin import macos, timer_tools


def test_durations_and_clock_times():
    assert timeparse.duration("an hour and a half") == 5400
    assert timeparse.duration("10 mins and 30 seconds") == 630
    assert timeparse.duration("banana") is None
    now = datetime.datetime(2026, 10, 11, 13, 30)
    assert timeparse.when("at 6", now) == datetime.datetime(2026, 10, 11, 18, 0)
    assert timeparse.when("tomorrow at 3", now) == datetime.datetime(2026, 10, 12, 15, 0)
    assert timeparse.when("tomorrow at 9:30am", now) == datetime.datetime(2026, 10, 12, 9, 30)
    assert timeparse.when("tonight at 8", now) == datetime.datetime(2026, 10, 11, 20, 0)


def test_new_instant_commands(monkeypatch):
    monkeypatch.setattr(quick, "_installed_apps", lambda: {})
    cases = {
        "set a pasta timer for 10 minutes": ("set_timer", {"seconds": 600.0, "label": "pasta"}),
        "remind me in 20 minutes to check the oven":
            ("set_timer", {"seconds": 1200.0, "label": "check the oven", "reminder": True}),
        "volume up": ("set_volume", {"change": "up"}),
        "set volume to 40%": ("set_volume", {"level": 40}),
        "what's 17% of 2340": ("calculator", {"expression": "17/100*2340"}),
        "undo that": ("undo_last", {}),
        "cancel the pasta timer": ("timers", {"cancel": True, "label": "pasta"}),
    }
    for text, (tool, args) in cases.items():
        a = quick.match(text)
        assert a and (a.tool, a.arguments) == (tool, args), text
    r = quick.match("remind me tomorrow at 9 to send the report")
    assert r.tool == "create_reminder" and r.arguments["title"] == "Send the report"
    assert r.arguments["due"].endswith("09:00")
    for text in ("what's the weather", "what is love", "remind me about the meeting"):
        assert quick.match(text) is None


def test_sums_and_time_replies_read_naturally():
    a = quick.match("what's 17% of 2340")
    assert quick.reply_for(a, "397.79999999999995") == "17% of 2340 is 397.8."
    assert quick.reply_for(quick.match("what is 1000 times 12"), "12000") == "1000 times 12 is 12,000."
    assert quick.match("what time is it").reply.startswith("It's ")


def test_open_my_cv_opens_the_file(monkeypatch, tmp_path):
    cv = tmp_path / "CV_Salah.pdf"
    cv.write_text("x")
    monkeypatch.setattr(quick, "_installed_apps", lambda: {})
    from app.tools.builtin import documents
    monkeypatch.setattr(documents, "find_file", lambda q: (cv, []) if "cv" in q else (None, []))
    a = quick.match("open my CV")
    assert (a.tool, a.arguments) == ("open_file", {"path": str(cv)})
    assert quick.match("open the pod bay doors") is None


def test_timer_rings_and_can_be_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(timers, "STORE", tmp_path / "timers.json")
    said = []

    async def announce(title, text, speak=True):
        said.append(text)
        return True
    monkeypatch.setattr(ui_bridge, "announce", announce)
    monkeypatch.setattr(timers, "_notify", lambda *a: None)

    from app.tools import base as tools

    async def scenario():
        timers.start(0.05, "pasta")                      # (the tool's minimum is 1 s)
        # through the real tool runner, as chat and instant commands call it
        assert "Laundry timer set — 10 minutes" in await tools.execute(
            "set_timer", {"minutes": 10, "label": "laundry"})
        assert "Laundry: 10 minutes left" in await tools.execute("timers", {})
        await asyncio.sleep(0.2)
        assert said == ["Your pasta timer is done."]
        assert "Cancelled laundry" in await tools.execute("timers", {"cancel": True, "label": "laundry"})
        assert timers.active() == []
    asyncio.run(scenario())


def test_reminder_and_event_dates_dont_depend_on_the_macs_region():
    script = macos.as_date("d", datetime.datetime(2026, 10, 12, 15, 30))
    assert "set year of d to 2026" in script and "set month of d to 10" in script
    assert "set day of d to 12" in script and "set hours of d to 15" in script
    assert 'date "' not in script

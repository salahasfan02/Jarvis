"""Routines: scheduling rules, triggers, delivery, and what they may run."""
import asyncio
import datetime

from app import routines
from app.tools.builtin import routine_tools


def setup_function():
    for r in routines.all_routines():
        routines.remove(r["id"])


def test_create_parses_times_and_days():
    out = routine_tools.create_routine("Morning briefing", "weekdays", at="8am",
                                       action="give me my daily briefing", deliver="telegram")
    assert "weekdays at 08:00" in out
    r = routines.get("morning briefing")
    assert r["trigger"] == {"type": "time", "at": "08:00", "days": ["mon", "tue", "wed", "thu", "fri"]}
    assert "need a time" in routine_tools.create_routine("x", "daily", at="soon")
    assert "every 5 minutes" in routine_tools.create_routine("x", "every", every_minutes=1)
    out = routine_tools.create_routine("Gym", "days", at="18:30", days=["Monday", "thu"])
    assert "Mon, Thu at 18:30" in out


def test_time_trigger_fires_once_per_day_and_not_when_missed_long_ago():
    r = routines.add("t", {"type": "time", "at": "08:00", "days": routines.DAYS})
    monday_0805 = datetime.datetime(2026, 10, 12, 8, 5)
    assert routines._due_time(r, monday_0805)
    routines.update(r["id"], last_fired=monday_0805.timestamp())
    assert not routines._due_time(routines.get(r["id"]), monday_0805)       # already fired
    assert not routines._due_time(r, datetime.datetime(2026, 10, 12, 9, 30))  # missed: skip
    weekdays = routines.add("w", {"type": "time", "at": "08:00", "days": routines.DAYS[:5]})
    assert not routines._due_time(weekdays, datetime.datetime(2026, 10, 11, 8, 1))  # Sunday


def test_email_trigger_ignores_old_mail_then_reports_new(monkeypatch):
    from app.tools.builtin import mail
    inbox = [{"id": 1, "from": "Tom <tom@x.com>", "subject": "Rent"}]
    monkeypatch.setattr(mail, "_list", lambda *a: list(inbox))
    r = routines.add("landlord", {"type": "email", "from": "tom@x.com", "subject": ""})
    assert asyncio.run(routines._check_email(routines.get(r["id"]))) == []   # first look
    routines.update(r["id"], state={**routines.get(r["id"])["state"], "checked": 0})
    inbox.append({"id": 2, "from": "Tom <tom@x.com>", "subject": "Boiler fixed"})
    events = asyncio.run(routines._check_email(routines.get(r["id"])))
    assert len(events) == 1 and "Boiler fixed" in events[0]


def test_alert_only_routine_delivers_the_event(monkeypatch):
    sent = []

    async def deliver(r, text):
        sent.append(text)
        return "notification"
    monkeypatch.setattr(routines, "deliver", deliver)
    r = routines.add("meetings", {"type": "calendar", "minutes_before": 10})
    asyncio.run(routines.fire(r, ["📅 “Standup” starts in 10 minutes"]))
    assert sent == ["📅 “Standup” starts in 10 minutes"]


def test_routines_never_send_email_on_their_own():
    from app.chat import service
    session = routines.RoutineSession()
    token = service.channels.current.set(session)
    try:
        events, out = [], {}

        async def run():
            async for ev in service._execute_with_permission(
                    "send_email", {"to": "a@b.com", "subject": "x", "body": "y"}, [], out):
                events.append(ev)
        asyncio.run(run())
    finally:
        service.channels.current.reset(token)
    assert "routines can't use it" in out["output"]
    assert not any(e["type"] == "confirm_request" for e in events)


def test_trigger_is_inferred_when_the_model_leaves_it_out():
    assert "when an email arrives from my landlord" in routine_tools.create_routine(
        "Landlord mail", email_from="my landlord")
    assert "15 minutes before" in routine_tools.create_routine("Meetings", minutes_before=15)
    assert "every day at 07:30" in routine_tools.create_routine("Wake", at="7:30am")


def test_routines_page_api_creates_and_edits():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app, base_url="http://127.0.0.1:8765")   # trusted-host check
    r = client.post("/api/routines", json={"trigger": "weekdays", "at": "7:45am",
                                           "action": "give me my briefing", "deliver": "speak"}).json()
    assert r["summary"] == "weekdays at 07:45" and r["name"] == "Give me my briefing"
    bad = client.post("/api/routines", json={"trigger": "daily", "at": "whenever"}).json()
    assert "need a time" in bad["error"]
    edited = client.put(f"/api/routines/{r['id']}", json={"trigger": "calendar",
                                                          "minutes_before": "15"}).json()
    assert edited["summary"] == "15 minutes before each calendar event"
    assert client.put(f"/api/routines/{r['id']}", json={"enabled": False}).json()["enabled"] is False

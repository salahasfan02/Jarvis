"""Tools to set up routines and triggers by asking ("every weekday at 8 send me
the briefing on Telegram", "tell me when my landlord emails")."""
from __future__ import annotations

import datetime
import re

from ... import routines
from ..base import tool

_DAY_ALIASES = {"monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
                "friday": "fri", "saturday": "sat", "sunday": "sun"}


def _hhmm(text: str) -> str | None:
    m = re.fullmatch(r"\s*(\d{1,2})(?::|\.)?(\d{2})?\s*(am|pm)?\s*", (text or "").lower())
    if not m:
        return None
    h, mins, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm == "pm" and h < 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mins:02d}" if h < 24 and mins < 60 else None


def build_trigger(trigger: str = "", at: str = "", days: list | None = None,
                  every_minutes: int = 0, email_from: str = "", email_subject: str = "",
                  minutes_before: int = 0) -> tuple[dict | None, str]:
    """(trigger spec, "") or (None, what's wrong) — shared with the Routines page."""
    if not trigger:   # infer it from what was given
        trigger = ("email" if email_from or email_subject else
                   "calendar" if minutes_before else
                   "every" if every_minutes else
                   "once" if re.search(r"\d{4}-\d{2}-\d{2}", at or "") else
                   "days" if days else "daily" if at else "")
        if not trigger:
            return None, "When should it run? (a time, every N minutes, an email, or before meetings)"
    if trigger in ("daily", "weekdays", "weekends", "days"):
        time = _hhmm(at)
        if not time:
            return None, f"I need a time like 08:00 or 6pm for that routine (got '{at}')."
        chosen = {"daily": routines.DAYS, "weekdays": routines.DAYS[:5],
                  "weekends": routines.DAYS[5:]}.get(trigger)
        if chosen is None:
            chosen = [_DAY_ALIASES.get(d.lower(), d.lower()[:3]) for d in (days or [])]
            chosen = [d for d in routines.DAYS if d in chosen]
            if not chosen:
                return None, "Which days? (mon, tue, …)"
        spec = {"type": "time", "at": time, "days": chosen}
    elif trigger == "every":
        if every_minutes < 5:
            return None, "Routines can repeat at most every 5 minutes."
        spec = {"type": "interval", "minutes": every_minutes}
    elif trigger == "once":
        try:
            when = datetime.datetime.fromisoformat(at.strip().replace(" ", "T"))
        except ValueError:
            return None, f"I need a date and time like 2026-10-12 15:00 (got '{at}')."
        if when < datetime.datetime.now():
            return None, f"{when:%d %b %H:%M} is in the past."
        spec = {"type": "once", "at": when.isoformat(timespec="minutes")}
    elif trigger == "email":
        if not (email_from or email_subject):
            return None, "Whose emails (or which subject) should I watch for?"
        spec = {"type": "email", "from": email_from.strip(), "subject": email_subject.strip()}
    elif trigger == "calendar":
        spec = {"type": "calendar", "minutes_before": max(1, min(int(minutes_before or 10), 240))}
    else:
        return None, f"Unknown trigger '{trigger}'."
    return spec, ""


@tool(
    name="create_routine",
    description="Set up something Jarvis does automatically, without being asked: on a "
                "schedule (\"every weekday at 8 send me my briefing\"), every N minutes, "
                "once at a date/time, when an email arrives from someone or about "
                "something, or N minutes before each calendar event. `action` is the "
                "instruction to carry out each time (e.g. \"give me my daily briefing\"); "
                "leave it empty to just pass on the alert. Results go to Telegram, a "
                "notification, or are spoken by the app.",
    parameters={"type": "object", "properties": {
        "name": {"type": "string", "description": "short name, e.g. Morning briefing"},
        "trigger": {"type": "string", "enum": ["daily", "weekdays", "weekends", "days",
                                               "every", "once", "email", "calendar"]},
        "at": {"type": "string", "description": "time like 08:00 or 6pm (daily/weekdays/"
                                                "weekends/days); date-time like "
                                                "2026-10-12 15:00 for once"},
        "days": {"type": "array", "items": {"type": "string"},
                 "description": "for trigger=days: mon, tue, …"},
        "every_minutes": {"type": "integer", "description": "for trigger=every"},
        "email_from": {"type": "string", "description": "for trigger=email: sender name, "
                                                       "relation (my landlord) or address"},
        "email_subject": {"type": "string", "description": "for trigger=email: subject words"},
        "minutes_before": {"type": "integer", "description": "for trigger=calendar"},
        "action": {"type": "string", "description": "what to do each time (optional)"},
        "deliver": {"type": "string", "enum": ["auto", "telegram", "notification", "speak"],
                    "description": "where the result goes (auto: phone if connected, "
                                   "else the Mac)"},
    }},
    risk="confirm",
    agent_tags=["automation", "calendar", "email", "messaging", "_conversation"],
)
def create_routine(name: str = "", trigger: str = "", at: str = "", days: list | None = None,
                   every_minutes: int = 0, email_from: str = "", email_subject: str = "",
                   minutes_before: int = 0, action: str = "", deliver: str = "auto") -> str:
    name = name.strip() or (action.strip()[:40] or "Routine").capitalize()
    spec, error = build_trigger(trigger, at, days, every_minutes, email_from, email_subject,
                                minutes_before)
    if spec is None:
        return error
    r = routines.add(name, spec, action, deliver)
    from ... import activity
    activity.offer_undo(kind="delete_routine", id=r["id"])
    what = f" → {action}" if action else ""
    return f"Routine “{r['name']}” set: {r['summary']}{what} (delivered: {deliver})."


@tool(
    name="list_routines",
    description="List the routines and triggers Jarvis runs automatically.",
    parameters={"type": "object", "properties": {}},
    agent_tags=["automation", "calendar", "email", "messaging", "_conversation"],
)
def list_routines() -> str:
    rs = routines.all_routines()
    if not rs:
        return "No routines set up yet."
    return "\n".join(f"- {r['name']}: {r['summary']}"
                     + (f" → {r['action']}" if r["action"] else "")
                     + ("" if r["enabled"] else " (paused)") for r in rs)


@tool(
    name="change_routine",
    description="Pause, resume, delete or run now one of the user's routines (by name).",
    parameters={"type": "object", "properties": {
        "name": {"type": "string"},
        "change": {"type": "string", "enum": ["pause", "resume", "delete", "run_now"]},
    }, "required": ["name", "change"]},
    risk="confirm",
    agent_tags=["automation", "calendar", "email", "messaging", "_conversation"],
)
async def change_routine(name: str, change: str) -> str:
    r = routines.get(name)
    if r is None:
        return f"No routine called '{name}'.\n" + list_routines()
    if change == "delete":
        routines.remove(r["id"])
        return f"Deleted “{r['name']}”."
    if change in ("pause", "resume"):
        routines.update(r["id"], enabled=change == "resume")
        return f"{'Resumed' if change == 'resume' else 'Paused'} “{r['name']}”."
    if change == "run_now":
        return await routines.fire(r)
    return f"Unknown change '{change}'."

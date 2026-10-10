"""Reading the user's calendar.

Uses EventKit (the framework Calendar.app itself uses) through PyObjC: fast,
and it expands repeating events. The old AppleScript query walked every
calendar (often timing out) and only matched a repeating event's FIRST
occurrence, so weekly meetings never showed. AppleScript remains the
fallback where EventKit isn't installed.
"""
from __future__ import annotations

import datetime
import threading

from ..base import tool
from .macos import _osascript

GRANTED = {3}          # EKAuthorizationStatusFullAccess (== legacy Authorized)
DENIED = {1, 2, 4}     # restricted, denied, write-only


class CalendarDenied(Exception):
    pass


def _eventkit_events(start: datetime.datetime, end: datetime.datetime) -> list[dict] | None:
    """Events overlapping [start, end), or None when EventKit isn't available."""
    try:
        import EventKit
        from Foundation import NSDate
    except ImportError:
        return None
    entity = EventKit.EKEntityTypeEvent
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(entity)
    store = EventKit.EKEventStore.alloc().init()
    if status in DENIED:
        raise CalendarDenied()
    if status not in GRANTED:  # not asked yet: macOS shows its permission prompt
        done, granted = threading.Event(), [False]

        def answered(ok, _error):
            granted[0] = bool(ok)
            done.set()

        if hasattr(store, "requestFullAccessToEventsWithCompletion_"):  # macOS 14+
            store.requestFullAccessToEventsWithCompletion_(answered)
        else:
            store.requestAccessToEntityType_completion_(entity, answered)
        done.wait(60)
        if not granted[0]:
            raise CalendarDenied()
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        NSDate.dateWithTimeIntervalSince1970_(start.timestamp()),
        NSDate.dateWithTimeIntervalSince1970_(end.timestamp()), None)
    events = []
    for ev in store.eventsMatchingPredicate_(predicate) or []:
        events.append({
            "title": str(ev.title() or "(no title)"),
            "start": datetime.datetime.fromtimestamp(ev.startDate().timeIntervalSince1970()),
            "end": datetime.datetime.fromtimestamp(ev.endDate().timeIntervalSince1970()),
            "all_day": bool(ev.isAllDay()),
            "location": str(ev.location() or ""),
            "calendar": str(ev.calendar().title() or "") if ev.calendar() else "",
        })
    return sorted(events, key=lambda e: (e["start"], e["title"]))


def _applescript_events(start: datetime.datetime, days: int) -> str:
    offset = (start.date() - datetime.date.today()).days
    script = f'''
    set output to ""
    set startOfDay to (current date) - (time of (current date)) + {offset} * days
    set endWindow to startOfDay + {days} * days
    tell application "Calendar"
        repeat with cal in calendars
            set evs to (every event of cal whose start date >= startOfDay and start date < endWindow)
            repeat with ev in evs
                set output to output & (start date of ev as string) & " — " & (summary of ev) & "\\n"
            end repeat
        end repeat
    end tell
    return output'''
    return _osascript(script, timeout=90)


def format_events(events: list[dict], start: datetime.date, days: int) -> str:
    if not events:
        span = "today" if days == 1 and start == datetime.date.today() else \
            f"{start:%a %b %d}" if days == 1 else f"the {days} days from {start:%a %b %d}"
        return f"No events {span}."
    lines, current = [], None
    for e in events:
        day = e["start"].date()
        if day != current:
            current = day
            lines.append(f"{day:%A, %B %d}")
        when = "all day" if e["all_day"] else f"{e['start']:%H:%M}–{e['end']:%H:%M}"
        extra = "".join(f" · {x}" for x in (e["location"], e["calendar"]) if x)
        lines.append(f"  {when}  {e['title']}{extra}")
    return "\n".join(lines)


def events_text(start_in_days: int = 0, days: int = 1) -> str:
    days = max(1, min(int(days), 60))
    day0 = datetime.date.today() + datetime.timedelta(days=int(start_in_days))
    start = datetime.datetime.combine(day0, datetime.time())
    try:
        events = _eventkit_events(start, start + datetime.timedelta(days=days))
    except CalendarDenied:
        return ("Jarvis isn't allowed to read your calendar. Allow it in System Settings → "
                "Privacy & Security → Calendars (for Terminal, or Jarvis if you use the app), "
                "then ask again.")
    if events is None:  # no EventKit (not macOS / pyobjc-framework-EventKit missing)
        out = _applescript_events(start, days)
        return out if out not in ("", "OK") else format_events([], day0, days)
    return format_events(events, day0, days)


@tool(
    name="calendar_events",
    description="Read the user's calendar (all calendars, repeating events included). "
                "start_in_days: 0 = today, 1 = tomorrow…; days: how many days to cover.",
    parameters={
        "type": "object",
        "properties": {
            "start_in_days": {"type": "integer", "description": "0 = today (default), 1 = tomorrow"},
            "days": {"type": "integer", "description": "how many days (default 7, max 60)"},
        },
    },
    risk="confirm",
    agent_tags=["automation", "calendar", "_conversation"],
)
def calendar_events(start_in_days: int = 0, days: int = 7) -> str:
    return events_text(start_in_days, days)


@tool(
    name="calendar_today",
    description="Today's events from the user's calendar.",
    parameters={"type": "object", "properties": {}},
    risk="confirm",
    agent_tags=["automation", "calendar", "_conversation"],
)
def calendar_today() -> str:
    return events_text(0, 1)

"""Proactive help: notice when the user seems stuck, and offer a hand.

Rides on screen memory's captures (no extra screen reading). Every capture's
text is scanned for error lines; when the SAME error stays on screen for 3
captures in a row spanning at least 8 minutes, Jarvis offers help with a card
and a "Help me" button. Opt-in, and polite: at most one offer every 30
minutes, never the same error twice in a day, and nothing while the user is
in a calendar event.
"""
from __future__ import annotations

import asyncio
import re
import time

from ..config import settings
from ..security import audit

STREAK = 3
MIN_STUCK = 8 * 60
GAP = 30 * 60

ERROR = re.compile(
    r"\b(?:error|exception|traceback|failed|failure|fatal|crash(?:ed)?|denied|refused|"
    r"timed out|not found|cannot|can['’]t|couldn['’]t|unable to|invalid|"
    r"no module named|command not found|is not recognized|segmentation fault)\b", re.I)
_NOISE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?|\b\d+\b")

_seen: dict[str, dict] = {}
_offered: dict[str, float] = {}
_last_offer = 0.0


def enabled() -> bool:
    return bool(settings.get("proactive.enabled", False))


def error_lines(text: str) -> dict[str, str]:
    """{normalized line: original line} for lines that look like errors."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if 12 <= len(line) <= 220 and ERROR.search(line):
            key = _NOISE.sub("#", line.lower())
            out.setdefault(key, line)
    return out


def _in_meeting() -> bool:
    try:
        import datetime
        from ..tools.builtin import calendars
        now = datetime.datetime.now()
        events = calendars._eventkit_events(now, now + datetime.timedelta(minutes=1)) or []
        return any(not e["all_day"] and e["start"] <= now < e["end"] for e in events)
    except Exception:
        return False


def observe(text: str, now: float | None = None) -> dict | None:
    """Feed one capture. Returns the offer it made (or None)."""
    global _last_offer
    if not enabled():
        return None
    now = now or time.time()
    lines = error_lines(text)
    for key in list(_seen):              # gone from the screen: resolved
        if key not in lines:
            del _seen[key]
    for key, line in lines.items():
        entry = _seen.setdefault(key, {"line": line, "first": now, "count": 0})
        entry["count"] += 1
        entry["last"] = now
    if now - _last_offer < GAP:
        return None
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    for key, e in sorted(_seen.items(), key=lambda kv: kv[1]["first"]):
        if e["count"] < STREAK or now - e["first"] < MIN_STUCK:
            continue
        if _offered.get(f"{day}|{key}"):
            continue
        if _in_meeting():
            return None
        _offered[f"{day}|{key}"] = now
        _last_offer = now
        minutes = round((now - e["first"]) / 60)
        offer = {
            "title": "💡 Want a hand?",
            "text": f"You've had “{e['line'][:120]}” on screen for about {minutes} minutes.",
            "action": {"label": "Help me",
                       "prompt": f"I seem to be stuck on this, which has been on my screen for "
                                 f"{minutes} minutes: “{e['line']}”. Look at my screen for "
                                 f"context and help me fix it."},
        }
        audit.log("proactive_offer", line=e["line"][:200], minutes=minutes)
        try:
            from .. import ui_bridge
            asyncio.get_running_loop().create_task(
                ui_bridge.announce(offer["title"], offer["text"], speak=False,
                                   action=offer["action"]))
        except RuntimeError:
            pass
        return offer
    return None


def reset() -> None:
    global _last_offer
    _seen.clear()
    _offered.clear()
    _last_offer = 0.0

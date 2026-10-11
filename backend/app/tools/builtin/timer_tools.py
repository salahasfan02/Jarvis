"""Timer, volume and other small instant tools."""
from __future__ import annotations

import re
import subprocess
import time

from ... import timers
from ..base import tool


@tool(
    name="set_timer",
    description="Start a countdown timer (\"10 minute pasta timer\"), or a quick reminder in "
                "N minutes (\"remind me in 20 minutes to check the oven\" → label 'check the "
                "oven', reminder=true). Jarvis says it out loud and notifies when it ends.",
    parameters={"type": "object", "properties": {
        "minutes": {"type": "number"},
        "seconds": {"type": "number"},
        "label": {"type": "string", "description": "what it's for (optional)"},
        "reminder": {"type": "boolean", "description": "true for 'remind me in N minutes to …'"},
    }},
)
async def set_timer(minutes: float = 0, seconds: float = 0, label: str = "",
                    reminder: bool = False) -> str:
    # async: the timer is scheduled on Jarvis's event loop (sync tools run in a
    # worker thread, which has none).
    total = float(minutes or 0) * 60 + float(seconds or 0)
    if total < 1:
        return "How long should the timer be?"
    if total > 24 * 3600:
        return "Timers can be up to 24 hours — for longer, use a reminder."
    t = timers.start(total, label, reminder)
    what = f"I'll remind you to {t['label']}" if reminder and t["label"] else \
        f"{t['label'].capitalize()} timer set" if t["label"] else "Timer set"
    return f"{what} — {timers.describe(total)}."


@tool(
    name="timers",
    description="How long is left on the running timers, or cancel them (\"cancel the pasta "
                "timer\", \"stop the timer\").",
    parameters={"type": "object", "properties": {
        "cancel": {"type": "boolean"},
        "label": {"type": "string", "description": "which one (optional)"},
    }},
)
async def timers_tool(cancel: bool = False, label: str = "") -> str:
    if cancel:
        gone = timers.cancel(label)
        if not gone:
            return "There's no timer like that running."
        names = ", ".join(t["label"] or "timer" for t in gone)
        return f"Cancelled {names}."
    running = timers.active()
    if not running:
        return "No timers are running."
    return " ".join(f"{(t['label'] or 'Your timer').capitalize()}: "
                    f"{timers.describe(t['ends_at'] - time.time())} left." for t in running)


def _volume_now() -> int:
    r = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                       capture_output=True, text=True, timeout=5)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 50


@tool(
    name="set_volume",
    description="Change the Mac's sound volume: level 0-100, or change 'up'/'down', or "
                "'mute'/'unmute'.",
    parameters={"type": "object", "properties": {
        "level": {"type": "integer", "description": "0-100"},
        "change": {"type": "string", "enum": ["up", "down", "mute", "unmute"]},
    }},
    agent_tags=["automation", "music"],
)
def set_volume(level: int | None = None, change: str = "") -> str:
    if change in ("mute", "unmute"):
        subprocess.run(["osascript", "-e", f"set volume output muted {str(change == 'mute').lower()}"],
                       capture_output=True, timeout=5)
        return "Muted." if change == "mute" else "Unmuted."
    if level is None:
        now = _volume_now()
        level = now + 15 if change == "up" else now - 15 if change == "down" else now
    level = max(0, min(100, int(level)))
    subprocess.run(["osascript", "-e", f"set volume output volume {level} without output muted"],
                   capture_output=True, timeout=5)
    return f"Volume {level}%."


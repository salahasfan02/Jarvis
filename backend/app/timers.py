"""Timers: "set a timer for 10 minutes", "remind me in 20 minutes to …".

Each timer is an asyncio task; the list is saved to disk so timers survive a
restart of Jarvis. When one ends, the Jarvis window says and shows it, and a
macOS notification with a sound appears (so it's noticed even with Jarvis
hidden); if no Jarvis window is open, the phone gets it too.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid

from .config import JARVIS_HOME
from .security import audit

STORE = JARVIS_HOME / "timers.json"
_timers: dict[str, dict] = {}


def _save() -> None:
    STORE.write_text(json.dumps([{k: v for k, v in t.items() if k != "task"}
                                 for t in _timers.values()]))


def describe(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = [f"{h} hour{'s' if h != 1 else ''}" if h else "",
             f"{m} minute{'s' if m != 1 else ''}" if m else "",
             f"{s} second{'s' if s != 1 else ''}" if s and not h else ""]
    return " ".join(p for p in parts if p) or "0 seconds"


def _notify(title: str, text: str) -> None:
    safe = text.replace('"', "'")[:200]
    subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "{title}" '
                    f'sound name "Glass"'], capture_output=True, timeout=10)


async def _ring(t: dict) -> None:
    from . import ui_bridge
    label = t.get("label") or ""
    text = (f"Time to {label}." if t.get("reminder") else
            f"Your {label} timer is done." if label else "Your timer is done.")
    shown = await ui_bridge.announce("⏲ Timer", text, speak=True)
    await asyncio.to_thread(_notify, "Jarvis", text)
    if not shown:
        try:
            from .channels import telegram
            bot, users = telegram._bot, telegram.allowed_users()
            if bot is not None and bot.running:
                for u in users:
                    await bot.send_text(u["id"], f"⏲ {text}")
        except Exception:
            pass
    audit.log("timer_done", label=label)


def _schedule(t: dict) -> None:
    async def wait():
        try:
            await asyncio.sleep(max(0.0, t["ends_at"] - time.time()))
            _timers.pop(t["id"], None)
            _save()
            await _ring(t)
        except asyncio.CancelledError:
            pass
    t["task"] = asyncio.get_running_loop().create_task(wait())
    _timers[t["id"]] = t


def start(seconds: float, label: str = "", reminder: bool = False) -> dict:
    t = {"id": uuid.uuid4().hex[:8], "label": label.strip(), "ends_at": time.time() + seconds,
         "seconds": seconds, "reminder": reminder}
    _schedule(t)
    _save()
    return t


def active() -> list[dict]:
    return sorted(({k: v for k, v in t.items() if k != "task"} for t in _timers.values()),
                  key=lambda t: t["ends_at"])


def cancel(label: str = "") -> list[dict]:
    """Cancel timers matching `label` (all when empty or only one exists)."""
    want = label.strip().lower()
    hits = [t for t in _timers.values()
            if not want or len(_timers) == 1 or want in (t.get("label") or "").lower()]
    for t in hits:
        t["task"].cancel()
        _timers.pop(t["id"], None)
    _save()
    return hits


def restore() -> None:
    """At startup: bring back timers saved before Jarvis restarted."""
    try:
        saved = json.loads(STORE.read_text())
    except (OSError, ValueError):
        return
    for t in saved:
        if t["ends_at"] > time.time() - 60:       # ended while closed: ring now
            _schedule(t)

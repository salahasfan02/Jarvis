"""Routines and triggers: Jarvis acting without being asked.

  "every weekday at 8, send me the briefing on Telegram"   -> time trigger
  "every 30 minutes check …"                               -> interval
  "tell me when an email from my landlord arrives"          -> email trigger
  "remind me 10 minutes before meetings"                    -> calendar trigger
  "at 3pm tomorrow remind me to …"                          -> once

A routine with an `action` runs it as a normal Jarvis turn (same agents and
tools) in the "⏰ Routines" conversation, then delivers the result: Telegram,
a macOS notification, or spoken/shown by the Jarvis app. Nobody is there to
approve things, so routines may use read-only and confirm-level tools but
never ones that always need the user (sending email) or dangerous ones.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

from . import channels, db
from .security import audit

TICK = 20                 # seconds between checks
EMAIL_EVERY = 120         # seconds between mailbox checks per routine
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trigger TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT '',
    deliver TEXT NOT NULL DEFAULT 'auto',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fired REAL NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
"""
_ready = False
_task: asyncio.Task | None = None


def _ensure() -> None:
    global _ready
    if not _ready:
        with db.connect() as conn:
            conn.executescript(_SCHEMA)
        _ready = True


def _row(r) -> dict:
    d = dict(r)
    d["trigger"] = json.loads(d["trigger"])
    d["state"] = json.loads(d["state"] or "{}")
    d["enabled"] = bool(d["enabled"])
    d["summary"] = describe_trigger(d["trigger"])
    return d


def all_routines() -> list[dict]:
    _ensure()
    with db.connect() as conn:
        return [_row(r) for r in conn.execute("SELECT * FROM routines ORDER BY created_at")]


def get(ref: str) -> dict | None:
    ref = ref.strip().lower()
    rs = all_routines()
    return (next((r for r in rs if r["id"] == ref), None)
            or next((r for r in rs if r["name"].lower() == ref), None)
            or next((r for r in rs if ref and ref in r["name"].lower()), None))


def add(name: str, trigger: dict, action: str = "", deliver: str = "auto") -> dict:
    _ensure()
    r = {"id": uuid.uuid4().hex[:10], "name": name.strip() or "Routine",
         "trigger": json.dumps(trigger), "action": action.strip(), "deliver": deliver,
         "enabled": 1, "last_fired": 0, "state": "{}", "created_at": time.time()}
    with db.connect() as conn:
        conn.execute("INSERT INTO routines VALUES (:id, :name, :trigger, :action, :deliver, "
                     ":enabled, :last_fired, :state, :created_at)", r)
    audit.log("routine_created", name=name, trigger=trigger)
    return get(r["id"])


def update(rid: str, **fields) -> None:
    _ensure()
    if "state" in fields:
        fields["state"] = json.dumps(fields["state"])
    if "trigger" in fields:
        fields["trigger"] = json.dumps(fields["trigger"])
    if "enabled" in fields:
        fields["enabled"] = int(bool(fields["enabled"]))
    sets = ", ".join(f"{k}=?" for k in fields)
    with db.connect() as conn:
        conn.execute(f"UPDATE routines SET {sets} WHERE id=?", (*fields.values(), rid))


def remove(rid: str) -> None:
    _ensure()
    with db.connect() as conn:
        conn.execute("DELETE FROM routines WHERE id=?", (rid,))


# ---- triggers ------------------------------------------------------------------------

def describe_trigger(t: dict) -> str:
    kind = t.get("type")
    if kind == "time":
        days = t.get("days") or DAYS
        when = ("every day" if len(days) == 7 else "weekdays" if days == DAYS[:5]
                else "weekends" if days == DAYS[5:] else ", ".join(d.title() for d in days))
        return f"{when} at {t.get('at')}"
    if kind == "interval":
        return f"every {t.get('minutes')} minutes"
    if kind == "once":
        return f"once, {t.get('at', '').replace('T', ' ')}"
    if kind == "email":
        bits = [f"from {t['from']}" if t.get("from") else "", f"about “{t['subject']}”"
                if t.get("subject") else ""]
        return "when an email arrives " + " ".join(b for b in bits if b)
    if kind == "calendar":
        return f"{t.get('minutes_before', 10)} minutes before each calendar event"
    return kind or "?"


def _due_time(r: dict, now: datetime.datetime) -> bool:
    t = r["trigger"]
    hh, mm = (int(x) for x in t.get("at", "08:00").split(":")[:2])
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if DAYS[now.weekday()] not in (t.get("days") or DAYS):
        return False
    # Fire once per day, and not for a time missed long ago (Mac asleep).
    return target <= now < target + datetime.timedelta(minutes=15) \
        and r["last_fired"] < target.timestamp()


def _due_once(r: dict, now: datetime.datetime) -> bool:
    try:
        target = datetime.datetime.fromisoformat(r["trigger"]["at"])
    except (KeyError, ValueError):
        return False
    return now >= target and not r["last_fired"]


async def _check_email(r: dict) -> list[str]:
    st = r["state"]
    if time.time() - st.get("checked", 0) < EMAIL_EVERY:
        return []
    from .memory import people
    from .tools.builtin import mail
    t = r["trigger"]
    sender = t.get("from", "")
    if sender and "@" not in sender:   # "my landlord" -> their address when known
        email, _ = people.resolve_email(sender)
        sender = email or re.sub(r"^(?:my|the)\s+", "", sender, flags=re.I)
    rows = await asyncio.to_thread(mail._list, "inbox", 2, False, sender or t.get("subject", ""))
    st["checked"] = time.time()
    if isinstance(rows, str):
        update(r["id"], state=st)
        return []
    if t.get("subject"):
        rows = [m for m in rows if t["subject"].lower() in m["subject"].lower()]
    seen = set(st.get("seen", []))
    first_look = "seen" not in st
    fresh = [m for m in rows if m["id"] not in seen]
    st["seen"] = sorted(seen | {m["id"] for m in rows})[-300:]
    update(r["id"], state=st)
    if first_look:   # don't announce what was already in the inbox
        return []
    return [f"📧 New email from {m['from']}: “{m['subject']}” (id {m['id']})" for m in fresh]


async def _check_calendar(r: dict) -> list[str]:
    from .tools.builtin import calendars
    st = r["state"]
    lead = int(r["trigger"].get("minutes_before", 10))
    now = datetime.datetime.now()
    try:
        events = await asyncio.to_thread(calendars._eventkit_events, now,
                                         now + datetime.timedelta(minutes=lead + 1)) or []
    except Exception:
        return []
    fired = set(st.get("fired", []))
    out = []
    for ev in events:
        if ev["all_day"] or ev["start"] < now:
            continue
        key = f"{ev['title']}@{ev['start'].isoformat()}"
        if key in fired:
            continue
        fired.add(key)
        mins = max(1, round((ev["start"] - now).total_seconds() / 60))
        where = f" at {ev['location']}" if ev["location"] else ""
        out.append(f"📅 “{ev['title']}” starts in {mins} minute{'s' if mins != 1 else ''}{where}")
    if out:
        st["fired"] = sorted(fired)[-200:]
        update(r["id"], state=st)
    return out


# ---- running & delivering ------------------------------------------------------------

class RoutineSession(channels.ChannelSession):
    """A routine's turn: nobody to ask, so confirm-level tools just run."""
    name = "routine"
    allow_dangerous = False
    auto_approve = True

    async def send_file(self, path: Path, caption: str = "") -> str:
        bot, users = _telegram()
        if not bot:
            return f"No phone is connected; the file is at {path}."
        from .channels.telegram import TelegramSession
        results = [await TelegramSession(bot, u["id"]).send_file(path, caption) for u in users]
        return results[0]


def _telegram():
    try:
        from .channels import telegram
        bot = telegram._bot
        users = telegram.allowed_users()
        if bot is not None and bot.running and users:
            return bot, users
    except Exception:
        pass
    return None, []


def _conversation() -> str:
    for c in db.list_conversations():
        if c.get("title") == "⏰ Routines":
            return c["id"]
    conv = db.create_conversation(title="⏰ Routines")
    try:
        db.rename_conversation(conv["id"], folder="Routines")
    except Exception:
        pass
    return conv["id"]


async def _run_action(r: dict, event: str = "") -> str:
    from .chat import service
    prompt = (f"[Automatic routine “{r['name']}” — {describe_trigger(r['trigger'])}]\n"
              + (f"Trigger: {event}\n" if event else "") + r["action"])
    token = channels.current.set(RoutineSession())
    final = ""
    try:
        async for ev in service.run_chat(_conversation(), prompt):
            if ev["type"] == "done":
                final = ev["content"]
            elif ev["type"] == "error":
                final = f"⚠️ Routine “{r['name']}” failed: {ev['message']}"
    finally:
        channels.current.reset(token)
    return final


def _notify(title: str, text: str) -> None:
    safe = re.sub(r"[`*_#>]", "", text).replace('"', "'").replace("\n", " ")[:220]
    subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "{title}" '
                    f'sound name "Glass"'], capture_output=True, timeout=10)


async def deliver(r: dict, text: str) -> str:
    """Send a routine's result where it should go. Returns where it went."""
    from . import ui_bridge
    title = f"Jarvis — {r['name']}"
    how = r.get("deliver") or "auto"
    bot, users = _telegram()
    went = []
    if how in ("telegram", "auto") and bot:
        for u in users:
            await bot.send_markdown(u["id"], f"*{r['name']}*\n{text}")
        went.append("telegram")
    if how in ("speak", "auto"):
        if await ui_bridge.announce(title, text, speak=True):
            went.append("app")
    if how == "notification" or not went:
        await asyncio.to_thread(_notify, title, text)
        went.append("notification")
    return ", ".join(went)


async def fire(r: dict, events: list[str] | None = None) -> str:
    """Run one routine now (also used by 'run now')."""
    update(r["id"], last_fired=time.time())
    events = events or [""]
    results = []
    for event in events:
        text = await _run_action(r, event) if r["action"] else event
        if text:
            results.append(text)
    if not results:
        return "Nothing to report."
    body = "\n\n".join(results)
    where = await deliver(r, body)
    audit.log("routine_fired", name=r["name"], delivered=where)
    if r["trigger"].get("type") == "once":
        update(r["id"], enabled=False)
    return body


async def tick() -> None:
    now = datetime.datetime.now()
    for r in all_routines():
        if not r["enabled"]:
            continue
        kind = r["trigger"].get("type")
        try:
            if kind == "time" and _due_time(r, now):
                await fire(r)
            elif kind == "once" and _due_once(r, now):
                await fire(r)
            elif kind == "interval" and time.time() - r["last_fired"] >= \
                    max(5, int(r["trigger"].get("minutes", 60))) * 60:
                await fire(r)
            elif kind == "email":
                if events := await _check_email(r):
                    await fire(r, events)
            elif kind == "calendar":
                if events := await _check_calendar(r):
                    await fire(r, events)
        except Exception as e:
            audit.log("routine_error", name=r["name"], error=str(e)[:300])


async def _loop() -> None:
    while True:
        await asyncio.sleep(TICK)
        await tick()


def start() -> None:
    global _task
    if _task is None or _task.done():
        _ensure()
        _task = asyncio.get_running_loop().create_task(_loop())

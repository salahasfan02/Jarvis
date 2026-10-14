"""Two small links between the backend and the Jarvis app on screen.

1. Screen activity: while a tool reads the screen (screenshot, OCR, screen
   memory, watch mode) or controls it (clicking), the state is "reading" /
   "controlling" / "watching". The desktop app polls /api/screen/activity and
   draws a glowing frame around every display, so the user always knows.

2. UI requests: a tool can ask the open Jarvis window to do something only it
   can — e.g. take a camera photo (the window has camera permission; the
   backend process doesn't) — and wait for the answer over the chat socket.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager

# ---- screen activity --------------------------------------------------------

LABELS = {
    "controlling": "Jarvis is controlling your screen — press Esc to stop",
    "reading": "Jarvis is reading your screen",
    "watching": "Jarvis is watching your screen",
}
SHOW_DELAY = 0.35   # let the frame appear before the screen is captured
HOLD = 1.2          # keep it up briefly so a quick read is still noticed

_lock = threading.Lock()
_active = {"controlling": 0, "reading": 0}
_hold_until = {"controlling": 0.0, "reading": 0.0}
_watching = 0


def _begin(mode: str) -> bool:
    with _lock:
        idle = current()["mode"] is None
        _active[mode] += 1
        return idle


def _end(mode: str) -> None:
    with _lock:
        _active[mode] = max(0, _active[mode] - 1)
        _hold_until[mode] = time.time() + HOLD


def current() -> dict:
    now = time.time()
    for mode in ("controlling", "reading"):
        if _active[mode] or _hold_until[mode] > now:
            return {"mode": mode, "label": LABELS[mode]}
    if _watching:
        return {"mode": "watching", "label": LABELS["watching"]}
    return {"mode": None, "label": ""}


@contextmanager
def screen_activity_sync(mode: str):
    """For blocking code (threads)."""
    if _begin(mode):
        time.sleep(SHOW_DELAY)
    try:
        yield
    finally:
        _end(mode)


@asynccontextmanager
async def screen_activity(mode: str):
    if _begin(mode):
        await asyncio.sleep(SHOW_DELAY)
    try:
        yield
    finally:
        _end(mode)


def set_watching(count: int) -> None:
    """Number of running screen watches (shown as a steady frame)."""
    global _watching
    _watching = max(0, count)


def is_overlay_text(line: str) -> bool:
    """The frame's own label must never be read back as screen content."""
    return line.strip() in LABELS.values()


# ---- emergency stop -----------------------------------------------------------
# Esc (while the frame is up) or "Jarvis stop" halts all screen control: the
# running chat turn is cancelled, and control tools refuse for a few seconds
# so a model mid-plan can't carry on clicking.

_abort_until = 0.0
_tasks: set = set()


def stop_control(reason: str = "Esc") -> int:
    """Cancel every running turn and block screen control briefly."""
    global _abort_until
    _abort_until = time.time() + 5
    cancelled = 0
    for task in list(_tasks):
        if not task.done():
            task.cancel()
            cancelled += 1
    from .security import audit
    audit.log("screen_control_stopped", reason=reason, cancelled=cancelled)
    return cancelled


def control_blocked() -> bool:
    return time.time() < _abort_until


def track(task) -> None:
    """Register a running chat turn so stop_control can cancel it."""
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ---- UI requests --------------------------------------------------------------

_sockets: list = []
_pending: dict[str, asyncio.Future] = {}


def register(ws) -> None:
    _sockets.append(ws)


def unregister(ws) -> None:
    if ws in _sockets:
        _sockets.remove(ws)


def ui_connected() -> bool:
    return bool(_sockets)


async def request(kind: str, payload: dict | None = None, timeout: float = 20) -> dict:
    """Ask the most recently opened Jarvis window to do `kind`. Returns its
    reply, or {"error": ...} when no window is open or it doesn't answer."""
    if not _sockets:
        return {"error": "no_ui"}
    rid = uuid.uuid4().hex
    future = asyncio.get_running_loop().create_future()
    _pending[rid] = future
    try:
        await _sockets[-1].send_json({"type": "ui_request", "id": rid, "kind": kind,
                                      **(payload or {})})
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        return {"error": "The Jarvis window didn't answer in time."}
    except Exception as e:
        return {"error": str(e)}
    finally:
        _pending.pop(rid, None)


async def announce(title: str, text: str, speak: bool = True,
                   action: dict | None = None, conversation_id: str | None = None) -> bool:
    """Show (and speak) a message in every open Jarvis window — routines,
    triggers, offers of help. `action` ({label, prompt}) adds a button that
    sends `prompt` as a request; `conversation_id` names a chat that just got
    a new message (an open window reloads it). Returns whether any window got it."""
    sent = False
    for ws in list(_sockets):
        try:
            await ws.send_json({"type": "announce", "title": title, "text": text,
                                "speak": speak, "action": action,
                                "conversation_id": conversation_id})
            sent = True
        except Exception:
            unregister(ws)
    return sent


def resolve(rid: str, data: dict | None) -> None:
    future = _pending.get(rid)
    if future and not future.done():
        future.set_result(data or {})

"""Screen watch mode.

Periodically OCRs the screen and asks the LLM whether a user-described
condition is now true (e.g. "the download finished", "the build turned
green"). When it triggers, it fires a macOS notification + sound and stops.
Runs entirely in the background so chat is unaffected.
"""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..llm import ollama_client
from ..security import audit


@dataclass
class Watch:
    id: str
    condition: str
    interval: int
    started: float = field(default_factory=time.time)
    checks: int = 0
    status: str = "watching"     # watching | triggered | stopped | timed_out
    last_seen: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)


_watches: dict[str, Watch] = {}
_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"met": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["met"],
}


async def _capture_text() -> str:
    from .. import ui_bridge
    async with ui_bridge.screen_activity("reading"):
        return await _capture_text_now()


async def _capture_text_now() -> str:
    path = Path(tempfile.mkstemp(suffix=".png")[1])
    try:
        proc = await asyncio.create_subprocess_exec("screencapture", "-x", str(path))
        await proc.wait()
        if not path.exists() or path.stat().st_size == 0:
            return ""
        from . import ocr
        return await ocr.ocr_file(path)
    finally:
        path.unlink(missing_ok=True)


def _notify(title: str, message: str) -> None:
    safe = message.replace('"', "'")[:200]
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{safe}" with title "{title}" sound name "Glass"'],
        capture_output=True, timeout=10)


def _sync_frame() -> None:
    """A running watch keeps a steady frame on screen."""
    from .. import ui_bridge
    ui_bridge.set_watching(sum(w.status == "watching" for w in _watches.values()))


async def _run(watch: Watch, max_minutes: int = 30) -> None:
    deadline = watch.started + max_minutes * 60
    await asyncio.sleep(0)   # start() registers the watch first
    _sync_frame()
    try:
        while watch.status == "watching" and time.time() < deadline:
            await asyncio.sleep(watch.interval)
            if watch.status != "watching":
                break
            text = await _capture_text()
            watch.checks += 1
            watch.last_seen = text[:400]
            if not text.strip():
                continue
            try:
                raw = await ollama_client.chat_once([
                    {"role": "system", "content":
                        "You watch a user's screen. Given the current on-screen text, "
                        "decide if this condition is now TRUE. Be conservative — only "
                        "true when clearly satisfied."},
                    {"role": "user", "content":
                        f"CONDITION: {watch.condition}\n\nCURRENT SCREEN TEXT:\n{text[:3500]}"},
                ], model=ollama_client.model_for("utility"), format=_JUDGE_SCHEMA)
                import json
                verdict = json.loads(raw)
            except Exception:
                continue
            if verdict.get("met"):
                watch.status = "triggered"
                msg = verdict.get("reason") or watch.condition
                _notify("Jarvis — screen watch", msg)
                audit.log("screen_watch_triggered", condition=watch.condition, reason=msg)
                return
        if watch.status == "watching":
            watch.status = "timed_out"
    except asyncio.CancelledError:
        watch.status = "stopped"
        raise
    finally:
        _sync_frame()


def start(condition: str, interval: int = 15) -> Watch:
    import uuid
    watch = Watch(id=uuid.uuid4().hex[:8], condition=condition,
                  interval=max(5, min(interval, 120)))
    watch.task = asyncio.get_event_loop().create_task(_run(watch))
    _watches[watch.id] = watch
    audit.log("screen_watch_started", id=watch.id, condition=condition)
    return watch


def stop(watch_id: str = "") -> int:
    stopped = 0
    for w in list(_watches.values()):
        if (not watch_id or w.id == watch_id) and w.status == "watching":
            w.status = "stopped"
            if w.task:
                w.task.cancel()
            stopped += 1
    return stopped


def active() -> list[dict]:
    return [{"id": w.id, "condition": w.condition, "status": w.status,
             "checks": w.checks, "interval": w.interval}
            for w in _watches.values()]

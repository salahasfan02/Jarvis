"""Screen memory / activity journal.

Periodically captures the screen, OCRs it, asks the utility model to summarize
what the user is doing in one line, and saves that to long-term memory
(category "activity"). Deduplicated so an unchanged screen isn't logged twice.

Privacy: OFF by default. The user starts it explicitly (voice/chat tool or the
Settings toggle). Everything stays local; captures are never stored, only the
one-line summary. Stop any time.
"""
from __future__ import annotations

import asyncio
import re
import time

from ..config import settings
from ..llm import ollama_client
from ..security import audit

_task: asyncio.Task | None = None
_state = {"running": False, "started": 0.0, "captures": 0, "saved": 0,
          "last_summary": "", "interval": 300}


def _norm(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def _similar(a: str, b: str) -> float:
    wa, wb = _norm(a), _norm(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


async def _capture_and_summarize() -> str | None:
    from . import watcher
    text = await watcher._capture_text()
    # Stuck on the same error for a while? (every capture, before the
    # "screen barely changed" skip below — being stuck IS an unchanged screen)
    try:
        from . import proactive
        proactive.observe(text)
    except Exception:
        pass
    if len(text.strip()) < 40:
        return None
    # skip if the screen barely changed since the last capture
    if _state["last_capture_text"] and _similar(text, _state["last_capture_text"]) > 0.8:
        return None
    _state["last_capture_text"] = text
    try:
        summary = await ollama_client.chat_once([
            {"role": "system", "content":
                "You summarize what a user is doing from their screen's text. Reply "
                "with ONE concise sentence starting with 'The user', capturing the app, "
                "task or content. If the screen is blank, a desktop, or has nothing "
                "meaningful, reply with exactly 'SKIP'."},
            {"role": "user", "content": "Screen text:\n" + text[:3500]},
        ], model=ollama_client.model_for("utility"))
    except Exception:
        return None
    summary = summary.strip().strip('"')
    if not summary or summary.upper().startswith("SKIP") or len(summary) < 12:
        return None
    # don't log the same activity twice in a row
    if _similar(summary, _state["last_summary"]) > 0.6:
        return None
    return summary


async def _loop() -> None:
    from ..memory import store as memory_store
    while _state["running"]:
        try:
            _state["captures"] += 1
            summary = await _capture_and_summarize()
            if summary:
                stamp = time.strftime("%Y-%m-%d %H:%M")
                await memory_store.save(f"[{stamp}] {summary}", "activity")
                _state["last_summary"] = summary
                _state["saved"] += 1
                audit.log("screen_memory_saved", summary=summary)
        except Exception as e:
            audit.log("screen_memory_error", error=str(e))
        await asyncio.sleep(max(30, _state["interval"]))


def start(interval_seconds: int | None = None) -> dict:
    """Must be called from within the running event loop (async route, tool
    handler, or lifespan) so the background task actually gets scheduled."""
    global _task
    if interval_seconds:
        _state["interval"] = max(30, interval_seconds)
    else:
        _state["interval"] = settings.get("screen_memory.interval_seconds", 300)
    if _state["running"]:
        return status()
    _state.update(running=True, started=time.time(), captures=0, saved=0,
                  last_summary="", last_capture_text="")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    _task = loop.create_task(_loop())
    audit.log("screen_memory_started", interval=_state["interval"])
    return status()


def stop() -> dict:
    global _task
    _state["running"] = False
    if _task:
        _task.cancel()
        _task = None
    audit.log("screen_memory_stopped", saved=_state["saved"])
    return status()


def status() -> dict:
    return {"running": _state["running"], "captures": _state["captures"],
            "saved": _state["saved"], "interval": _state["interval"],
            "last_summary": _state["last_summary"]}


# initialize the extra key used above
_state["last_capture_text"] = ""

"""Warm-up: load the slow-to-start pieces in the background, before they're needed.

Cold, the first command after launching Jarvis waited for the chat model to
load into memory (several seconds for a 14B model), the first voice command
for Whisper, and the first spoken reply for Kokoro. Loading them right after
startup — and again whenever the model is changed in Settings — moves that
wait to a moment nobody is waiting.
"""
from __future__ import annotations

import asyncio

from .config import settings
from .llm import ollama_client
from .security import audit

_task: asyncio.Task | None = None


async def _models() -> None:
    if not await ollama_client.is_up():
        return
    chat = settings.get("ollama.model")
    await ollama_client.preload(chat)
    utility = ollama_client.model_for("utility")
    if utility != chat:
        await ollama_client.preload(utility)
    if settings.get("ollama.embedding_model"):
        await ollama_client.embed("warm up")


async def _whisper() -> None:
    from .speech import stt
    if settings.get("voice.stt_engine", "whisper") == "whisper" and stt.model_present():
        await asyncio.to_thread(stt._load, stt.configured_size())


async def _kokoro() -> None:
    from .speech import engines
    engine = engines.ENGINES.get("kokoro")
    if settings.get("voice.tts_engine", "kokoro") == "kokoro" and engine and engine.available():
        await asyncio.to_thread(engine._load)  # type: ignore[attr-defined]


async def warm_up() -> None:
    results = await asyncio.gather(_models(), _whisper(), _kokoro(), return_exceptions=True)
    errors = [str(r) for r in results if isinstance(r, Exception)]
    audit.log("warm_up", errors=errors)


def schedule() -> None:
    """Start a warm-up unless one is already running (never blocks the caller)."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(warm_up())


# Settings that change which models are in play.
WARM_KEYS = {("ollama", "model"), ("ollama", "embedding_model"), ("ollama", "task_models"),
             ("voice", "whisper_model"), ("voice", "stt_engine"), ("voice", "tts_engine")}


def affected_by(patch: dict) -> bool:
    return any(section in patch and isinstance(patch[section], dict) and key in patch[section]
               for section, key in WARM_KEYS)

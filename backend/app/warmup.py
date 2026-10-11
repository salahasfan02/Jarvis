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


PREFERRED = ("qwen2.5", "qwen3", "llama3.1", "llama3.2", "llama3", "mistral", "gemma")


def pick_installed(configured: str, installed: list[str]) -> str | None:
    """If the configured chat model isn't installed (the default is llama3.1,
    the README suggests qwen2.5:14b), choose one that is — a tool-capable
    family first, never an embedding model. None = keep the configured one."""
    names = [n for n in installed if "embed" not in n.lower()]
    if not names or any(n == configured or n.split(":")[0] == configured for n in names):
        return None
    for family in PREFERRED:
        for n in names:
            if n.startswith(family):
                return n
    return names[0]


async def _models() -> None:
    if not await ollama_client.is_up():
        return
    try:
        installed = [m.get("name", "") for m in await ollama_client.list_models()]
    except Exception:
        installed = []
    if pick := pick_installed(settings.get("ollama.model", ""), installed):
        audit.log("model_auto_selected", was=settings.get("ollama.model"), now=pick)
        settings.update({"ollama": {"model": pick}})
    chat = settings.get("ollama.model")
    await ollama_client.preload(chat)
    utility = ollama_client.model_for("utility")
    if utility != chat:
        await ollama_client.preload(utility)
    if settings.get("ollama.embedding_model"):
        await ollama_client.embed("warm up")
    # Read the prompt opening every request shares, so even the first command
    # after launch only pays for its own words.
    from .chat import prefetch
    await prefetch.warm_opening()


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

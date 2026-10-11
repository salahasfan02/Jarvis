"""Warm the model up the moment the wake word is heard.

Most of a reply's wait is the model reading its prompt. Every request opens
the same way (base system prompt + core tools, see toolpick.CORE), followed by
the conversation so far, so that part can be read before the user has even
finished speaking. If it is already cached (the usual case) this costs ~0.1 s;
if something else pushed it out of Ollama's cache, the reading starts now
instead of after the user's sentence.

The real turn waits for a warm-up still in flight: sent alongside it, the
request would get its own empty cache slot and the two would share the GPU.
"""
from __future__ import annotations

import asyncio
import time

from .. import db
from ..agents import registry as agents
from ..llm import ollama_client

FRESH_FOR = 60
_state: dict[str, dict] = {}


def _key(conversation_id: str | None) -> str:
    return conversation_id or "new"


async def warm(conversation_id: str | None, text: str = "") -> dict:
    from . import service, toolpick
    conv = (db.get_conversation(conversation_id) or {}) if conversation_id else {}
    history = db.get_messages(conversation_id) if conversation_id else []
    agent = agents.AGENTS["coding" if conv.get("mode") == "code" else "general"]
    # The opening every request shares, plus this conversation's history.
    history = [*history, {"role": "user", "content": text or "…", "meta": {}}]
    messages, _ = await service.assemble(conversation_id or "", conv, agent, history,
                                         text or "…", [], {})
    core = toolpick.arrange([])
    key = _key(conversation_id)
    old = _state.get(key)
    if old and not old["task"].done():
        return {"warming": True}
    task = asyncio.create_task(ollama_client.prefill(
        messages, [t.to_ollama() for t in core] or None,
        ollama_client.model_for(agent.model_task)))
    _state[key] = {"task": task, "at": time.time()}
    return {"warming": True, "core_tools": len(core)}


async def claim(conversation_id: str) -> None:
    """Let a warm-up for this conversation finish before the real request."""
    st = _state.pop(_key(conversation_id), None) or _state.pop("new", None)
    if st is None or time.time() - st["at"] > FRESH_FOR or st["task"].done():
        return
    try:
        await asyncio.wait_for(asyncio.shield(st["task"]), timeout=60)
    except Exception:
        pass


async def warm_opening() -> dict:
    """At startup: read the shared opening once so the first request is fast."""
    return await warm(None, "")

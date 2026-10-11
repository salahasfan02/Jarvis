"""Async client for the Ollama HTTP API.

Model-agnostic by design: every call takes the model name from settings at
call time, so switching models in the settings page takes effect on the next
message without restarting anything.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, AsyncIterator

import httpx

from ..config import settings


class OllamaError(RuntimeError):
    pass


def _host() -> str:
    return settings.get("ollama.host", "http://localhost:11434").rstrip("/")


def model_for(task: str | None = None) -> str:
    """Resolve the model for a task ('coding', 'utility', ...); falls back to
    the main chat model when no override is configured."""
    if task:
        override = settings.get(f"ollama.task_models.{task}", "")
        if override:
            return override
    return settings.get("ollama.model")


async def benchmark(model: str) -> dict:
    """One-shot performance measurement using Ollama's own timing metrics."""
    payload = {
        "model": model,
        "messages": [{"role": "user",
                      "content": "Write exactly two sentences about the ocean."}],
        "stream": False,
        "options": {"num_ctx": 4096},
        "keep_alive": settings.get("ollama.keep_alive", "30m"),
    }
    async with httpx.AsyncClient(timeout=600) as client:
        r = await client.post(f"{_host()}/api/chat", json=payload)
        r.raise_for_status()
        d = r.json()
    ns = 1e9
    prompt_tps = (d.get("prompt_eval_count", 0) /
                  (d.get("prompt_eval_duration", 1) / ns)) if d.get("prompt_eval_duration") else 0
    gen_tps = (d.get("eval_count", 0) /
               (d.get("eval_duration", 1) / ns)) if d.get("eval_duration") else 0
    return {
        "model": model,
        "load_seconds": round(d.get("load_duration", 0) / ns, 2),
        "prompt_tokens_per_s": round(prompt_tps),
        "generate_tokens_per_s": round(gen_tps, 1),
        "total_seconds": round(d.get("total_duration", 0) / ns, 2),
    }


def _keep_alive(model: str | None) -> str:
    """How long a model stays loaded after a call. The vision model (6-7 GB) is
    only needed for camera/screen questions: unloading it after 2 minutes keeps
    a 24 GB Mac out of memory pressure (Ollama was being killed with the chat,
    vision and utility models all resident)."""
    vision = settings.get("ollama.vision_model", "")
    if model and vision and model == vision and vision != settings.get("ollama.model"):
        return settings.get("ollama.vision_keep_alive", "2m")
    return settings.get("ollama.keep_alive", "5m")


def _options(tools: bool = False) -> dict[str, Any]:
    temperature = settings.get("ollama.temperature", 0.7)
    if tools:
        # Picking a tool and its arguments should be steady, not creative: at
        # 0.7 the same request sometimes acted and sometimes asked a question.
        temperature = min(temperature, settings.get("ollama.tool_temperature", 0.2))
    opts: dict[str, Any] = {
        "temperature": temperature,
        "num_ctx": settings.get("ollama.num_ctx", 8192),
    }
    num_gpu = settings.get("ollama.num_gpu", -1)
    if num_gpu is not None and num_gpu >= 0:
        opts["num_gpu"] = num_gpu
    return opts


async def is_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{_host()}/api/version")
            return r.status_code == 200
    except httpx.HTTPError:
        return False


async def list_models() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{_host()}/api/tags")
        r.raise_for_status()
        return r.json().get("models", [])


async def delete_model(name: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request("DELETE", f"{_host()}/api/delete", json={"model": name})
        r.raise_for_status()


async def pull_model(name: str) -> AsyncIterator[dict]:
    """Stream pull progress events."""
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{_host()}/api/pull",
                                 json={"model": name}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.strip():
                    yield json.loads(line)


async def chat_stream(messages: list[dict], model: str | None = None,
                      tools: list[dict] | None = None) -> AsyncIterator[dict]:
    """Stream chat chunks. Yields the raw Ollama chunk dicts.

    Text chunks arrive as {"message": {"content": "..."}}; tool calls arrive
    as {"message": {"tool_calls": [...]}} (Ollama emits those non-streamed).
    """
    payload: dict[str, Any] = {
        "model": model or settings.get("ollama.model"),
        "messages": messages,
        "stream": True,
        "options": _options(tools=bool(tools)),
        "keep_alive": _keep_alive(model),
        # Thinking models (qwen3.5…) would reason for many seconds before every
        # reply; an assistant answering commands doesn't need that.
        "think": bool(settings.get("ollama.think", False)),
    }
    if tools:
        payload["tools"] = tools
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{_host()}/api/chat", json=payload) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="replace")
                    raise OllamaError(f"Ollama returned {r.status_code}: {body[:500]}")
                async for line in r.aiter_lines():
                    if line.strip():
                        yield json.loads(line)
    except httpx.ConnectError as e:
        raise OllamaError(
            f"Cannot reach Ollama at {_host()}. Is `ollama serve` running?") from e


async def prefill(messages: list[dict], tools: list[dict] | None = None,
                  model: str | None = None) -> dict:
    """Have Ollama read a prompt (and cache it) without really answering:
    the next request sharing this prefix only processes what's new. Same
    options as chat_stream — a different num_ctx would reload the model."""
    payload: dict[str, Any] = {
        "model": model or settings.get("ollama.model"),
        "messages": messages,
        "stream": False,
        "options": {**_options(tools=bool(tools)), "num_predict": 1},
        "keep_alive": _keep_alive(model),
        "think": bool(settings.get("ollama.think", False)),
    }
    if tools:
        payload["tools"] = tools
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{_host()}/api/chat", json=payload)
            data = r.json()
            return {"prompt_tokens": data.get("prompt_eval_count", 0),
                    "seconds": round(data.get("prompt_eval_duration", 0) / 1e9, 2)}
    except (httpx.HTTPError, ValueError) as e:
        return {"error": str(e)}


async def chat_once(messages: list[dict], model: str | None = None,
                    format: str | dict | None = None) -> str:
    """Non-streamed helper for internal calls (titles, self-analysis...).
    Pass format="json" (or a JSON schema dict) to force structured output."""
    payload: dict[str, Any] = {
        "model": model or settings.get("ollama.model"),
        "messages": messages,
        "stream": False,
        "options": _options(),
        "keep_alive": _keep_alive(model),
        # Thinking models (qwen3.5…) would reason for many seconds before every
        # reply; an assistant answering commands doesn't need that.
        "think": bool(settings.get("ollama.think", False)),
    }
    if format:
        payload["format"] = format
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{_host()}/api/chat", json=payload)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")


async def loaded_models() -> list[dict]:
    """Models currently loaded in memory (name, size, VRAM usage)."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{_host()}/api/ps")
            r.raise_for_status()
            return r.json().get("models", [])
    except httpx.HTTPError:
        return []


_embed_cache: "OrderedDict[tuple[str, str], list[float]]" = OrderedDict()


async def embed(text: str) -> list[float] | None:
    """Embed text with the configured embedding model, or None if unset.
    Cached: memory recall and agent routing embed the same message."""
    model = settings.get("ollama.embedding_model", "")
    if not model:
        return None
    key = (model, text)
    if key in _embed_cache:
        _embed_cache.move_to_end(key)
        return _embed_cache[key]
    vector = await _embed_uncached(model, text)
    if vector:
        _embed_cache[key] = vector
        while len(_embed_cache) > 512:
            _embed_cache.popitem(last=False)
    return vector


async def preload(model: str) -> None:
    """Load a model into memory now (an empty request does that), so the first
    real message doesn't wait several seconds for it to load from disk."""
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{_host()}/api/generate", json={
            "model": model, "keep_alive": settings.get("ollama.keep_alive", "30m")})
        r.raise_for_status()


async def embed_many(texts: list[str]) -> list[list[float]] | None:
    """Embed many texts in one request (not cached — for one-off passages)."""
    model = settings.get("ollama.embedding_model", "")
    if not model or not texts:
        return None
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{_host()}/api/embed", json={"model": model, "input": texts})
            r.raise_for_status()
            vectors = r.json().get("embeddings", [])
            return vectors if len(vectors) == len(texts) else None
    except httpx.HTTPError:
        return None


async def _embed_uncached(model: str, text: str) -> list[float] | None:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{_host()}/api/embed",
                                  json={"model": model, "input": text})
            r.raise_for_status()
            embeddings = r.json().get("embeddings", [])
            return embeddings[0] if embeddings else None
    except httpx.HTTPError:
        return None

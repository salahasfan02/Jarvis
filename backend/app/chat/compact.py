"""Keep long conversations inside the model's memory.

The model sees num_ctx tokens (8192 by default). The shared prompt opening —
base prompt + core tools — takes ~4,600 of them, and the reply needs room, so
the conversation itself gets what's left. Past that, Ollama would cut the
prompt and the model would silently forget things (or the tools themselves).

So once a conversation grows long, its older turns are replaced by a short
summary written by the small utility model. That happens in the background
right after a reply (nobody waits for it), and the summary only changes when
another chunk is folded in, so the cached prompt stays mostly stable. If a
turn arrives before the summary has caught up, the oldest turns are dropped
for that turn as a fallback.
"""
from __future__ import annotations

import asyncio
import json

from .. import db
from ..config import settings
from ..llm import ollama_client
from ..security import audit

CHARS_PER_TOKEN = 3.5
OPENING_TOKENS = 4600      # base prompt + core tools + a few extras (measured)
REPLY_RESERVE = 1200
SUMMARY_WORDS = 160

_running: set[str] = set()


def budget() -> int:
    """Tokens the conversation (history + this message) may use."""
    return max(1500, int(settings.get("ollama.num_ctx", 8192)) - OPENING_TOKENS - REPLY_RESERVE)


def _tokens(rows: list[dict]) -> int:
    chars = 0
    for m in rows:
        chars += len(m.get("content") or "") + 16
        for c in (m.get("meta") or {}).get("tools") or []:
            chars += min(len(c.get("result") or ""), 800) + len(json.dumps(c.get("arguments") or {}))
    return int(chars / CHARS_PER_TOKEN)


def _cut(rows: list[dict], target: int) -> int:
    """Index from which the newest rows fit in `target` tokens, starting at a
    user message (never mid-exchange). Always keeps at least the last row."""
    keep = len(rows) - 1
    for i in range(len(rows) - 1, -1, -1):
        if _tokens(rows[i:]) > target:
            break
        if rows[i]["role"] == "user":
            keep = i
    return keep


def fit(conv: dict, history: list[dict]) -> list[dict]:
    """The stored history this turn should show the model: the summary of
    older turns (if any), then the recent turns that fit."""
    upto = int(conv.get("summary_upto") or 0)
    summary = conv.get("summary") or ""
    rows = history[upto:] if 0 < upto < len(history) else history
    if not (0 < upto < len(history)):
        summary = ""
    room = budget() - (len(summary) // int(CHARS_PER_TOKEN) + 20)
    if _tokens(rows) > room:
        rows = rows[_cut(rows, room):]   # summary not caught up yet: drop the oldest
    if summary:
        return [{"role": "user", "content": f"[Earlier in this conversation — summary]\n{summary}",
                 "meta": {}},
                {"role": "assistant", "content": "Understood.", "meta": {}}, *rows]
    return rows


def _transcript(rows: list[dict]) -> str:
    out = []
    for m in rows:
        line = f"{m['role'].upper()}: {(m.get('content') or '')[:1500]}"
        for c in (m.get("meta") or {}).get("tools") or []:
            line += f"\n  [tool {c.get('name')} {json.dumps(c.get('arguments') or {})[:200]} -> " \
                    f"{(c.get('result') or '')[:300]}]"
        out.append(line)
    return "\n".join(out)


async def _summarize(conversation_id: str) -> None:
    conv = db.get_conversation(conversation_id) or {}
    history = db.get_messages(conversation_id)
    upto = int(conv.get("summary_upto") or 0)
    rows = history[upto:]
    if _tokens(rows) <= budget() * 0.75:
        return
    # Fold everything except the newest ~half of the budget into the summary.
    cut = upto + _cut(rows, int(budget() * 0.45))
    if cut <= upto:
        return
    old = conv.get("summary") or ""
    prompt = (f"Update the running summary of a conversation between a user and their "
              f"assistant Jarvis. Keep every concrete detail that might matter later: "
              f"names, email addresses, file paths, ids, decisions, what was done, and what "
              f"is still pending. At most {SUMMARY_WORDS} words, plain sentences.\n\n"
              f"SUMMARY SO FAR:\n{old or '(none)'}\n\nNEW TURNS TO FOLD IN:\n"
              f"{_transcript(history[upto:cut])}")
    text = (await ollama_client.chat_once([{"role": "user", "content": prompt}],
                                          model=ollama_client.model_for("utility")) or "").strip()
    if text:
        db.set_summary(conversation_id, text[:2000], cut)
        audit.log("conversation_compacted", conversation=conversation_id, upto=cut,
                  chars=len(text))


def schedule(conversation_id: str) -> None:
    """After a reply: fold older turns into the summary if it's getting long."""
    if conversation_id in _running:
        return

    async def run():
        _running.add(conversation_id)
        try:
            await _summarize(conversation_id)
        except Exception as e:
            audit.log("compaction_failed", error=str(e)[:200])
        finally:
            _running.discard(conversation_id)
    try:
        asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        pass

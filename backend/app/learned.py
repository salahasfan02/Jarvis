"""Learning from real mistakes.

When a turn went wrong in a way Jarvis can see — the model claimed results it
never looked up, stalled instead of acting, wrote a tool call as text, didn't
create a file it was asked for — or the user says "that's wrong", the request
is kept as a candidate test case. On the Developer page the user says which
tool should have run; it is then saved to ~/.jarvis/evals/learned.json, which
the eval suite (backend/evals) replays alongside its built-in cases.
"""
from __future__ import annotations

import json
import re
import time
import uuid

from . import db
from .config import JARVIS_HOME

LEARNED_FILE = JARVIS_HOME / "evals" / "learned.json"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS learned (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    say TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT '',
    calls TEXT NOT NULL DEFAULT '[]',
    reply TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new'
);
"""
_ready = False

# "no, that's wrong" / "that's not what I asked" about the previous answer.
SAYS_WRONG = re.compile(
    r"^\s*(?:no+[,.!]?\s*)?(?:that'?s|that is|this is|it'?s)\s+(?:wrong|not (?:right|what i "
    r"(?:asked|meant|wanted)))|^\s*wrong (?:file|one|person|tab|email)\b"
    r"|^\s*(?:no+[,.!]?\s*)?not what i (?:asked|meant|wanted)", re.I)


def _ensure() -> None:
    global _ready
    if not _ready:
        with db.connect() as conn:
            conn.executescript(_SCHEMA)
        _ready = True


def add(say: str, agent: str, calls: list[dict], reply: str, reason: str) -> None:
    _ensure()
    with db.connect() as conn:
        # One candidate per request text: the newest attempt replaces older ones.
        conn.execute("DELETE FROM learned WHERE say=? AND status='new'", (say,))
        conn.execute("INSERT INTO learned VALUES (?, ?, ?, ?, ?, ?, ?, 'new')",
                     (uuid.uuid4().hex[:10], time.time(), say[:500], agent,
                      json.dumps([{"name": c.get("name"), "arguments": c.get("arguments")}
                                  for c in calls])[:3000], reply[:1500], reason))


def note_turn(conversation_id: str, user_content: str, agent: str, tool_events: list[dict],
              reply: str, reasons: list[str]) -> None:
    """Called at the end of every turn."""
    if reasons:
        add(user_content, agent, tool_events, reply, ", ".join(dict.fromkeys(reasons)))
    if SAYS_WRONG.search(user_content):
        # The PREVIOUS exchange was wrong: keep that request.
        history = db.get_messages(conversation_id)
        users = [m for m in history if m["role"] == "user"]
        replies = [m for m in history if m["role"] == "assistant"]
        if len(users) >= 2 and len(replies) >= 2:
            prev, prev_reply = users[-2], replies[-2]
            add(prev["content"], (prev_reply.get("meta") or {}).get("agent", ""),
                (prev_reply.get("meta") or {}).get("tools") or [], prev_reply["content"],
                "user said it was wrong")


def candidates() -> list[dict]:
    _ensure()
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM learned WHERE status='new' ORDER BY ts DESC LIMIT 100")
        out = [dict(r) for r in rows]
    for r in out:
        r["calls"] = json.loads(r["calls"] or "[]")
    return out


def saved_cases() -> list[dict]:
    try:
        return json.loads(LEARNED_FILE.read_text())
    except (OSError, ValueError):
        return []


def resolve(cid: str, expected: list[str] | None) -> dict:
    """expected = tool names that should run ([] = answer without tools);
    None = dismiss the candidate."""
    _ensure()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM learned WHERE id=?", (cid,)).fetchone()
        if row is None:
            return {"error": "no such candidate"}
        conn.execute("UPDATE learned SET status=? WHERE id=?",
                     ("dismissed" if expected is None else "saved", cid))
    if expected is None:
        return {"ok": True}
    case: dict = {"say": row["say"], "learned": True}
    if expected:
        case["tools"] = expected
    else:
        case["no_tools"] = True
    cases = [c for c in saved_cases() if c.get("say") != row["say"]] + [case]
    LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEARNED_FILE.write_text(json.dumps(cases, indent=1))
    return {"ok": True, "saved": len(cases)}

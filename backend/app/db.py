"""SQLite persistence for conversations, messages and long-term memories."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .config import DB_FILE

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'New conversation',
    folder TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS capability_gaps (
    id TEXT PRIMARY KEY,
    capability TEXT NOT NULL,
    user_prompt TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    technical_limitation TEXT NOT NULL DEFAULT '',
    missing_tool TEXT NOT NULL DEFAULT '',
    missing_integration TEXT NOT NULL DEFAULT '',
    missing_permission TEXT NOT NULL DEFAULT '',
    missing_ai_capability TEXT NOT NULL DEFAULT '',
    suggested_fix TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'open',
    count INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    template TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'file',
    content_text TEXT NOT NULL DEFAULT '',
    image_b64 TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attach_conv ON attachments(conversation_id);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS doc_chunks (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON doc_chunks(doc_id, seq);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    embedding TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        # migrations for pre-existing databases
        try:
            conn.execute("ALTER TABLE conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat'")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")
        except sqlite3.OperationalError:
            pass
        for column in ("summary TEXT NOT NULL DEFAULT ''",
                       "summary_upto INTEGER NOT NULL DEFAULT 0"):
            try:   # long conversations: older turns folded into a summary
                conn.execute(f"ALTER TABLE conversations ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass


# --- conversations -----------------------------------------------------------

def create_conversation(title: str = "New conversation", mode: str = "chat") -> dict:
    now = time.time()
    conv = {"id": uuid.uuid4().hex, "title": title, "folder": "", "mode": mode,
            "created_at": now, "updated_at": now}
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, folder, mode, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (conv["id"], conv["title"], conv["folder"], mode, now, now))
    return conv


def set_conversation_mode(conv_id: str, mode: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE conversations SET mode=? WHERE id=?", (mode, conv_id))


def get_conversation(conv_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
    return dict(row) if row else None


# --- custom skills (saved prompt templates) ------------------------------------

def create_skill(name: str, template: str, description: str = "") -> dict:
    now = time.time()
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "skill"
    skill = {"id": uuid.uuid4().hex, "name": slug, "description": description,
             "template": template, "created_at": now}
    with connect() as conn:
        conn.execute(
            "INSERT INTO skills (id, name, description, template, created_at) VALUES (?,?,?,?,?)",
            (skill["id"], slug, description, template, now))
    return skill


def list_skills() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM skills ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def update_skill(skill_id: str, fields: dict) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("name", "description", "template")}
    if "name" in allowed:
        allowed["name"] = re.sub(r"[^a-z0-9]+", "-", allowed["name"].lower()).strip("-")
    if not allowed:
        return
    with connect() as conn:
        conn.execute(
            f"UPDATE skills SET {', '.join(f'{k}=?' for k in allowed)} WHERE id=?",
            (*allowed.values(), skill_id))


def delete_skill(skill_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))


# --- projects ------------------------------------------------------------------

def create_project(name: str, description: str = "") -> dict:
    now = time.time()
    proj = {"id": uuid.uuid4().hex, "name": name, "description": description,
            "notes": "", "created_at": now, "updated_at": now}
    with connect() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, description, notes, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (proj["id"], name, description, "", now, now))
    return proj


def list_projects() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_project(proj_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (proj_id,)).fetchone()
    return dict(row) if row else None


def find_project_by_name(name: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE LOWER(name)=LOWER(?)", (name,)).fetchone()
    return dict(row) if row else None


def update_project(proj_id: str, fields: dict) -> None:
    allowed = {k: v for k, v in fields.items()
               if k in ("name", "description", "notes")}
    if not allowed:
        return
    with connect() as conn:
        conn.execute(
            f"UPDATE projects SET {', '.join(f'{k}=?' for k in allowed)}, updated_at=? WHERE id=?",
            (*allowed.values(), time.time(), proj_id))


def append_project_note(proj_id: str, note: str) -> None:
    stamp = time.strftime("%Y-%m-%d")
    with connect() as conn:
        conn.execute(
            "UPDATE projects SET notes = notes || ?, updated_at=? WHERE id=?",
            (f"\n- [{stamp}] {note}", time.time(), proj_id))


def delete_project(proj_id: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE conversations SET project_id=NULL WHERE project_id=?", (proj_id,))
        conn.execute("DELETE FROM projects WHERE id=?", (proj_id,))


def set_conversation_project(conv_id: str, proj_id: str | None) -> None:
    with connect() as conn:
        conn.execute("UPDATE conversations SET project_id=? WHERE id=?", (proj_id, conv_id))


def conversations_in_project(proj_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, mode, updated_at FROM conversations "
            "WHERE project_id=? ORDER BY updated_at DESC", (proj_id,)).fetchall()
    return [dict(r) for r in rows]


# --- attachments ---------------------------------------------------------------

def add_attachment(conv_id: str, name: str, kind: str, content_text: str,
                   image_b64: str | None = None) -> dict:
    now = time.time()
    att = {"id": uuid.uuid4().hex, "conversation_id": conv_id, "name": name,
           "kind": kind, "created_at": now}
    with connect() as conn:
        conn.execute(
            "INSERT INTO attachments (id, conversation_id, name, kind, content_text, image_b64, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (att["id"], conv_id, name, kind, content_text, image_b64, now))
    return att


def list_attachments(conv_id: str, with_content: bool = False) -> list[dict]:
    cols = "*" if with_content else "id, conversation_id, name, kind, created_at"
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM attachments WHERE conversation_id=? ORDER BY created_at",
            (conv_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_attachment(att_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM attachments WHERE id=?", (att_id,))


def list_conversations() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def rename_conversation(conv_id: str, title: str | None = None, folder: str | None = None) -> None:
    with connect() as conn:
        if title is not None:
            conn.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                         (title, time.time(), conv_id))
        if folder is not None:
            conn.execute("UPDATE conversations SET folder=?, updated_at=? WHERE id=?",
                         (folder, time.time(), conv_id))


def delete_conversation(conv_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))


def search_conversations(query: str) -> list[dict]:
    like = f"%{query}%"
    with connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT c.* FROM conversations c
               LEFT JOIN messages m ON m.conversation_id = c.id
               WHERE c.title LIKE ? OR m.content LIKE ?
               ORDER BY c.updated_at DESC LIMIT 50""",
            (like, like)).fetchall()
    return [dict(r) for r in rows]


# --- messages ----------------------------------------------------------------

def add_message(conv_id: str, role: str, content: str, meta: dict | None = None) -> dict:
    now = time.time()
    msg = {"id": uuid.uuid4().hex, "conversation_id": conv_id, "role": role,
           "content": content, "meta": meta or {}, "created_at": now}
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, meta, created_at) VALUES (?,?,?,?,?,?)",
            (msg["id"], conv_id, role, content, json.dumps(msg["meta"]), now))
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
    return msg


def set_summary(conv_id: str, summary: str, upto: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE conversations SET summary=?, summary_upto=? WHERE id=?",
                     (summary, upto, conv_id))


def get_messages(conv_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",
            (conv_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d["meta"])
        out.append(d)
    return out


def update_message(msg_id: str, content: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE messages SET content=? WHERE id=?", (content, msg_id))


def delete_messages_after(conv_id: str, msg_id: str) -> None:
    """Delete a message and everything after it (used by edit/regenerate)."""
    with connect() as conn:
        row = conn.execute("SELECT created_at FROM messages WHERE id=?", (msg_id,)).fetchone()
        if row:
            conn.execute(
                "DELETE FROM messages WHERE conversation_id=? AND created_at>=?",
                (conv_id, row["created_at"]))


# --- capability gaps ---------------------------------------------------------

GAP_FIELDS = ["capability", "user_prompt", "goal", "reason", "technical_limitation",
              "missing_tool", "missing_integration", "missing_permission",
              "missing_ai_capability", "suggested_fix", "difficulty"]


def add_gap(data: dict) -> dict:
    now = time.time()
    gap = {f: str(data.get(f, "") or "") for f in GAP_FIELDS}
    gap.update({"id": uuid.uuid4().hex, "status": "open", "count": 1,
                "created_at": now, "updated_at": now})
    with connect() as conn:
        conn.execute(
            f"INSERT INTO capability_gaps (id, {', '.join(GAP_FIELDS)}, status, count, created_at, updated_at) "
            f"VALUES (?{', ?' * len(GAP_FIELDS)}, ?, ?, ?, ?)",
            (gap["id"], *[gap[f] for f in GAP_FIELDS],
             gap["status"], gap["count"], now, now))
    return gap


def bump_gap(gap_id: str, user_prompt: str = "") -> None:
    """Same failure again: increment the request count (drives priority)."""
    with connect() as conn:
        conn.execute(
            "UPDATE capability_gaps SET count = count + 1, updated_at = ?, "
            "user_prompt = CASE WHEN ? != '' THEN ? ELSE user_prompt END, "
            "status = CASE WHEN status = 'dismissed' THEN 'open' ELSE status END "
            "WHERE id = ?",
            (time.time(), user_prompt, user_prompt, gap_id))


def list_gaps() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM capability_gaps ORDER BY count DESC, updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_gap(gap_id: str, fields: dict) -> None:
    allowed = set(GAP_FIELDS) | {"status", "count"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    with connect() as conn:
        conn.execute(
            f"UPDATE capability_gaps SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE id=?",
            (*sets.values(), time.time(), gap_id))


def delete_gap(gap_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM capability_gaps WHERE id=?", (gap_id,))


# --- knowledge documents -------------------------------------------------------

def add_document(name: str, chunks: list[tuple[str, list[float] | None]]) -> dict:
    now = time.time()
    doc_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, name, chunk_count, created_at) VALUES (?,?,?,?)",
            (doc_id, name, len(chunks), now))
        conn.executemany(
            "INSERT INTO doc_chunks (id, doc_id, seq, content, embedding) VALUES (?,?,?,?,?)",
            [(uuid.uuid4().hex, doc_id, i, content,
              json.dumps(emb) if emb else None)
             for i, (content, emb) in enumerate(chunks)])
    return {"id": doc_id, "name": name, "chunk_count": len(chunks), "created_at": now}


def list_documents() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_document(doc_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))


def all_chunks() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT c.id, c.doc_id, c.seq, c.content, c.embedding, d.name AS doc_name
               FROM doc_chunks c JOIN documents d ON d.id = c.doc_id""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["embedding"] = json.loads(d["embedding"]) if d["embedding"] else None
        out.append(d)
    return out


# --- memories ----------------------------------------------------------------

def add_memory(content: str, category: str = "general",
               embedding: list[float] | None = None) -> dict:
    now = time.time()
    mem = {"id": uuid.uuid4().hex, "content": content, "category": category,
           "created_at": now, "updated_at": now}
    with connect() as conn:
        conn.execute(
            "INSERT INTO memories (id, content, category, embedding, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (mem["id"], content, category,
             json.dumps(embedding) if embedding else None, now, now))
    return mem


def list_memories() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["embedding"] = json.loads(d["embedding"]) if d["embedding"] else None
        out.append(d)
    return out


def update_memory(mem_id: str, content: str, embedding: list[float] | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE memories SET content=?, embedding=?, updated_at=? WHERE id=?",
            (content, json.dumps(embedding) if embedding else None, time.time(), mem_id))


def delete_memory(mem_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM memories WHERE id=?", (mem_id,))

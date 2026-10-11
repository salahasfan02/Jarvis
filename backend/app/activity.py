"""Everything Jarvis did, and how to take it back.

Each tool run is logged (what, when, from where: the app, the phone, a
routine). Tools that change things leave an undo recipe with offer_undo();
undo() carries it out: move a file back, restore an overwritten file or a
trashed one, remove a created document or empty folder, forget a saved
memory, person or routine.
"""
from __future__ import annotations

import contextvars
import json
import shutil
import time
import uuid
from pathlib import Path

from . import db
from .config import JARVIS_HOME

BACKUPS = JARVIS_HOME / "undo"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'app',
    undo TEXT NOT NULL DEFAULT '',
    undone INTEGER NOT NULL DEFAULT 0
);
"""
_ready = False
# Set by the tool executor around each run; tools put their undo recipe in it.
# (A shared dict, so it works from tools that run in a worker thread.)
_slot: contextvars.ContextVar[dict | None] = contextvars.ContextVar("jarvis_undo", default=None)

READ_ONLY = {"list_directory", "search_files", "read_file", "read_document", "browser_tabs",
             "browser_read_page", "screen_read", "screen_look", "camera_look", "read_emails",
             "read_email", "search_emails", "calendar_events", "calendar_today", "web_search",
             "web_fetch", "find_person", "list_routines", "list_shortcuts", "ui_elements",
             "search_documents", "search_notes", "read_note", "current_datetime", "calculator",
             "read_messages", "read_conversation_with", "clipboard_read", "compare_documents",
             "index_documents"}


def _ensure() -> None:
    global _ready
    if not _ready:
        with db.connect() as conn:
            conn.executescript(_SCHEMA)
        _ready = True


def begin() -> tuple[dict, contextvars.Token]:
    slot: dict = {}
    return slot, _slot.set(slot)


def end(token: contextvars.Token) -> None:
    _slot.reset(token)


def offer_undo(**recipe) -> None:
    """Called by a tool that changed something: how to reverse it."""
    slot = _slot.get()
    if slot is not None:
        slot["undo"] = recipe


def backup(path: Path) -> str:
    """Copy a file about to be overwritten; returns the backup path."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS / f"{uuid.uuid4().hex[:8]}-{path.name}"
    shutil.copy2(path, dest)
    return str(dest)


def record(tool: str, arguments: dict, result: str, source: str, undo: dict | None) -> None:
    if tool in READ_ONLY and not undo:
        return
    _ensure()
    with db.connect() as conn:
        conn.execute("INSERT INTO activity VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                     (uuid.uuid4().hex[:12], time.time(), tool,
                      json.dumps(arguments)[:4000], (result or "")[:600], source,
                      json.dumps(undo) if undo else ""))


def recent(limit: int = 100) -> list[dict]:
    _ensure()
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM activity ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["arguments"] = json.loads(d["arguments"] or "{}")
        d["can_undo"] = bool(d["undo"]) and not d["undone"]
        d["undo"] = json.loads(d["undo"]) if d["undo"] else None
        out.append(d)
    return out


def _trash(path: Path) -> None:
    import subprocess
    subprocess.run(["osascript", "-e", f'tell application "Finder" to delete POSIX file "{path}"'],
                   capture_output=True, timeout=30)


def _apply(u: dict) -> tuple[bool, str]:
    """Carry out an undo recipe: (done, what happened)."""
    kind = u.get("kind")
    if kind == "move_back":
        now, was = Path(u["now"]), Path(u["was"])
        if not now.exists():
            return False, f"{now.name} is no longer at {now.parent} — can't move it back."
        if was.exists():
            return False, f"Something is already at {was} — not overwriting it."
        was.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(now), str(was))
        return True, f"Moved {now.name} back to {was.parent}."
    if kind == "remove_created":
        p = Path(u["path"])
        if not p.exists():
            return True, f"{p.name} is already gone."
        _trash(p)
        return True, f"Moved {p.name} to the Trash."
    if kind == "remove_folder":
        p = Path(u["path"])
        if p.exists() and not any(p.iterdir()):
            p.rmdir()
            return True, f"Removed the empty folder {p.name}."
        return False, f"{p.name} isn't empty any more — left it alone."
    if kind == "restore_backup":
        p, b = Path(u["path"]), Path(u["backup"])
        if not b.exists():
            return False, "The saved copy is gone — can't restore."
        shutil.copy2(b, p)
        return True, f"Restored the previous version of {p.name}."
    if kind == "restore_from_trash":
        was = Path(u["was"])
        trash = Path.home() / ".Trash"
        found = sorted((c for c in trash.glob("*") if c.name.startswith(was.stem)),
                       key=lambda c: c.stat().st_mtime, reverse=True)
        if not found:
            return False, f"{was.name} isn't in the Trash any more."
        if was.exists():
            return False, f"Something is already at {was} — not overwriting it."
        shutil.move(str(found[0]), str(was))
        return True, f"Put {was.name} back in {was.parent}."
    if kind == "forget_memory":
        db.delete_memory(u["id"])
        return True, "Forgot it."
    if kind == "forget_person":
        from .memory import people
        people.forget(u["name"])
        return True, f"Forgot {u['name']}."
    if kind == "delete_routine":
        from . import routines
        routines.remove(u["id"])
        return True, "Deleted that routine."
    return False, "That can't be undone."


def undo(activity_id: str) -> str:
    entry = next((a for a in recent(500) if a["id"] == activity_id), None)
    if entry is None:
        return "No such action."
    if entry["undone"]:
        return "Already undone."
    if not entry["can_undo"]:
        return "That one can't be undone."
    try:
        done, out = _apply(entry["undo"])
    except Exception as e:
        return f"Couldn't undo: {e}"
    if done:
        with db.connect() as conn:
            conn.execute("UPDATE activity SET undone=1 WHERE id=?", (activity_id,))
    return out


def undo_last() -> str:
    entry = next((a for a in recent(50) if a["can_undo"]), None)
    if entry is None:
        return "There's nothing I can undo."
    return f"{entry['tool']}: " + undo(entry["id"])

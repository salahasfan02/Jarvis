"""The activity log, and undoing what Jarvis did."""
import asyncio

from app import activity, db
from app.chat import service
from app.tools import base as tools


def _run(name, args):
    out = {}

    async def go():
        async for _ in service._execute_with_permission(name, args, [], out):
            pass
    asyncio.run(go())
    return out["output"]


def test_moving_a_file_can_be_undone(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.registry.get("move_file"), "needs_confirmation", lambda: False)
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "Spain").mkdir()
    _run("move_file", {"source": str(tmp_path / "notes.txt"), "destination": str(tmp_path / "Spain")})
    assert (tmp_path / "Spain" / "notes.txt").exists()
    entry = activity.recent(1)[0]
    assert entry["tool"] == "move_file" and entry["can_undo"]
    assert "Moved notes.txt back" in activity.undo(entry["id"])
    assert (tmp_path / "notes.txt").exists() and not (tmp_path / "Spain" / "notes.txt").exists()
    assert activity.undo(entry["id"]) == "Already undone."


def test_overwriting_a_file_can_be_undone(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.registry.get("write_file"), "needs_confirmation", lambda: False)
    f = tmp_path / "plan.txt"
    f.write_text("version 1")
    _run("write_file", {"path": str(f), "content": "version 2"})
    assert f.read_text() == "version 2"
    assert "Restored" in activity.undo_last()
    assert f.read_text() == "version 1"


def test_new_folder_and_saved_person_can_be_undone(tmp_path):
    _run("create_folder", {"path": str(tmp_path / "Invoices")})
    assert "Removed the empty folder" in activity.undo_last()
    assert not (tmp_path / "Invoices").exists()
    from app.memory import people
    _run("remember_person", {"name": "Zed Example", "email": "zed@example.com"})
    assert people.known("Zed")
    assert "Forgot Zed Example" in activity.undo_last()
    assert not people.known("Zed")


def test_reads_are_not_logged_and_failures_are_not_undoable(tmp_path):
    before = len(activity.recent(500))
    _run("list_directory", {"path": str(tmp_path)})
    assert len(activity.recent(500)) == before

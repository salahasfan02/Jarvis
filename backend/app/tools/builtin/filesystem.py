"""Filesystem tools. Reads are safe; writes/moves ask for confirmation;
deletion is always confirmed and only moves items to the Trash (never a
permanent delete)."""
from __future__ import annotations

import asyncio
import datetime
import os
import shutil
import subprocess
from pathlib import Path

from ..base import tool
from .documents import find_file


def _expand(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _stamp(p: Path) -> str:
    return datetime.datetime.fromtimestamp(_mtime(p)).strftime("%Y-%m-%d %H:%M")


@tool(
    name="list_directory",
    description="List files and folders in a directory. Path supports ~ for home. "
                "sort='recent' lists newest first with modification times — use it for "
                "'my latest/last/newest …' (e.g. the latest screenshot on the Desktop).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "directory path, e.g. ~/Desktop"},
            "sort": {"type": "string", "enum": ["name", "recent"],
                     "description": "name (default) or recent (newest first, with dates)"},
        },
        "required": ["path"],
    },
    agent_tags=["files"],
)
def list_directory(path: str, sort: str = "name") -> str:
    p = _expand(path)
    if not p.is_dir():
        return f"Not a directory: {p}"
    # Hidden files (.DS_Store, .localized) are noise to a person.
    visible = [e for e in p.iterdir() if not e.name.startswith(".")]
    # The full list is shown to the user directly (the model reads an excerpt),
    # so the cap is only a guard against enormous folders.
    if sort == "recent":
        entries = sorted(visible, key=_mtime, reverse=True)
        lines = [f"{_stamp(e)}  {'[dir] ' if e.is_dir() else ''}{e.name}"
                 for e in entries[:LIST_CAP]]
        head = f"{p} ({len(entries)} items, newest first)"
    else:
        entries = sorted(visible, key=lambda e: (e.is_file(), e.name.lower()))
        lines = [f"{'[dir] ' if e.is_dir() else ''}{e.name}" for e in entries[:LIST_CAP]]
        head = f"{p} ({len(entries)} items)"
    if len(entries) > LIST_CAP:
        head += f" — showing the first {LIST_CAP}"
    return head + ":\n" + "\n".join(lines)


LIST_CAP = 1000


# Opening these RUNS something (a script, an installer) — not what "open my
# file" means, and a wrong guess shouldn't execute code.
_RUNS_CODE = {".command", ".sh", ".zsh", ".bash", ".tool", ".pkg", ".mpkg", ".workflow",
              ".scpt", ".applescript", ".jar", ".py", ".rb", ".pl", ".terminal", ".exe"}


@tool(
    name="open_file",
    description="Open a file or folder on this Mac in its default app — a PDF in Preview, "
                "a .docx in Word/Pages, a photo, a video, or a folder in Finder. Give a full "
                "path OR just the name the user said (\"my CV\", \"lease.pdf\", \"the Spain "
                "folder\"): it searches Desktop, Downloads, Documents, then the whole home "
                "folder. For applications use open_app.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string",
                                "description": "full path, or the file/folder name"}},
        "required": ["path"],
    },
    agent_tags=["files", "automation"],
)
async def open_file(path: str) -> str:
    p, candidates = await asyncio.to_thread(find_file, path)
    if p is None:
        if candidates:
            return ("Several files could match — ask the user which one, then call "
                    "open_file with its full path:\n" + "\n".join(candidates))
        return f"No file or folder called '{path}' was found on this Mac."
    if p.suffix.lower() in _RUNS_CODE or (
            p.is_file() and not p.suffix and os.access(p, os.X_OK)):
        return (f"{p} is a script or installer — opening it would run it, so I didn't. "
                "The user can open it themselves in Finder.")
    result = subprocess.run(["open", str(p)], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return f"Couldn't open {p}: {result.stderr.strip()}"
    return f"Opened {p}"


@tool(
    name="read_file",
    description="Read a text file's contents (first 10000 characters).",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    agent_tags=["files", "coding"],
)
def read_file(path: str) -> str:
    p = _expand(path)
    if not p.is_file():
        return f"Not a file: {p}"
    try:
        return p.read_text(errors="replace")[:10000]
    except OSError as e:
        return f"Could not read file: {e}"


@tool(
    name="write_file",
    description="Write text content to a file, creating it if needed.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
    risk="confirm",
    agent_tags=["files", "coding"],
)
def write_file(path: str, content: str) -> str:
    p = _expand(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content)} characters to {p}"


@tool(
    name="create_folder",
    description="Create a folder (and any missing parent folders).",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    agent_tags=["files"],
)
def create_folder(path: str) -> str:
    p = _expand(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Created folder {p}"


@tool(
    name="move_file",
    description="Move or rename a file or folder.",
    parameters={
        "type": "object",
        "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
        "required": ["source", "destination"],
    },
    risk="confirm",
    agent_tags=["files"],
)
def move_file(source: str, destination: str) -> str:
    src, dst = _expand(source), _expand(destination)
    if not src.exists():
        return f"Source does not exist: {src}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"Moved {src} -> {dst}"


@tool(
    name="trash_file",
    description="Move a file or folder to the macOS Trash (recoverable delete).",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    risk="dangerous",
    agent_tags=["files"],
)
def trash_file(path: str) -> str:
    p = _expand(path)
    if not p.exists():
        return f"Path does not exist: {p}"
    script = f'tell application "Finder" to delete POSIX file "{p}"'
    result = subprocess.run(["osascript", "-e", script],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return f"Failed to trash: {result.stderr.strip()}"
    return f"Moved {p} to Trash"


@tool(
    name="search_files",
    description="Search for files by name using Spotlight (mdfind). Results are newest "
                "first, each with its modification time and full path.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "file name or part of it"},
            "directory": {"type": "string", "description": "optional folder to limit the search to"},
        },
        "required": ["query"],
    },
    agent_tags=["files"],
)
def search_files(query: str, directory: str = "") -> str:
    cmd = ["mdfind", "-name", query]
    if directory:
        cmd += ["-onlyin", str(_expand(directory))]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    # Newest first, with dates: "the latest screenshot" is then simply line 1,
    # and full paths let a later turn send the file without searching again.
    paths = sorted((Path(line) for line in result.stdout.splitlines()[:300] if line),
                   key=_mtime, reverse=True)[:30]
    return ("\n".join(f"{_stamp(f)}  {f}" for f in paths) if paths
            else "No files found.")

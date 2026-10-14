"""Photos Jarvis takes with the camera ("take a picture").

They're kept in ~/Pictures/Jarvis, named by when they were taken
(photo-2026-10-14-22-30-15.jpg — no spaces, so a model can pass the path on
intact), newest first. Only files in that folder count as Jarvis's photos:
the API serves and deletes nothing else.
"""
from __future__ import annotations

import base64
import binascii
import datetime
import subprocess
import urllib.parse
from pathlib import Path

PHOTOS_DIR = Path.home() / "Pictures" / "Jarvis"
IMAGE_TYPES = (".jpg", ".jpeg", ".png")
MAX_BYTES = 25 * 1024 * 1024


def image_bytes(data: str) -> bytes:
    """A data URL or bare base64 -> bytes; b'' if it isn't a JPEG or PNG."""
    try:
        raw = base64.b64decode((data or "").split(",")[-1], validate=False)
    except (binascii.Error, ValueError):
        return b""
    return raw if _kind(raw) and len(raw) <= MAX_BYTES else b""


def _kind(raw: bytes) -> str:
    if raw.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    return ""


def save(raw: bytes, when: datetime.datetime | None = None) -> Path:
    """Write a photo into the folder under a new name; returns its path."""
    ext = _kind(raw)
    if not ext:
        raise ValueError("not a JPEG or PNG image")
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    stem = (when or datetime.datetime.now()).strftime("photo-%Y-%m-%d-%H-%M-%S")
    path, n = PHOTOS_DIR / f"{stem}{ext}", 2
    while path.exists():
        path, n = PHOTOS_DIR / f"{stem}-{n}{ext}", n + 1
    path.write_bytes(raw)
    return path


def is_photo(path: Path) -> bool:
    """One of Jarvis's camera photos (sent to a phone as a picture, not a file)."""
    try:
        return (path.suffix.lower() in IMAGE_TYPES and path.is_file()
                and path.resolve().parent == PHOTOS_DIR.resolve())
    except OSError:
        return False


def recent(limit: int = 60) -> list[Path]:
    if not PHOTOS_DIR.is_dir():
        return []
    shots = [p for p in PHOTOS_DIR.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_TYPES and not p.name.startswith(".")]
    return sorted(shots, key=lambda p: p.stat().st_mtime, reverse=True)[:max(1, limit)]


def by_name(name: str) -> Path | None:
    """A photo in the folder by file name — never anything outside it."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    p = PHOTOS_DIR / name
    return p if is_photo(p) else None


def info(p: Path) -> dict:
    st = p.stat()
    return {"name": p.name, "path": str(p), "bytes": st.st_size, "taken_at": st.st_mtime,
            "url": f"/api/photos/file/{urllib.parse.quote(p.name)}"}


def trash(p: Path) -> bool:
    """Move a photo to the Trash (recoverable), like every delete in Jarvis."""
    quoted = str(p).replace("\\", "\\\\").replace('"', '\\"')
    try:
        r = subprocess.run(["osascript", "-e", f'tell application "Finder" to delete POSIX file "{quoted}"'],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0

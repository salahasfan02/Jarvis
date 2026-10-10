"""Background pictures for the UI, stored in ~/.jarvis/backgrounds.

Uploads are checked by their actual bytes (not the file name), capped in
size, and saved under a generated name, so nothing a user picks can escape
the folder. iPhone photos (HEIC) are converted to JPEG with macOS's `sips`,
because Chrome can't display HEIC.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from .config import JARVIS_HOME, settings

BG_DIR = JARVIS_HOME / "backgrounds"
BG_DIR.mkdir(exist_ok=True)
MAX_BYTES = 25 * 1024 * 1024
_NAME = re.compile(r"[a-f0-9]{12}-[a-z0-9_-]{0,40}\.(?:jpg|png|webp|gif)")


def _kind(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"hevc", b"heif"):
        return "heic"
    return None


def _to_jpeg(data: bytes) -> bytes | None:
    """HEIC -> JPEG via macOS's built-in `sips`; None where it isn't available."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.heic", Path(tmp) / "out.jpg"
        src.write_bytes(data)
        try:
            subprocess.run(["sips", "-s", "format", "jpeg", str(src), "--out", str(dst)],
                           capture_output=True, timeout=60, check=True)
        except (OSError, subprocess.SubprocessError):
            return None
        return dst.read_bytes() if dst.exists() else None


def _entry(path: Path) -> dict:
    return {"name": path.name, "url": f"/api/backgrounds/file/{path.name}"}


def list_all() -> list[dict]:
    files = [p for p in BG_DIR.iterdir() if _NAME.fullmatch(p.name)]
    return [_entry(p) for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]


def save(filename: str, data: bytes) -> dict:
    if not data:
        return {"error": "That file is empty."}
    if len(data) > MAX_BYTES:
        return {"error": "That picture is over 25 MB — pick a smaller one."}
    kind = _kind(data)
    if kind == "heic":
        data = _to_jpeg(data) or b""
        kind = "jpg" if data else None
        if not data:
            return {"error": "Couldn't convert that HEIC photo — export it as JPEG first."}
    if kind is None:
        return {"error": "That isn't a picture Jarvis can show (use JPEG, PNG, WebP or GIF)."}
    stem = re.sub(r"[^a-z0-9_-]+", "-", Path(filename).stem.lower()).strip("-")[:40]
    path = BG_DIR / f"{uuid.uuid4().hex[:12]}-{stem}.{kind}"
    path.write_bytes(data)
    return _entry(path)


def path_for(name: str) -> Path | None:
    if not _NAME.fullmatch(name):
        return None
    path = BG_DIR / name
    return path if path.is_file() else None


def delete(name: str) -> dict:
    path = path_for(name)
    if path:
        path.unlink()
        if settings.get("ui.background", "") == f"image:{name}":
            settings.update({"ui": {"background": ""}})  # don't point at a missing file
    return {"ok": True}

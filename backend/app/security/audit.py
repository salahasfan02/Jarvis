"""Append-only audit log. Every tool execution, confirmation and denial is
recorded so nothing happens on the machine silently."""
from __future__ import annotations

import json
import threading
import time

from ..config import AUDIT_FILE

_lock = threading.Lock()
MAX_BYTES = 10 * 1024 * 1024   # then rotate to audit.log.1 (one generation kept)


def log(event: str, **fields) -> None:
    entry = {"ts": time.time(), "event": event, **fields}
    with _lock:
        try:
            if AUDIT_FILE.stat().st_size > MAX_BYTES:
                AUDIT_FILE.replace(AUDIT_FILE.with_suffix(".log.1"))
        except OSError:
            pass  # no log yet
        with AUDIT_FILE.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def tail(limit: int = 200) -> list[dict]:
    """The newest entries. Reads only the end of the file: the dashboard asks
    every few seconds, and the log grows forever."""
    if not AUDIT_FILE.exists():
        return []
    with AUDIT_FILE.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - min(size, 2048 * max(limit, 1))))
        chunk = f.read().decode(errors="replace")
    lines = chunk.splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # first line of the chunk may be cut mid-entry
    return list(reversed(out))

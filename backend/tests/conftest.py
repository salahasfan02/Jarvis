"""Test setup: an isolated HOME (Jarvis keeps everything under ~/.jarvis), no
real Ollama, no macOS-only calls. Runs on any OS:  cd backend && pytest"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Must happen before `app` is imported: config resolves ~/.jarvis at import.
os.environ["HOME"] = tempfile.mkdtemp(prefix="jarvis-test-home-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import app.main  # noqa: E402,F401  (registers every built-in tool)
from app import db  # noqa: E402
from app.config import settings  # noqa: E402

db.init_db()
settings.update({"context": {"enabled": False},   # no AppleScript snapshots
                 "memory": {"auto_capture": False},
                 "gaps": {"enabled": False}})


@pytest.fixture(autouse=True)
def _no_background_llm(monkeypatch):
    """Post-turn analysis and titling call Ollama; keep tests offline."""
    from app.gaps import registry as gaps
    from app.llm import ollama_client
    from app.memory import store

    monkeypatch.setattr(gaps, "schedule_analysis", lambda *a, **k: None)
    monkeypatch.setattr(store, "schedule_auto_capture", lambda *a, **k: None)

    async def chat_once(*a, **k):
        return "Test title"

    async def embed(*a, **k):
        return None

    monkeypatch.setattr(ollama_client, "chat_once", chat_once)
    monkeypatch.setattr(ollama_client, "embed", embed)


@pytest.fixture(autouse=True)
def _no_real_input(monkeypatch):
    """Tests must never press keys or click on the real Mac."""
    try:
        import Quartz
    except ImportError:
        return
    monkeypatch.setattr(Quartz, "CGEventPost", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_contacts_lookup(monkeypatch):
    """Looking people up in the Mac's Contacts app is not for tests."""
    from app.memory import people
    monkeypatch.setattr(people, "from_contacts", lambda q: [])

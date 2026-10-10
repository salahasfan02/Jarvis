"""Central settings management.

Settings live in ~/.jarvis/settings.json so they survive reinstalls and are
editable both from the UI (via /api/settings) and by hand. Nothing is
hardcoded to a specific model — the active model is just a string that must
match a model available in Ollama.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

JARVIS_HOME = Path.home() / ".jarvis"
JARVIS_HOME.mkdir(exist_ok=True)
SETTINGS_FILE = JARVIS_HOME / "settings.json"
DB_FILE = JARVIS_HOME / "jarvis.db"
AUDIT_FILE = JARVIS_HOME / "audit.log"
PLUGINS_DIR = JARVIS_HOME / "plugins"
PLUGINS_DIR.mkdir(exist_ok=True)

DEFAULT_SETTINGS: dict[str, Any] = {
    "ollama": {
        "host": "http://localhost:11434",
        "model": "llama3.1",           # default chat model (user-changeable)
        "vision_model": "",             # e.g. "llava" — empty = vision disabled
        "embedding_model": "",          # e.g. "nomic-embed-text" — empty = keyword memory
        "temperature": 0.7,
        "num_ctx": 8192,                # context length
        "num_gpu": -1,                  # -1 = let Ollama decide
        "keep_alive": "30m",            # how long the model stays in memory
        # Per-task model overrides. Empty = use the main chat model. Lets a
        # small fast model handle utility work (titles, self-analysis) while
        # a strong model does coding — fully model-agnostic.
        "task_models": {
            "coding": "",               # Code Studio + coding agent
            "utility": "",              # titles, gap analysis, summaries
        },
    },
    "assistant": {
        "name": "Jarvis",
        "wake_words": ["jarvis", "computer", "assistant"],
        "persona": (
            "You are {name}, a capable personal AI assistant running locally on "
            "the user's Mac. Be concise, direct and helpful. Use tools when they "
            "help you answer accurately or act on the user's behalf."
        ),
    },
    "voice": {
        "enabled": True,
        "wake_word_enabled": False,
        "conversation_mode": False,     # auto-reopen mic after Jarvis speaks
        "tts_enabled": True,
        "tts_engine": "kokoro",         # kokoro | piper | browser (auto-falls back)
        "tts_rate": 1.0,
        "tts_voice": "",                # browser engine only; "" = system default
        "kokoro_voice": "bm_george",    # human-sounding neural voice
        "stt_engine": "whisper",        # whisper (offline) | browser (Chrome only)
        "whisper_model": "base",        # tiny | base | small
        "piper_voice_path": "",         # path to a .onnx piper voice model
        "language": "en-US",
    },
    "automation": {
        "browser": "",                  # "" = auto-detect (Safari/Chrome)
    },
    "context": {
        "enabled": True,                # app/tab/music awareness in prompts
    },
    "screen_memory": {
        "enabled": False,               # background: watch screen -> save to memory
        "interval_seconds": 300,        # capture every 5 minutes
    },
    "gaps": {
        "enabled": True,                # capability-gap self-analysis
    },
    "telegram": {                       # text Jarvis from your phone (opt-in)
        "enabled": False,               # bot token lives in ~/.jarvis/telegram_token
        "allowed_users": [],            # paired accounts: [{"id", "name", "username"}]
        "allow_dangerous": False,       # shell/AppleScript/delete from the phone
        "voice_replies": True,          # answer voice notes with a voice note
    },
    "memory": {
        "enabled": True,
        "max_recalled": 5,
        "auto_capture": True,           # learn facts from conversation quietly
    },
    "tools": {
        "enabled": True,
        "max_iterations": 6,            # max tool-call rounds per user message
    },
    "permissions": {
        # tool name -> "ask" | "always" | "never"
        # tools not listed use their declared default
    },
    "ui": {
        "theme": "hacker",              # hacker | dark | light | cyberpunk | system
        "glass": True,
        "accent": "",                   # hex color overriding the theme accent
        "background": "",               # "" theme default | "matrix" | "world" | hex
        "core_design": "orb",           # orb | reactor | halo | nebula
    },
    "developer": {
        "debug": False,
    },
}


class Settings:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        data = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
        if SETTINGS_FILE.exists():
            try:
                stored = json.loads(SETTINGS_FILE.read_text())
                _deep_merge(data, stored)
            except (json.JSONDecodeError, OSError):
                pass
        return data

    def all(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            _deep_merge(self._data, patch)
            SETTINGS_FILE.write_text(json.dumps(self._data, indent=2))
            return json.loads(json.dumps(self._data))


def _deep_merge(base: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


settings = Settings()

"""Offer the model only the tools this request needs.

Every tool definition costs prompt tokens (the automation agent's 45 tools
were ~4,500 tokens — 25+ seconds of reading on a 14B model before it could
answer "close the github tab"). The message is compared by meaning with each
tool's description (the same embedding model that routes requests), and only
the closest few go into the prompt, plus anything this conversation used
recently (follow-ups like "send number 2"). Tools keep their registry order so
the same choice yields a byte-identical, cacheable prompt.
"""
from __future__ import annotations

import math
import re

from ..llm import ollama_client
from ..tools import base as tools

KEEP = 10            # tools offered per request
SMALL_ENOUGH = 12    # agents with this few tools keep them all

_card_vectors: dict[str, list[float]] = {}

# Words that make a tool family obviously relevant, whatever the embedding says.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tab": ("browser_tabs", "browser_close_tab", "browser_open", "browser_read_page"),
    "click": ("browser_click", "ui_press", "click_on_screen", "ui_elements"),
    "press": ("browser_click", "ui_press", "press_keys", "ui_elements"),
    "button": ("browser_click", "ui_press", "ui_elements"),
    "type": ("ui_type", "press_keys"),
    "fill": ("ui_type", "ui_elements"),
    "scroll": ("scroll",),
    "drag": ("drag",),
    "shortcut": ("press_keys",),
    "email": ("send_email", "draft_email", "read_emails", "search_emails"),
    "mail": ("send_email", "draft_email", "read_emails", "search_emails"),
    "attach": ("send_email", "search_files", "create_word_document"),
    "document": ("create_word_document", "create_spreadsheet", "create_presentation",
                 "read_document", "search_files"),
    "file": ("search_files", "list_directory", "open_file", "send_file"),
    "folder": ("list_directory", "create_folder", "move_file"),
    "desktop": ("list_directory", "search_files"),
    "open": ("open_file", "open_app", "browser_open"),
    "remind": ("create_reminder",),
    "calendar": ("calendar_events", "calendar_today", "calendar_create_event"),
    "note": ("create_note", "append_note", "read_note", "search_notes"),
    "youtube": ("youtube_play", "youtube_control", "browser_open"),
    "song": ("music_play", "music_control", "youtube_play"),
    "music": ("music_play", "music_control", "music_playlists"),
    "camera": ("camera_look",),
    "screen": ("screen_look", "screen_read", "watch_screen"),
    "text him": ("draft_imessage",), "text her": ("draft_imessage",),
    "message": ("draft_imessage", "read_messages", "read_conversation_with"),
    "pdf": ("read_document", "search_files", "open_file"),
    "spreadsheet": ("create_spreadsheet",), "excel": ("create_spreadsheet",),
    "presentation": ("create_presentation",), "slides": ("create_presentation",),
    "powerpoint": ("create_presentation",),
    "contact": ("find_person", "remember_person"),
    "remember": ("remember", "remember_person"),
}


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _card(t: tools.Tool) -> str:
    return f"{t.name.replace('_', ' ')}: {t.description}"


async def _vector(t: tools.Tool) -> list[float] | None:
    card = _card(t)
    if card not in _card_vectors:
        v = await ollama_client.embed(card[:600])
        if not v:
            return None
        _card_vectors[card] = v
    return _card_vectors[card]


async def select(user_content: str, tool_list: list[tools.Tool],
                 recent: set[str] | None = None, keep: int = KEEP) -> list[tools.Tool]:
    """The tools worth offering for this message (registry order kept)."""
    if len(tool_list) <= SMALL_ENOUGH:
        return tool_list
    query = await ollama_client.embed(user_content[:400])
    if not query:
        return tool_list   # no embedding model: offer everything, as before
    scores: dict[str, float] = {}
    for t in tool_list:
        v = await _vector(t)
        scores[t.name] = _cos(query, v) if v else 0.0
    chosen = {name for name, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:keep]}
    lower = user_content.lower()
    for word, names in _KEYWORDS.items():
        if re.search(rf"\b{re.escape(word)}", lower):
            chosen.update(names)
    chosen.update(recent or set())
    return [t for t in tool_list if t.name in chosen]

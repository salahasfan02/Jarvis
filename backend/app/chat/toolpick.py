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

KEEP = EXTRAS = 4    # extra tools per request, on top of the core set
REPLY_TOOLS = {"send_reply", "draft_reply"}

# Offered on EVERY request, first and always in this order: with the base
# system prompt they form one shared prompt opening that Ollama keeps cached
# across all agents, so a request only pays for its extra tools and words.
CORE = ("open_app", "quit_app", "open_file", "browser_open", "browser_tabs",
        "browser_close_tab", "browser_click", "youtube_play", "youtube_control",
        "music_play", "music_control", "list_directory", "search_files",
        "read_document", "send_email", "draft_email", "read_emails",
        "calendar_events", "create_reminder", "create_note", "screen_read",
        "screen_look", "camera_look", "research", "remember",
        "create_word_document", "ui_press")

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
                 "read_document", "search_files", "research_report"),
    "report": ("research_report", "create_word_document"), "essay": ("research_report",),
    "write up": ("research_report",), "word doc": ("research_report", "create_word_document"),
    "research": ("research_report",),
    "file": ("search_files", "list_directory", "open_file", "send_file"),
    "send me": ("send_file",), "send it": ("send_file",), "send that": ("send_file",),
    "send them": ("send_file",), "send this": ("send_file",),
    "weather": ("weather",), "forecast": ("weather",), "rain": ("weather",),
    "umbrella": ("weather",), "temperature": ("weather",), "degrees": ("weather",),
    "sunny": ("weather",), "snow": ("weather",), "windy": ("weather",),
    "search the web": ("web_search", "web_fetch"), "google": ("web_search",),
    "github": ("web_search",), "stack overflow": ("web_search",), "reddit": ("web_search",),
    "link": ("web_search", "web_fetch"), "this url": ("web_fetch",), "http": ("web_fetch",),
    "website": ("web_fetch", "web_search"),
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
    "every": ("create_routine",), "routine": ("create_routine", "list_routines", "change_routine"),
    "minutes before": ("create_routine",), "each morning": ("create_routine",),
    "tell me when": ("create_routine", "watch_screen"), "let me know when": ("create_routine", "watch_screen"),
    "arrives": ("create_routine",),
    "undo": ("undo_last",), "put it back": ("undo_last",),
    "form": ("fill_form", "my_details"), "fill": ("fill_form", "ui_type"),
    "my details": ("my_details", "update_my_details"), "my address": ("update_my_details", "my_details"),
    "my phone": ("update_my_details", "my_details"),
    "timer": ("set_timer", "timers"), "volume": ("set_volume",), "louder": ("set_volume",),
    "quieter": ("set_volume",), "remind me in": ("set_timer",),
    "shortcut": ("run_shortcut", "list_shortcuts"), "scene": ("run_shortcut",),
    "lights": ("run_shortcut",), "focus": ("run_shortcut",), "homekit": ("run_shortcut",),
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
                 recent: set[str] | None = None, keep: int = EXTRAS) -> list[tools.Tool]:
    """Extra (non-core) tools worth offering for this message, registry order.
    The core tools are always offered on top (see arrange)."""
    candidates = [t for t in tool_list if t.name not in CORE]
    # Replies answer an email the user received. Offered for a NEW email
    # ("email my landlord…") they got called with made-up ids.
    if not (re.search(r"\b(?:repl|respond|answer)", user_content, re.I)
            or (recent or set()) & {"read_emails", "search_emails", "read_email"}):
        candidates = [t for t in candidates if t.name not in REPLY_TOOLS]
    if not candidates:
        return []
    query = await ollama_client.embed(user_content[:400])
    if not query:
        return candidates   # no embedding model: offer everything, as before
    scores: dict[str, float] = {}
    for t in candidates:
        v = await _vector(t)
        scores[t.name] = _cos(query, v) if v else 0.0
    chosen = {name for name, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:keep]}
    lower = user_content.lower()
    names = {t.name for t in candidates}
    for word, wanted in _KEYWORDS.items():
        if re.search(rf"\b{re.escape(word)}", lower):
            chosen.update(n for n in wanted if n in names)
    chosen.update(n for n in (recent or set()) if n in names)
    return [t for t in candidates if t.name in chosen]


def arrange(picked: list[tools.Tool]) -> list[tools.Tool]:
    """Core tools (fixed order) followed by this request's extras."""
    core = [t for name in CORE if (t := tools.registry.get(name)) is not None
            and not t.is_blocked()]
    names = {t.name for t in core}
    return core + [t for t in picked if t.name not in names]

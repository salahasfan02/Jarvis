"""Instant commands: simple, unambiguous requests run their tool directly.

"open youtube", "open safari", "play lofi on youtube", "pause", "next song"
don't need a language model to understand — and a local 14B model spends
several seconds reading thousands of tokens of tool schemas before it can
act. These commands match a small set of strict patterns (the WHOLE message
must be the command, so "open youtube and find a recipe" still goes to the
model), run their tool through the normal permission path, and answer in
well under a second. Anything that doesn't match falls through to the model.
"""
from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings


@dataclass
class QuickAction:
    tool: str
    arguments: dict = field(default_factory=dict)
    reply: str = ""          # what Jarvis says when the tool succeeds


SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
    "google": "https://www.google.com", "github": "https://github.com",
    "netflix": "https://www.netflix.com", "reddit": "https://www.reddit.com",
    "twitter": "https://x.com", "x": "https://x.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com", "amazon": "https://www.amazon.com",
    "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "wikipedia": "https://www.wikipedia.org", "google maps": "https://maps.google.com",
    "google drive": "https://drive.google.com", "google docs": "https://docs.google.com",
    "google calendar": "https://calendar.google.com",
    "youtube music": "https://music.youtube.com", "twitch": "https://www.twitch.tv",
    "tiktok": "https://www.tiktok.com", "pinterest": "https://www.pinterest.com",
    "hacker news": "https://news.ycombinator.com",
    "stack overflow": "https://stackoverflow.com", "stackoverflow": "https://stackoverflow.com",
    # also apps — the installed app wins when there is one
    "spotify": "https://open.spotify.com", "whatsapp": "https://web.whatsapp.com",
    "outlook": "https://outlook.live.com", "notion": "https://www.notion.so",
    "figma": "https://www.figma.com", "discord": "https://discord.com/app",
    "slack": "https://app.slack.com", "telegram": "https://web.telegram.org",
}
SITE_NAMES = {"youtube": "YouTube", "gmail": "Gmail", "github": "GitHub",
              "x": "X", "chatgpt": "ChatGPT", "linkedin": "LinkedIn",
              "tiktok": "TikTok", "whatsapp": "WhatsApp"}

APP_ALIASES = {
    "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
    "settings": "System Settings", "system preferences": "System Settings",
    "word": "Microsoft Word", "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint", "teams": "Microsoft Teams",
    "app store": "App Store", "facetime": "FaceTime", "imessage": "Messages",
}
APP_DIRS = ["/Applications", "/System/Applications", "/System/Applications/Utilities",
            "/Applications/Utilities", str(Path.home() / "Applications")]

_TLDS = ("com|org|net|io|ai|dev|app|co|edu|gov|me|tv|uk|de|fr|ca|us|info|xyz|so|"
         "gg|fm|news|blog|tech|site|online|ly|sh")
_DOMAIN = re.compile(rf"(?:[a-z0-9-]+\.)+(?:{_TLDS})(?:/\S*)?")

_FILLER = re.compile(
    r"^(?:(?:hey|ok|okay|yo)\s+)?(?:jarvis|computer|assistant)?[\s,.!]*"
    r"(?:(?:can|could|would|will)\s+you\s+|please\s+|just\s+|go\s+ahead\s+and\s+)*", re.I)
_TAIL = re.compile(r"(?:\s+(?:please|for me|now|right now|thanks|thank you))+$", re.I)

_apps_cache: dict = {"at": 0.0, "apps": {}}


def _installed_apps() -> dict[str, str]:
    """lower-case name -> app name, for .app bundles in the usual folders."""
    if time.time() - _apps_cache["at"] < 60:
        return _apps_cache["apps"]
    apps: dict[str, str] = {}
    for folder in APP_DIRS:
        try:
            for entry in Path(folder).iterdir():
                if entry.suffix == ".app":
                    apps.setdefault(entry.stem.lower(), entry.stem)
        except OSError:
            continue
    _apps_cache.update(at=time.time(), apps=apps)
    return apps


def _normalize(text: str) -> str:
    t = text.strip().strip("\"'“”").strip()
    t = _FILLER.sub("", t, count=1)
    t = re.sub(r"[.!?]+$", "", t).strip()
    t = _TAIL.sub("", t).strip()
    return re.sub(r"\s+", " ", t)


def _open(target: str) -> QuickAction | None:
    key = target.lower().strip()
    key = re.sub(r"^(?:the|my)\s+", "", key)
    key = re.sub(r"\s+(?:app|application|website|site|web ?site)$", "", key)
    apps = _installed_apps()
    app = APP_ALIASES.get(key)
    if app and app.lower() not in apps:
        app = None
    app = app or apps.get(key)
    if app:
        return QuickAction("open_app", {"name": app}, f"Opening {app}.")
    if key in SITES:
        name = SITE_NAMES.get(key, key.title())
        return QuickAction("browser_open", {"url": SITES[key]}, f"Opening {name}.")
    if _DOMAIN.fullmatch(key):
        return QuickAction("browser_open", {"url": key}, f"Opening {key}.")
    return None


_MEDIA = {
    "pause": "pause", "stop": "pause", "resume": "play", "play": "play",
    "unpause": "play", "next": "next", "skip": "next", "previous": "previous",
    "mute": "mute", "unmute": "unmute",
}
# Bare "stop" could mean "stop talking", so it needs an object ("stop the music").
_NEEDS_TARGET = {"stop"}
_MEDIA_RE = re.compile(
    r"(pause|stop|resume|unpause|play|next|skip|previous|mute|unmute)"
    r"(?:\s+(?:the\s+)?(music|song|track|video|youtube|playback|it|this))?"
    r"(?:\s+(?:song|track|video))?")


def match(text: str) -> QuickAction | None:
    """Return the instant action for `text`, or None to let the model handle it."""
    t = _normalize(text)
    low = t.lower()
    if not low or len(low) > 80 or " and " in f" {low} " or "," in low:
        return None  # compound or long requests need real understanding

    # YouTube first: "open drake on youtube" is a video, not an app called that.
    if m := re.fullmatch(r"(?:search(?: for)?|find|look up)\s+(.+?)\s+on\s+youtube", low):
        query = m.group(1).strip()
        return QuickAction("browser_open", {"url": "https://www.youtube.com/results?"
                                            + urllib.parse.urlencode({"search_query": query})},
                           f"Here are YouTube results for {query}.")
    if m := re.fullmatch(r"(?:play|put on|open|watch)\s+(.+?)\s+(?:on|from)\s+youtube", low) or \
            re.fullmatch(r"youtube\s+(.+)", low):
        query = m.group(1).strip()
        return QuickAction("youtube_play", {"query": query},
                           f"Playing {query} on YouTube.")

    if m := re.fullmatch(r"(?:open|launch|start|go to|pull up|bring up)\s+(.+)", low):
        return _open(t[len(t) - len(m.group(1)):])
    if m := re.fullmatch(r"play\s+(.+?)\s+(?:on|in)\s+(?:apple\s+)?music", low):
        query = m.group(1).strip()
        return QuickAction("music_play", {"query": query}, "")

    if action := _calendar(low):
        return action

    if m := _MEDIA_RE.fullmatch(low):
        word, target = m.group(1), m.group(2) or ""
        if word in _NEEDS_TARGET and not target:
            return None
        return media_action(_MEDIA[word], video=target in ("video", "youtube"))
    return None


_CALENDAR_RE = re.compile(
    r"(?:what'?s|what is|show me|check|read|what do i have)\s+(?:on\s+)?(?:my\s+)?"
    r"(?:calendar|schedule|agenda)?\s*(?:for\s+)?(today|tomorrow|this week)?"
    r"|(?:my\s+)?(?:calendar|schedule|agenda)(?:\s+for)?\s*(today|tomorrow|this week)?")


def _calendar(low: str) -> QuickAction | None:
    """ "what's on my calendar", "my schedule tomorrow", "what do I have this week" """
    m = _CALENDAR_RE.fullmatch(low)
    if not m or not re.search(r"calendar|schedule|agenda|what do i have", low):
        return None
    when = m.group(1) or m.group(2) or "today"
    if when == "today":
        return QuickAction("calendar_today", {}, "")
    if when == "tomorrow":
        return QuickAction("calendar_events", {"start_in_days": 1, "days": 1}, "")
    return QuickAction("calendar_events", {"start_in_days": 0, "days": 7}, "")


def media_action(verb: str, video: bool = False) -> QuickAction | None:
    """Pick the player that's actually in use: an explicit 'video' -> YouTube;
    Apple Music if it's playing; else an open YouTube tab; else Music if it's
    merely open. Nothing running -> None (never launch an app to pause it)."""
    from ..automation import context
    if not video:
        music_open = context.app_running("Music")
        if music_open and context.music_state().get("state") == "playing":
            video = False
        elif _youtube_tab_open():
            video = True
        elif not music_open:
            return None
    elif not _youtube_tab_open():
        return None
    replies = {"pause": "Paused.", "play": "Resuming.", "next": "Skipping.",
               "previous": "Going back.", "mute": "Muted.", "unmute": "Unmuted."}
    if video:
        action = {"next": "skip", "previous": "seek_back"}.get(verb, verb)
        return QuickAction("youtube_control", {"action": action}, replies[verb])
    action = {"play": "resume"}.get(verb, verb)
    if action in ("mute", "unmute"):  # Music has no mute; fall back to pause/resume
        action = "pause" if action == "mute" else "resume"
    return QuickAction("music_control", {"action": action}, replies[verb])


def _youtube_tab_open() -> bool:
    from ..tools.builtin import browser
    return browser._find_tab("youtube.com") is not None


_FAILED = ("failed", "could not", "couldn't", "no ", "applescript error", "error",
           "browser scripting error", "javascript control is disabled", "unknown",
           "the user denied", "'")  # "'name' is blocked…" / "'song' is not in…"


def reply_for(action: QuickAction, output: str) -> str:
    """The user-facing line: the canned reply on success, the tool's own words
    when it went wrong (so the user learns why)."""
    if not action.reply or output.strip().lower().startswith(_FAILED):
        return output.strip() or action.reply or "Done."
    return action.reply


def enabled() -> bool:
    return bool(settings.get("assistant.instant_commands", True))

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
    # "open my CV" / "open the lease pdf": a file with one clear match.
    if len(key) >= 2 and not re.search(r"\b(?:tab|window|page|door|camera|settings)\b", key):
        from ..tools.builtin.documents import find_file
        try:
            path, candidates = find_file(key)
        except Exception:
            path = None
        if path is not None:
            return QuickAction("open_file", {"path": str(path)}, f"Opening {path.name}.")
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
    if not low or len(low) > 120:
        return None
    # Timers, reminders, volume, time and sums may contain "and" ("an hour and a
    # half", "remind me to buy milk and eggs at 6"), so they're matched first.
    if action := _instant(t, low):
        return action
    if len(low) > 80 or " and " in f" {low} " or "," in low:
        return None  # compound or long requests need real understanding
    if action := _facetime(t, low):
        return action

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

    # "play janice stfu by drake" — Apple Music (they subscribe), unless it's a
    # control ("play", "play next") or meant for YouTube.
    if (m := re.fullmatch(r"play\s+(?:me\s+)?(?:some\s+)?(.+)", low)) and not _MEDIA_RE.fullmatch(low) \
            and not re.search(r"\b(?:youtube|video)\b", low) \
            and settings.get("music.service", "apple_music") == "apple_music":
        query = m.group(1).strip()
        if query not in ("music", "something", "a song", "songs") and not re.fullmatch(
                r"(?:the\s+)?(?:next|previous|last)(?:\s+(?:song|track|one|video))?|it|that|this", query):
            return QuickAction("music_play", {"query": query}, "")

    if m := _MEDIA_RE.fullmatch(low):
        word, target = m.group(1), m.group(2) or ""
        if word in _NEEDS_TARGET and not target:
            return None
        return media_action(_MEDIA[word], video=target in ("video", "youtube"))
    return None


# ---- timers, reminders, volume, time, sums, undo ---------------------------------------

_WORD_OPS = [(r"\s*(?:times|multiplied by|x)\s*", "*"), (r"\s*divided by\s*", "/"),
             (r"\s*plus\s*", "+"), (r"\s*minus\s*", "-"), (r"\s*to the power of\s*", "**"),
             (r"\s*squared", "**2"), (r"\s*cubed", "**3")]


def _math(expr: str) -> str | None:
    """'17% of 2340' / '23 times 19' / '(4+5)*2' -> a calculator expression."""
    e = expr.lower().strip().rstrip("?").replace(",", "")
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(\d+(?:\.\d+)?)", e):
        return f"{m.group(1)}/100*{m.group(2)}"
    if m := re.fullmatch(r"(?:the\s+)?square root of\s+(\d+(?:\.\d+)?)", e):
        return f"sqrt({m.group(1)})"
    for pat, op in _WORD_OPS:
        e = re.sub(pat, op, e)
    e = e.replace("×", "*").replace("÷", "/").replace("^", "**")
    if re.fullmatch(r"[\d.+\-*/() ]+", e) and re.search(r"\d\s*[+\-*/]", e):
        return e.replace(" ", "")
    return None


def _instant(t: str, low: str) -> QuickAction | None:
    from datetime import datetime
    from .timeparse import duration, when

    # "set a (pasta) timer for 10 minutes" / "timer 5 min" / "10 minute timer (for pasta)"
    if m := re.fullmatch(r"(?:set|start|make)?\s*(?:a|an|the|my)?\s*(?:(?P<label>[a-z ]{2,30}?)\s+)?"
                         r"timer\s+(?:for\s+)?(?P<dur>.+)", low):
        if (secs := duration(m.group("dur"))) and (m.group("label") or "").strip() not in ("cancel", "stop"):
            label = (m.group("label") or "").strip()
            return QuickAction("set_timer", {"seconds": secs, "label": label}, "{output}")
    if m := re.fullmatch(r"(?:set|start)?\s*(?:a|an)?\s*(?P<dur>.+?)\s+timer(?:\s+for\s+(?P<label>.+))?", low):
        if secs := duration(m.group("dur")):
            return QuickAction("set_timer", {"seconds": secs, "label": (m.group("label") or "").strip()},
                               "{output}")
    # "remind me in 20 minutes to X" / "remind me to X in 20 minutes"
    if m := (re.fullmatch(r"remind me in\s+(?P<dur>.+?)\s+to\s+(?P<task>.+)", low)
             or re.fullmatch(r"remind me to\s+(?P<task>.+?)\s+in\s+(?P<dur>.+)", low)):
        if secs := duration(m.group("dur")):
            task = t[m.start("task"):m.end("task")]
            return QuickAction("set_timer", {"seconds": secs, "label": task, "reminder": True},
                               "{output}")
    # "remind me at 6 to X" / "remind me tomorrow at 9 to X" / "remind me to X at 6pm"
    if m := (re.fullmatch(r"remind me\s+(?P<when>(?:(?:today|tonight|tomorrow|on \w+day)\s+)?"
                          r"(?:at\s+)?[\d:.]+\s*(?:am|pm)?|(?:today|tonight|tomorrow|on \w+day)\s+at\s+"
                          r"[\d:.]+\s*(?:am|pm)?|at noon|at midnight)\s+to\s+(?P<task>.+)", low)
             or re.fullmatch(r"remind me to\s+(?P<task>.+?)\s+(?P<when>(?:(?:today|tonight|tomorrow|"
                             r"on \w+day)\s+)?at\s+[\d:.]+\s*(?:am|pm)?|(?:today|tonight|tomorrow)"
                             r"\s+at\s+[\d:.]+\s*(?:am|pm)?|at noon|at midnight)", low)):
        if due := when(m.group("when")):
            task = t[m.start("task"):m.end("task")]
            return QuickAction("create_reminder", {"title": task[0].upper() + task[1:],
                                                   "due": due.strftime("%Y-%m-%d %H:%M")}, "")
    # timers: cancel / how long left
    if m := re.fullmatch(r"(?:cancel|stop|delete|kill|turn off)\s+(?:the\s+|my\s+)?(?:(?P<label>.+?)\s+)?timers?", low):
        return QuickAction("timers", {"cancel": True, "label": (m.group("label") or "").strip()}, "")
    if re.fullmatch(r"how (?:long|much time)(?: is| has| do i have)? (?:left|remaining)(?: on (?:the|my) .*timer)?"
                    r"|(?:how'?s|check) (?:the |my )?timers?", low):
        return QuickAction("timers", {}, "")
    # volume
    if m := re.fullmatch(r"(?:turn\s+)?(?:the\s+)?(?:volume|sound)\s+(up|down)|turn (?:it|the sound|the volume) (up|down)", low):
        return QuickAction("set_volume", {"change": m.group(1) or m.group(2)}, "")
    if low in ("louder", "a bit louder", "quieter", "a bit quieter", "softer"):
        return QuickAction("set_volume", {"change": "up" if "loud" in low else "down"}, "")
    if m := re.fullmatch(r"(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*(?:%|percent)?", low):
        return QuickAction("set_volume", {"level": int(m.group(1))}, "")
    if re.fullmatch(r"mute (?:the )?(?:volume|sound|mac|computer)", low):
        return QuickAction("set_volume", {"change": "mute"}, "")
    if re.fullmatch(r"unmute (?:the )?(?:volume|sound|mac|computer)", low):
        return QuickAction("set_volume", {"change": "unmute"}, "")
    # time and date — answered right away
    now = datetime.now()
    if re.fullmatch(r"what(?:'s| is)? the time|what time is it|time\??|what'?s the time now", low):
        return QuickAction("current_datetime", {}, f"It's {now.strftime('%-I:%M %p').lower()}.")
    if re.fullmatch(r"what(?:'s| is)? (?:the date|today'?s date)(?: today)?|what day is (?:it|today)"
                    r"|what'?s today", low):
        return QuickAction("current_datetime", {}, f"It's {now.strftime('%A, %-d %B %Y')}.")
    # sums
    if m := re.fullmatch(r"(?:what'?s|what is|calculate|how much is|work out)\s+(.+)", low):
        if expr := _math(m.group(1)):
            return QuickAction("calculator", {"expression": expr},
                               f"{m.group(1).strip().rstrip('?')} is {{output}}.")
    # undo
    if re.fullmatch(r"undo(?: that| it| the last (?:thing|action))?|put it back|take that back", low):
        return QuickAction("undo_last", {}, "")
    # "send that to me" / "send me the whole chat" / "put that in a document and send it to me"
    if action := _send_to_me(low):
        return action
    # "take a picture" / "take a selfie and send it to me"
    if action := _photo(low):
        return action
    if action := _lights(low):
        return action
    return None


# ---- calls and photos --------------------------------------------------------------

_FT = r"face ?time"
_CALL_KIND = r"(?P<kind>video|audio|voice)"
_FACETIME = (
    # "facetime salah", "facetime audio mum", "facetime video call with sam"
    re.compile(rf"{_FT}(?:\s+{_CALL_KIND})?(?:\s+call)?(?:\s+(?:with|to))?\s+(?P<who>.+)"),
    # "make a facetime call to salah", "start a facetime audio call with mum"
    re.compile(rf"(?:make|start|place|do)\s+(?:a\s+)?{_FT}(?:\s+{_CALL_KIND})?(?:\s+call)?"
               rf"\s+(?:to|with)\s+(?P<who>.+)"),
    # "call salah on facetime", "ring mum over facetime audio"
    re.compile(rf"(?:call|ring|phone|dial)\s+(?P<who>.+?)\s+(?:on|via|over|using|with|through)"
               rf"\s+{_FT}(?:\s+{_CALL_KIND})?(?:\s+call)?"),
    # "video call salah", "make a video call to mum", "voice call dad"
    re.compile(rf"(?:(?:make|start|place|do)\s+(?:an?\s+)?)?{_CALL_KIND}\s+call\s+(?:to\s+|with\s+)?"
               rf"(?P<who>.+)"),
)
# "facetime him" needs the conversation; "facetime audio" isn't a person.
_NOT_A_NAME = {"him", "her", "them", "it", "back", "me", "us", "someone", "somebody", "anyone",
               "him back", "her back", "them back", "app", "the app", "settings", "call", "audio",
               "video", "voice"}
# "FaceTime isn't working", "video call quality is bad": about FaceTime, not a call.
_ABOUT_IT = re.compile(
    r"(?:is|isn'?t|are|aren'?t|was|wasn'?t|keeps?|won'?t|doesn'?t|does|did|didn'?t|has|hasn'?t|"
    r"have|not|no|can'?t|cannot|should|stopped|crash\w*|fail\w*|freez\w*|quality|settings?|"
    r"issues?|problems?|errors?|help|works?|working|broken|lag|lags|lagging|laggy|sound|camera|"
    r"mic|microphone)\b", re.I)


def _facetime(t: str, low: str) -> QuickAction | None:
    """"FaceTime Salah's business number", "video call mum", "call Sam on
    FaceTime" — the call, straight away; the tool finds who and which number."""
    for pattern in _FACETIME:
        if m := pattern.fullmatch(low):
            who = t[m.start("who"):m.end("who")].strip()
            if not who or who.lower() in _NOT_A_NAME or _ABOUT_IT.match(who):
                return None
            kind = "audio" if m.group("kind") in ("audio", "voice") else "video"
            return QuickAction("facetime_call", {"contact": who, "kind": kind}, "")
    return None


_PIC = r"(?:picture|photo|pic|photograph|selfie)"
_TAKE_PHOTO = re.compile(
    r"(?:take|snap|grab|shoot)\s+(?:a\s+|an\s+|my\s+|me\s+a\s+|another\s+|one\s+more\s+)?"
    rf"(?:quick\s+|new\s+)?{_PIC}"
    r"(?:\s+of\s+(?:me|us|myself|this|that|it|him|her|them))?"
    r"(?:\s+(?:with|using|on|from|through)\s+(?:the\s+|my\s+)?(?:camera|webcam|mac))?")
_AND_SEND = re.compile(
    r"(?:,\s*|\s+)and\s+(?:then\s+)?send\s+(?:it|that|this|the\s+(?:picture|photo|pic|selfie))"
    r"(?:\s+(?:back\s+)?to\s+me|\s+me|\s+to\s+my\s+phone)?(?:\s+(?:on|via|over|through)\s+telegram)?$")


def _photo(low: str) -> QuickAction | None:
    """'take a picture', 'take a selfie and send it to me' — the camera, now.
    'Take a picture of my screen' isn't the camera, so it goes to the model."""
    m = _AND_SEND.search(low)
    if _TAKE_PHOTO.fullmatch((low[:m.start()] if m else low).strip()):
        return QuickAction("take_photo", {"send_to_phone": True} if m else {}, "")
    return None


_L = r"(?:the |my |all (?:the )?)?(?P<name>[a-z][a-z ]{0,20}? )?(?:lights?|lamps?|bulbs?)"


def _lights(low: str) -> QuickAction | None:
    """'lights off', 'turn on the bedroom light', 'dim the lights', 'lights to 30%',
    'make the lights blue' — the lights tool, straight away."""
    from .. import lights
    if not lights.configured():
        return None

    def act(**args) -> QuickAction:
        name = (args.pop("name", "") or "").strip()
        return QuickAction("lights", {**args, "light": name}, "")

    if m := (re.fullmatch(rf"(?:turn|switch|put) {_L} (?P<p>on|off)", low)
             or re.fullmatch(rf"(?:turn|switch) (?P<p>on|off) {_L}", low)
             or re.fullmatch(rf"{_L} (?P<p>on|off)", low)):
        return act(power=m.group("p"), name=m.group("name"))
    if m := re.fullmatch(rf"(?:set |turn |put |dim |change )?{_L} (?:to |at |on )?(?P<n>\d{{1,3}})\s*(?:%|percent)?", low):
        return act(brightness=int(m.group("n")), name=m.group("name"))
    if m := re.fullmatch(rf"dim {_L}(?: a bit| a little)?", low):
        return act(change=-30, name=m.group("name"))
    if m := (re.fullmatch(rf"(?:brighten|turn up) {_L}(?: a bit| a little)?", low)
             or re.fullmatch(rf"{_L} (?:brighter|up)", low)):
        return act(change=30, name=m.group("name"))
    if m := (re.fullmatch(rf"{_L} (?:dimmer|down)", low) or re.fullmatch(rf"turn down {_L}", low)):
        return act(change=-30, name=m.group("name"))
    if m := re.fullmatch(rf"(?:make|turn|set|change|put) {_L} (?:to |on )?(?P<c>[a-z ]+?|#[0-9a-f]{{6}}|\d{{4}}k?)", low):
        if lights.parse_color(m.group("c")):
            return act(color=m.group("c"), name=m.group("name"))
    return None


_PHONE = r"(?: on telegram| via telegram| on my phone| to my phone| as a (?:text|message|telegram message))?"
_IT = r"(?:it|that|this|the (?:answer|reply|last (?:answer|message|reply)))"
_CHAT = r"(?:the |this |our |my )?(?:whole |entire |full )?(?:chat|conversation)(?: history)?"
_DOC = r"(?:a )?(?:word )?(?:doc|document|docx)"
_PHOTO_REF = r"(?:the |that |this |my |the last |that last )(?:picture|photo|pic|selfie|photograph)"


def _send_to_me(low: str) -> QuickAction | None:
    """Sending to the user's phone (Telegram). The reply is the tool's own
    words, so "Telegram isn't set up" is said instead of a cheerful "Sent"."""
    if re.fullmatch(rf"send (?:me )?{_PHOTO_REF}(?: (?:back |over )?to me)?{_PHONE}", low):
        return QuickAction("send_to_phone", {"what": "photo"}, "")
    if re.fullmatch(rf"send {_IT}(?: back| over)?(?: to me)?{_PHONE}|send me {_IT}{_PHONE}"
                    rf"|text (?:it|that) to me|text me (?:it|that)", low):
        return QuickAction("send_to_phone", {"what": "last_answer"}, "")
    if re.fullmatch(rf"send (?:me )?{_CHAT}(?: to me)?{_PHONE}", low):
        return QuickAction("send_to_phone", {"what": "conversation"}, "")
    if m := re.fullmatch(rf"(?:put|save|turn|make|write) ({_IT}|{_CHAT}) (?:in|into|as|to) {_DOC}"
                         rf"(?:,)?(?: and)? send (?:it|that)(?: to me)?{_PHONE}"
                         rf"|send ({_IT}|{_CHAT})(?: to me)? as {_DOC}{_PHONE}", low):
        what = "conversation" if re.search(r"chat|conversation", m.group(1) or m.group(2) or "") else "last_answer"
        return QuickAction("send_to_phone", {"what": what, "as_document": True}, "")
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
    if "{output}" in action.reply:
        return action.reply.format(output=_tidy_number(output.strip()))
    return action.reply


def _tidy_number(text: str) -> str:
    """397.80000000000001 -> 397.8, 1200.0 -> 1,200"""
    try:
        value = float(text)
    except ValueError:
        return text
    if value == int(value) and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def enabled() -> bool:
    return bool(settings.get("assistant.instant_commands", True))

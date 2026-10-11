"""Apple Music agent — controls the Music app via AppleScript.

Session-aware: never relaunches Music if it's already running; playback
commands act on the current session.
"""
from __future__ import annotations

import asyncio
import re
import subprocess

from ..base import tool


def _osascript(script: str, timeout: int = 20) -> str:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err = r.stderr.strip()
        if "1002" in err or "not authorized" in err.lower():
            return ("Not allowed to control Music yet — macOS will show a permission "
                    "prompt; ask the user to click OK and retry.")
        return f"Music error: {err}"
    return r.stdout.strip() or "OK"


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# --- the Apple Music catalogue -------------------------------------------------------
#
# AppleScript can only play songs in the user's library. For anything else the
# song is found with Apple's public search, opened in Music (in the background)
# and queued with the song's own "Play Next" menu through Accessibility, then
# skipped to — so exactly that song plays, and nothing is added to the library.
# Checked by name afterwards; Music reports what's playing.

def _country() -> str:
    try:
        from Foundation import NSLocale
        return (NSLocale.currentLocale().countryCode() or "us").lower()
    except Exception:
        return "us"


def _norm(text: str) -> str:
    text = re.sub(r"\(.*?\)|\[.*?\]|\ufffc", " ", (text or "").lower())
    return re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", text).strip()


def best_match(query: str, hits: list[dict]) -> dict | None:
    """The search result that best fits what was asked ('janice stfu by drake')."""
    words = set(_norm(query.replace(" by ", " ")).split())
    def score(h: dict) -> tuple:
        title, artist = _norm(h.get("trackName", "")), _norm(h.get("artistName", ""))
        overlap = len(words & set(f"{title} {artist}".split()))
        exact = title in _norm(query)
        return (exact, overlap)
    ranked = sorted(enumerate(hits), key=lambda ih: (*score(ih[1]), -ih[0]), reverse=True)
    return ranked[0][1] if ranked and score(ranked[0][1])[1] else None


async def catalog_search(query: str, limit: int = 10) -> list[dict]:
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://itunes.apple.com/search", params={
            "term": query, "entity": "song", "limit": limit, "country": _country()})
        r.raise_for_status()
    return [h for h in r.json().get("results", []) if h.get("isStreamable", True)]


def _ax():
    import ApplicationServices as AS
    from AppKit import NSWorkspace
    app = next((a for a in NSWorkspace.sharedWorkspace().runningApplications()
                if a.bundleIdentifier() == "com.apple.Music"), None)
    return AS, (AS.AXUIElementCreateApplication(app.processIdentifier()) if app else None)


def _attr(AS, e, name):
    err, v = AS.AXUIElementCopyAttributeValue(e, name, None)
    return v if err == 0 else None


def _find_row(AS, app, title: str):
    """The table row (and its table) for this song on the page Music shows."""
    want = _norm(title)
    stack = [(w, 0) for w in (_attr(AS, app, "AXWindows") or [])]
    while stack:
        e, depth = stack.pop()
        if _attr(AS, e, "AXRole") == "AXRow":
            for cell in _attr(AS, e, "AXChildren") or []:
                for t in _attr(AS, cell, "AXChildren") or []:
                    v = _attr(AS, t, "AXValue")
                    if isinstance(v, str) and _norm(v) == want:
                        return e, _attr(AS, e, "AXParent")
            continue
        if depth < 30:
            stack.extend((c, depth + 1) for c in _attr(AS, e, "AXChildren") or [])
    return None, None


def _menu_item(AS, app, titles: tuple[str, ...]):
    """An enabled item of the open context menu (the menu bar has a greyed-out
    "Play Next" of its own, so it's skipped)."""
    stack = [(app, 0)]
    while stack:
        e, depth = stack.pop()
        role = _attr(AS, e, "AXRole")
        if role == "AXMenuBar":
            continue
        if (role == "AXMenuItem" and (_attr(AS, e, "AXTitle") or "").lower() in titles
                and _attr(AS, e, "AXEnabled")):
            return e
        if depth < 9:
            stack.extend((c, depth + 1) for c in _attr(AS, e, "AXChildren") or [])
    return None


def _queue_and_play(title: str, wait: float = 15.0) -> str:
    """Queue the song shown in Music with its own Play Next, then skip to it."""
    import time
    AS, app = _ax()
    if not AS.AXIsProcessTrusted():
        return "NEEDS_ACCESSIBILITY"
    deadline = time.time() + wait
    row = table = None
    while time.time() < deadline:
        AS, app = _ax()
        if app is not None:
            row, table = _find_row(AS, app, title)
            if row is not None:
                break
        time.sleep(0.4)
    if row is None:
        return "NO_ROW"
    AS.AXUIElementSetAttributeValue(row, "AXSelected", True)
    AS.AXUIElementPerformAction(table, "AXShowMenu")
    item = None
    for _ in range(25):
        time.sleep(0.1)
        if item := _menu_item(AS, app, ("play next",)):
            break
    if item is None:
        return "NO_MENU"
    AS.AXUIElementPerformAction(item, "AXPress")
    time.sleep(0.4)
    _osascript('tell application "Music" to next track')
    _osascript('tell application "Music" to play')
    for _ in range(25):
        time.sleep(0.2)
        now = _osascript('tell application "Music" to get name of current track')
        if _norm(now) == _norm(title):
            return "OK"
    return "WRONG:" + now


async def play_from_catalog(query: str) -> str:
    try:
        hits = await catalog_search(query)
    except Exception as e:
        return f"Couldn't search Apple Music: {e}"
    song = best_match(query, hits)
    if song is None:
        return f"Couldn't find “{query}” on Apple Music."
    title, artist = song["trackName"], song["artistName"]
    url = f"music://music.apple.com/{_country()}/album/{song['collectionId']}?i={song['trackId']}"
    subprocess.run(["open", "-g", url], timeout=15)
    result = await asyncio.to_thread(_queue_and_play, title)
    if result == "OK":
        return f"Playing {title} by {artist} from Apple Music."
    if result == "NEEDS_ACCESSIBILITY":
        return (f"I opened {title} by {artist} in Music, but I need Accessibility permission "
                "to start it — press play, or allow Jarvis in Setup check.")
    return (f"I opened {title} by {artist} in Music but couldn't start it myself "
            f"({result.lower().replace('_', ' ')}) — it's on screen to press play.")


@tool(
    name="music_play",
    description="Play a song, artist or album on Apple Music (the user subscribes): from "
                "their library when it's there, otherwise from the whole Apple Music "
                "catalogue. Without a query it resumes playback. Use for 'play X' unless "
                "they ask for YouTube.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string",
                                 "description": "song and/or artist, e.g. 'janice stfu by drake'; "
                                                "empty = resume"}},
    },
    agent_tags=["automation", "music"],
)
async def music_play(query: str = "") -> str:
    if not query:
        return await asyncio.to_thread(_osascript, 'tell application "Music" to play')
    script = f'''
    tell application "Music"
        set results to (search library playlist 1 for "{_q(query)}")
        if (count of results) = 0 then return "NOTFOUND"
        play item 1 of results
        set t to item 1 of results
        return "Playing " & (name of t) & " by " & (artist of t)
    end tell'''
    out = await asyncio.to_thread(_osascript, script)
    if out != "NOTFOUND":
        return out
    return await play_from_catalog(query)


@tool(
    name="music_control",
    description="Control Apple Music playback: pause, resume, next, previous, "
                "shuffle_on, shuffle_off, repeat_on, repeat_off, or 'status' for "
                "the current track.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["pause", "resume", "next", "previous", "shuffle_on",
                                "shuffle_off", "repeat_on", "repeat_off", "status"]},
        },
        "required": ["action"],
    },
    agent_tags=["automation", "music"],
)
def music_control(action: str) -> str:
    scripts = {
        "pause": 'tell application "Music" to pause',
        "resume": 'tell application "Music" to play',
        "next": 'tell application "Music" to next track',
        "previous": 'tell application "Music" to previous track',
        "shuffle_on": 'tell application "Music" to set shuffle enabled to true',
        "shuffle_off": 'tell application "Music" to set shuffle enabled to false',
        "repeat_on": 'tell application "Music" to set song repeat to all',
        "repeat_off": 'tell application "Music" to set song repeat to off',
        "status": 'tell application "Music"\n'
                  'if player state is playing then\n'
                  'return "Playing: " & (name of current track) & " by " & (artist of current track)\n'
                  'else\nreturn "Not playing (" & (player state as string) & ")"\nend if\nend tell',
    }
    if action not in scripts:
        return f"Unknown action '{action}'"
    return _osascript(scripts[action])


@tool(
    name="music_playlists",
    description="List the user's Apple Music playlists, or play one by name.",
    parameters={
        "type": "object",
        "properties": {
            "play": {"type": "string", "description": "playlist name to play; empty = just list"},
        },
    },
    agent_tags=["automation", "music"],
)
def music_playlists(play: str = "") -> str:
    if play:
        return _osascript(f'tell application "Music" to play playlist "{_q(play)}"')
    return _osascript('tell application "Music" to get name of playlists') or "No playlists."


@tool(
    name="music_create_playlist",
    description="Create a new empty playlist in Apple Music, optionally adding library "
                "songs to it by search query.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "add_songs_matching": {"type": "string",
                                   "description": "optional library search; matching songs are added"},
        },
        "required": ["name"],
    },
    risk="confirm",
    agent_tags=["automation", "music"],
)
def music_create_playlist(name: str, add_songs_matching: str = "") -> str:
    out = _osascript(
        f'tell application "Music" to make new user playlist with properties {{name:"{_q(name)}"}}')
    if out.startswith("Music error"):
        return out
    if add_songs_matching:
        add = _osascript(f'''
        tell application "Music"
            set results to (search library playlist 1 for "{_q(add_songs_matching)}")
            repeat with t in results
                duplicate t to user playlist "{_q(name)}"
            end repeat
            return "added " & (count of results) & " songs"
        end tell''')
        return f"Created playlist '{name}' ({add})."
    return f"Created playlist '{name}'."

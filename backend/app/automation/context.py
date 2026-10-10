"""Application Context Memory.

Snapshots what the user is doing right now — frontmost app, open browser
tabs, current music — so the assistant can CONTINUE in existing contexts
(reuse the YouTube tab, keep the Music session) instead of opening
duplicates. Read on demand; never cached longer than a few seconds.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time

from ..config import settings

_cache: dict = {"ts": 0.0, "data": {}, "ttl": 3.0}
CACHE_SECONDS = 3.0
# If collecting context is slow (Automation permission not granted yet, or
# osascript timing out), back off so we don't burn 40s per dashboard poll.
SLOW_BACKOFF_SECONDS = 120.0


def _osascript(script: str, timeout: int = 8) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def frontmost_app() -> str:
    return _osascript(
        'tell application "System Events" to get name of first application '
        'process whose frontmost is true')


def app_running(name: str) -> bool:
    """Is an app running? pgrep takes milliseconds; asking System Events via
    AppleScript takes a few hundred, and this runs on every browser action."""
    try:
        return subprocess.run(["pgrep", "-xq", name], timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return _osascript(f'tell application "System Events" to (name of processes) '
                          f'contains "{name}"') == "true"


def browser_name() -> str:
    """The browser to automate: the configured one, else whichever is running."""
    configured = settings.get("automation.browser", "")
    if configured:
        return configured
    for name in ("Safari", "Google Chrome"):
        if app_running(name):
            return name
    return "Safari"


def list_tabs(browser: str | None = None) -> list[dict]:
    """Tabs of the front window: [{index, title, url}]."""
    browser = browser or browser_name()
    if "Chrome" in browser:
        script = f'''
        set out to ""
        tell application "{browser}"
            if (count of windows) = 0 then return ""
            set i to 0
            repeat with t in tabs of front window
                set i to i + 1
                set out to out & i & "\\t" & (title of t) & "\\t" & (URL of t) & "\\n"
            end repeat
        end tell
        return out'''
    else:
        script = f'''
        set out to ""
        tell application "{browser}"
            if (count of windows) = 0 then return ""
            set i to 0
            repeat with t in tabs of front window
                set i to i + 1
                set out to out & i & "\\t" & (name of t) & "\\t" & (URL of t) & "\\n"
            end repeat
        end tell
        return out'''
    tabs = []
    for line in _osascript(script, timeout=10).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            tabs.append({"index": int(parts[0]), "title": parts[1], "url": parts[2]})
    return tabs


def music_state() -> dict:
    if not app_running("Music"):  # never launch Music just to ask about it
        return {"running": False}
    script = '''
    tell application "Music"
        if player state is playing then
            return "playing\\t" & (name of current track) & "\\t" & (artist of current track)
        else if player state is paused then
            try
                return "paused\\t" & (name of current track) & "\\t" & (artist of current track)
            on error
                return "paused\\t\\t"
            end try
        else
            return "stopped\\t\\t"
        end if
    end tell'''
    raw = _osascript(script)
    if not raw:
        return {"running": False}
    parts = (raw.split("\t") + ["", ""])[:3]
    return {"running": True, "state": parts[0], "track": parts[1], "artist": parts[2]}


_refresh_task: asyncio.Task | None = None


async def snapshot_nowait() -> dict:
    """Never block the chat: return the cached snapshot immediately and, if it
    is stale, refresh it in the background for the NEXT message."""
    global _refresh_task
    if not settings.get("context.enabled", True):
        return {"enabled": False}
    stale = time.time() - _cache["ts"] >= _cache["ttl"]
    if stale and (_refresh_task is None or _refresh_task.done()):
        _refresh_task = asyncio.create_task(snapshot(force=True))
    return _cache["data"] or {"enabled": True, "warming": True}


async def snapshot(force: bool = False) -> dict:
    """Full context snapshot, cached briefly. Runs in a thread (osascript is slow)."""
    if not settings.get("context.enabled", True):
        return {"enabled": False}
    now = time.time()
    if not force and now - _cache["ts"] < _cache["ttl"]:
        return _cache["data"]

    def collect() -> dict:
        browser = browser_name()
        return {
            "enabled": True,
            "frontmost_app": frontmost_app(),
            "browser": browser,
            "tabs": list_tabs(browser)[:15],
            "music": music_state(),
        }

    started = time.time()
    data = await asyncio.to_thread(collect)
    took = time.time() - started
    if took > 4 or not data.get("frontmost_app"):
        data["degraded"] = ("Automation permission missing or slow — grant your "
                            "terminal access to System Events/Safari/Music in "
                            "System Settings > Privacy & Security > Automation")
    _cache.update(ts=time.time(), data=data,
                  ttl=SLOW_BACKOFF_SECONDS if took > 4 else CACHE_SECONDS)
    return data


def summary_for_prompt(ctx: dict) -> str:
    """Compact context block injected into the system prompt."""
    if not ctx.get("enabled"):
        return ""
    lines = [f"Frontmost app: {ctx.get('frontmost_app') or 'unknown'}",
             f"Browser: {ctx.get('browser')}"]
    tabs = ctx.get("tabs") or []
    if tabs:
        lines.append("Open browser tabs (front window):")
        for t in tabs[:10]:
            lines.append(f"  {t['index']}. {t['title'][:60]} — {t['url'][:80]}")
    music = ctx.get("music") or {}
    if music.get("running") and music.get("track"):
        lines.append(f"Music app: {music['state']} — {music['track']} by {music['artist']}")
    return "\n".join(lines)


def context_json() -> str:
    return json.dumps(_cache["data"], indent=2) if _cache["data"] else "{}"

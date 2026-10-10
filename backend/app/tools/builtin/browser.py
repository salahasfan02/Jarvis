"""Interactive browser agent (Safari / Google Chrome via AppleScript).

Smart window rules are built into the tools themselves:
- browser_open REUSES an existing tab on the same site unless new_window=true.
- Nothing here ever creates a duplicate window on its own.

JavaScript execution (clicking, scrolling, media control) requires a one-time
browser setting; the tools return exact instructions when it's disabled:
  Safari:  Develop menu > Allow JavaScript from Apple Events
  Chrome:  View > Developer > Allow JavaScript from Apple Events
"""
from __future__ import annotations

import json
import subprocess
import urllib.parse

from ...automation import context
from ..base import tool


def _osascript(script: str, timeout: int = 15) -> tuple[bool, str]:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return False, r.stderr.strip()
    return True, r.stdout.strip()


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _js_in_tab(browser: str, tab_index: int, js: str) -> str:
    """Run JS in a specific tab of the front window."""
    if "Chrome" in browser:
        script = (f'tell application "{browser}" to execute tab {tab_index} '
                  f'of front window javascript "{_q(js)}"')
    else:
        script = (f'tell application "{browser}" to do JavaScript "{_q(js)}" '
                  f'in tab {tab_index} of front window')
    ok, out = _osascript(script, timeout=20)
    if not ok:
        if "12" in out or "not allowed" in out.lower() or "javascript" in out.lower():
            menu = ("Develop menu > Allow JavaScript from Apple Events" if "Chrome" not in browser
                    else "View > Developer > Allow JavaScript from Apple Events")
            return (f"JavaScript control is disabled in {browser}. Ask the user to enable: "
                    f"{menu} (one-time setting), then retry.")
        return f"Browser scripting error: {out}"
    return out or "OK"


def _find_tab(site_hint: str) -> tuple[str, int] | None:
    """Find an existing tab whose URL contains the hint. Returns (browser, index)."""
    browser = context.browser_name()
    for t in context.list_tabs(browser):
        if site_hint.lower() in t["url"].lower():
            return browser, t["index"]
    return None


def _focus_script(browser: str, index: int) -> str:
    if "Chrome" in browser:
        select = f"set active tab index of front window to {index}"
    else:
        select = f"set current tab of front window to tab {index} of front window"
    return f'tell application "{browser}"\n{select}\nactivate\nend tell'


def _focus_tab(browser: str, index: int) -> None:
    _osascript(_focus_script(browser, index))  # one osascript launch, not two


@tool(
    name="browser_tabs",
    description="List the open tabs in the user's browser (front window): index, title, URL. "
                "ALWAYS check this before opening a site — reuse an existing tab when one matches.",
    parameters={"type": "object", "properties": {}},
    agent_tags=["automation", "research", "browser"],
)
def browser_tabs() -> str:
    browser = context.browser_name()
    tabs = context.list_tabs(browser)
    if not tabs:
        return f"{browser} has no open tabs (or is not running)."
    return f"{browser} front window tabs:\n" + "\n".join(
        f"{t['index']}. {t['title'][:70]} — {t['url'][:100]}" for t in tabs)


@tool(
    name="browser_open",
    description="Open a URL in the browser. REUSES an existing tab that is already on the "
                "same site (never opens a duplicate); otherwise opens ONE new tab in the "
                "existing window. Only pass new_window=true if the user explicitly asked "
                "for a new window.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "new_window": {"type": "boolean", "description": "only if explicitly requested"},
        },
        "required": ["url"],
    },
    agent_tags=["automation", "research", "browser"],
)
def browser_open(url: str, new_window: bool = False) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    browser = context.browser_name()
    domain = urllib.parse.urlparse(url).netloc.replace("www.", "")

    if new_window:
        if "Chrome" in browser:
            ok, err = _osascript(f'tell application "{browser}" to make new window\n'
                                 f'tell application "{browser}" to set URL of active tab '
                                 f'of front window to "{_q(url)}"')
        else:
            ok, err = _osascript(f'tell application "{browser}" to make new document '
                                 f'with properties {{URL:"{_q(url)}"}}')
        _osascript(f'tell application "{browser}" to activate')
        return f"Opened {url} in a NEW {browser} window." if ok else f"Failed: {err}"

    # Each osascript launch costs ~0.1-0.3 s, so: one tab listing (skipped when
    # the browser isn't even running), then one script per outcome.
    tabs = context.list_tabs(browser) if context.app_running(browser) else []
    if not tabs:
        subprocess.run(["open", "-a", browser, url], timeout=10)
        return f"Opened {url} in {browser}."
    match = next((t for t in tabs if domain and domain in t["url"].lower()), None)
    if match:
        idx = match["index"]
        if urllib.parse.urlparse(url).path in ("", "/"):
            # "open youtube" with YouTube already open: just bring that tab
            # forward — don't reload it and stop whatever is playing.
            _osascript(_focus_script(browser, idx))
            return f"Switched to the existing {domain} tab (tab {idx})."
        _osascript(f'tell application "{browser}" to set URL of tab {idx} of front window '
                   f'to "{_q(url)}"\n' + _focus_script(browser, idx))
        return f"Reused the existing {domain} tab (tab {idx}) and navigated to {url}."
    ok, err = _osascript(f'tell application "{browser}"\n'
                         f'make new tab at end of tabs of front window with properties '
                         f'{{URL:"{_q(url)}"}}\nactivate\nend tell')
    return f"Opened {url} in a new tab of the existing window." if ok else f"Failed: {err}"


@tool(
    name="browser_read_page",
    description="Read the text content of a browser tab (default: the active site tab you "
                "were working with, or pass tab_index from browser_tabs).",
    parameters={
        "type": "object",
        "properties": {"tab_index": {"type": "integer"}},
    },
    risk="confirm",
    agent_tags=["automation", "research", "browser"],
)
def browser_read_page(tab_index: int = 0) -> str:
    browser = context.browser_name()
    if not tab_index:
        tabs = context.list_tabs(browser)
        if not tabs:
            return "No open tabs."
        tab_index = next((t["index"] for t in tabs), 1)
    text = _js_in_tab(browser, tab_index,
                      "document.body.innerText.slice(0, 6000)")
    return text[:6000]


@tool(
    name="browser_js",
    description="Run JavaScript in a browser tab to click buttons, scroll, fill forms, or "
                "control media. Use for interactions no other tool covers. Returns the "
                "script's result. Example: document.querySelector('video').pause()",
    parameters={
        "type": "object",
        "properties": {
            "javascript": {"type": "string"},
            "tab_index": {"type": "integer", "description": "from browser_tabs; 0 = active tab"},
        },
        "required": ["javascript"],
    },
    risk="dangerous",
    agent_tags=["automation", "browser"],
)
def browser_js(javascript: str, tab_index: int = 0) -> str:
    browser = context.browser_name()
    if not tab_index:
        tabs = context.list_tabs(browser)
        if not tabs:
            return "No open tabs."
        tab_index = tabs[0]["index"]
    return _js_in_tab(browser, tab_index, javascript)[:3000]


@tool(
    name="browser_close_tab",
    description="Close a browser tab by index (from browser_tabs).",
    parameters={
        "type": "object",
        "properties": {"tab_index": {"type": "integer"}},
        "required": ["tab_index"],
    },
    risk="confirm",
    agent_tags=["automation", "browser"],
)
def browser_close_tab(tab_index: int) -> str:
    browser = context.browser_name()
    ok, err = _osascript(f'tell application "{browser}" to close tab {tab_index} of front window')
    return f"Closed tab {tab_index}." if ok else f"Failed: {err}"


# --- YouTube agent -------------------------------------------------------------

@tool(
    name="youtube_play",
    description="Search YouTube and play the first matching video. REUSES the existing "
                "YouTube tab if one is open (never opens a second YouTube window). "
                "Use for 'play X', 'put on some Y music', etc.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "what to search and play"}},
        "required": ["query"],
    },
    agent_tags=["automation", "browser"],
)
def youtube_play(query: str) -> str:
    import re

    import httpx
    # Find the first video id via the search page (no API key needed).
    try:
        r = httpx.get("https://www.youtube.com/results",
                      params={"search_query": query},
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        m = re.search(r'"videoId":"([\w-]{11})"', r.text)
    except httpx.HTTPError as e:
        return f"Could not search YouTube: {e}"
    if not m:
        return f"No YouTube results found for '{query}'."
    url = f"https://www.youtube.com/watch?v={m.group(1)}"

    browser = context.browser_name()
    found = _find_tab("youtube.com")
    if found:
        b, idx = found
        _osascript(f'tell application "{b}" to set URL of tab {idx} of front window to "{_q(url)}"')
        _focus_tab(b, idx)
        return f"Playing '{query}' in the existing YouTube tab: {url}"
    return browser_open(url) + f" (playing '{query}')"


@tool(
    name="youtube_control",
    description="Control the video in the open YouTube tab: play, pause, skip (next video), "
                "mute, unmute, fullscreen_off, or seek_forward/seek_back (10s).",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["play", "pause", "skip", "mute", "unmute",
                                "seek_forward", "seek_back"]},
        },
        "required": ["action"],
    },
    agent_tags=["automation", "browser"],
)
def youtube_control(action: str) -> str:
    found = _find_tab("youtube.com")
    if not found:
        return "No YouTube tab is open."
    browser, idx = found
    js = {
        "play": "document.querySelector('video').play(); 'playing'",
        "pause": "document.querySelector('video').pause(); 'paused'",
        "skip": "document.querySelector('.ytp-next-button')?.click(); 'skipped'",
        "mute": "document.querySelector('video').muted = true; 'muted'",
        "unmute": "document.querySelector('video').muted = false; 'unmuted'",
        "seek_forward": "document.querySelector('video').currentTime += 10; 'seeked'",
        "seek_back": "document.querySelector('video').currentTime -= 10; 'seeked'",
    }.get(action)
    if not js:
        return f"Unknown action '{action}'"
    return _js_in_tab(browser, idx, js)

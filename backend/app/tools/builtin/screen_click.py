"""Clicking things on screen — "press Sign in", "click the second video".

Works without any browser setting: the screen is read with Apple's Vision
OCR (the Live Text engine), the requested text is located, and a real mouse
click is posted there with Quartz. Web pages first try a DOM click (exact,
works even when the button is scrolled off-screen) and fall back to this
when the browser blocks JavaScript from Apple Events.

Needs two macOS permissions for the app running Jarvis: Screen Recording
(to see) and Accessibility (to click). Both failures return clear steps.
"""
from __future__ import annotations

import asyncio
import ctypes
import difflib
import json
import subprocess
import time

from ...automation import context
from ...ui_bridge import screen_activity_sync
from ..base import tool
from .browser import _focus_tab, _js_in_tab, _osascript, _q

_PERMS = "System Settings → Privacy & Security"
_NOT_SEEN = "I couldn't see"
_BROWSERS = ("Safari", "Google Chrome", "Arc", "Microsoft Edge", "Brave Browser", "Firefox")


def _accessibility_ok() -> bool:
    try:
        ax = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(ax.AXIsProcessTrusted())
    except OSError:
        return True   # can't tell — try anyway


def _score(text: str, want: str) -> float:
    """1.0 = the label is exactly the target; lower for looser matches."""
    t = text.lower().strip()
    if t == want:
        return 1.0
    if want in t:
        # "Sign in" inside "Sign in with Google" beats it inside a paragraph
        return 0.6 + 0.35 * len(want) / len(t)
    ratio = difflib.SequenceMatcher(None, t, want).ratio()
    return ratio * 0.85 if ratio >= 0.8 else 0.0


def _front_window() -> tuple[float, float, float, float] | None:
    """Bounds (x, y, w, h) of the frontmost normal window, in screen points."""
    import Quartz
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []
    for w in info:
        if w.get("kCGWindowLayer") == 0 and w.get("kCGWindowBounds"):
            b = w["kCGWindowBounds"]
            return b["X"], b["Y"], b["Width"], b["Height"]
    return None


def _find_on_screen(target: str) -> list[tuple[float, str, float, float]]:
    """All matches of `target` on every display: (score, text, x, y) in
    global screen points, best first; among equals, ones in the front window
    (what the user is looking at) first, then top-to-bottom."""
    import Quartz
    from ...vision.ocr import text_boxes

    want = target.lower().strip()
    err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
    hits = []
    for display in list(ids or [])[:count]:
        image = Quartz.CGDisplayCreateImage(display)
        if image is None:
            continue
        b = Quartz.CGDisplayBounds(display)
        for text, (x, y, w, h) in text_boxes(image, want):
            s = _score(text, want)
            if s > 0:
                hits.append((s, text, b.origin.x + (x + w / 2) * b.size.width,
                             b.origin.y + (y + h / 2) * b.size.height))
    front = _front_window()

    def outside(m) -> bool:
        if not front:
            return False
        fx, fy, fw, fh = front
        return not (fx <= m[2] <= fx + fw and fy <= m[3] <= fy + fh)
    hits.sort(key=lambda m: (-round(m[0], 2), outside(m), m[3], m[2]))
    return hits


def _click_at(x: float, y: float, double: bool = False) -> None:
    """Post a real-looking click: glide in (so the page sees the pointer
    arrive and hover), pause, then press and release with a human hold."""
    import Quartz
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)

    def post(kind, point, clicks=0):
        ev = Quartz.CGEventCreateMouseEvent(src, kind, point, Quartz.kCGMouseButtonLeft)
        if clicks:
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, clicks)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    for dx in (12, 6, 0):
        post(Quartz.kCGEventMouseMoved, (x - dx, y - dx / 2))
        time.sleep(0.03)
    time.sleep(0.15)
    for n in (1, 2) if double else (1,):
        post(Quartz.kCGEventLeftMouseDown, (x, y), n)
        time.sleep(0.06)
        post(Quartz.kCGEventLeftMouseUp, (x, y), n)
        time.sleep(0.08)


def _activate(app: str) -> None:
    subprocess.run(["osascript", "-e", f'tell application "{_q(app)}" to activate'],
                   capture_output=True, timeout=10)
    time.sleep(0.5)   # let the window come forward before looking


def screen_click(target: str, occurrence: int = 1, double: bool = False) -> str:
    """Find `target` text on screen and click it (blocking)."""
    if not target.strip():
        return "Say what to click (the text on the button or link)."
    from ...ui_bridge import control_blocked
    if control_blocked():
        return "Stopped — the user pressed the emergency stop. Don't continue."
    from ...automation import guard
    if reason := guard.check():
        return reason
    if not _accessibility_ok():
        return ("I can see the screen but macOS won't let me click yet. Ask the user to "
                f"allow Jarvis (or the Terminal running it) in {_PERMS} → Accessibility, "
                "then try again.")
    with screen_activity_sync("controlling"):   # frame around the screen meanwhile
        return _find_and_click(target, occurrence, double)


def _find_and_click(target: str, occurrence: int, double: bool) -> str:
    try:
        hits = _find_on_screen(target)
    except Exception as e:
        return (f"Couldn't read the screen ({e}). Jarvis needs {_PERMS} → Screen Recording.")
    if not hits:
        return (f"{_NOT_SEEN} '{target}' on screen. It may be scrolled out of view or "
                "an icon without text — tell the user, or scroll and try again.")
    best = round(hits[0][0], 2)
    same = [h for h in hits if round(h[0], 2) >= best - 0.05]
    pick = same[min(max(occurrence, 1), len(same)) - 1]
    _click_at(pick[2], pick[3], double)
    note = ""
    if len(same) > 1:
        note = (f" ({len(same)} matches on screen; clicked number {same.index(pick) + 1} from "
                "the top — pass occurrence to pick another)")
    return f"Clicked '{pick[1]}'{note}."


@tool(
    name="click_on_screen",
    description="Click something visible on the Mac's screen by its text — a button, link, "
                "menu item or label in ANY app (\"press Sign in\", \"click Accept\"). "
                "Optionally bring an app to the front first. For web pages prefer "
                "browser_click. Never tell the user you can't click — use this.",
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "the text shown on what to click"},
            "app": {"type": "string", "description": "optional app to bring forward first"},
            "occurrence": {"type": "integer",
                           "description": "which match, counting from the top (default 1)"},
            "double": {"type": "boolean", "description": "double-click (e.g. open a file)"},
        },
        "required": ["target"],
    },
    risk="confirm",
    agent_tags=["automation", "browser", "vision"],
)
async def click_on_screen(target: str, app: str = "", occurrence: int = 1,
                          double: bool = False) -> str:
    if app:
        await asyncio.to_thread(_activate, app)
    return await asyncio.to_thread(screen_click, target, occurrence, double)


# Finds the best clickable element by its visible text / label and clicks it.
_DOM_CLICK = """(() => {
  const want = %s.toLowerCase().trim();
  const nth = %d;
  const sel = 'a,button,input[type=submit],input[type=button],[role=button],[role=link],' +
              '[role=tab],[role=menuitem],[role=option],summary,label,[onclick],[tabindex]';
  const label = (e) => (e.innerText || e.value || e.getAttribute('aria-label') ||
                        e.getAttribute('title') || e.getAttribute('alt') || '').trim().toLowerCase();
  const seen = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const els = [...document.querySelectorAll(sel)].filter(seen);
  let hits = els.filter((e) => label(e) === want);
  if (!hits.length) hits = els.filter((e) => label(e).includes(want))
                              .sort((a, b) => label(a).length - label(b).length);
  if (!hits.length) return 'NOT_FOUND';
  const el = hits[Math.min(nth, hits.length) - 1];
  el.scrollIntoView({block: 'center'});
  el.click();
  return 'CLICKED ' + (label(el).slice(0, 80) || el.tagName);
})()"""


@tool(
    name="browser_click",
    description="Click a button, link or tab on a web page by its text (\"press Subscribe\", "
                "\"click the first result\", \"click Sign in\"). Works on the front browser "
                "tab unless tab_index is given. Never tell the user you can't click — use this.",
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "the text on the button/link"},
            "tab_index": {"type": "integer", "description": "tab from browser_tabs (optional)"},
            "occurrence": {"type": "integer",
                           "description": "which match, counting from the top (default 1)"},
        },
        "required": ["target"],
    },
    risk="confirm",
    agent_tags=["automation", "browser"],
)
async def browser_click(target: str, tab_index: int = 0, occurrence: int = 1) -> str:
    browser = context.browser_name()

    def run() -> str:
        from ...automation import guard
        if reason := guard.app_reason(browser):
            return reason
        idx = tab_index
        tabs = context.list_tabs(browser)
        if idx:
            url = next((x["url"] for x in tabs if x["index"] == idx), "")
            if reason := guard.site_reason(url):
                return reason
            _focus_tab(browser, idx)
        else:
            prop = ("active tab index of front window" if "Chrome" in browser
                    else "index of current tab of front window")
            ok, out = _osascript(f'tell application "{browser}" to get {prop}')
            idx = int(out) if ok and out.isdigit() else 0
            url = next((x["url"] for x in tabs if x["index"] == idx), "")
            if reason := guard.site_reason(url):
                return reason
        if idx:
            js = _DOM_CLICK % (json.dumps(target), max(occurrence, 1))
            out = _js_in_tab(browser, idx, js)
            if out.startswith("CLICKED"):
                return f"Clicked '{out[8:]}' in {browser}."
        # JavaScript blocked (or no DOM match): click what's visible. First the
        # screen as the user sees it — the page may be in another browser —
        # then with the browser brought to the front.
        result = screen_click(target, occurrence)
        if tab_index:
            return result
        # Hidden behind another window: bring each running browser forward
        # in turn (the page may be in Chrome while Safari is the default).
        others = [b for b in _BROWSERS if b != browser and context.app_running(b)]
        for candidate in [browser] + others:
            if not result.startswith(_NOT_SEEN):
                break
            _activate(candidate)
            result = screen_click(target, occurrence)
        return result

    return await asyncio.to_thread(run)

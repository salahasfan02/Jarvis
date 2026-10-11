"""Full control of the Mac: press any button, fill in fields, type, use
keyboard shortcuts, scroll and drag.

Elements are found through the accessibility tree first (real labels, works
for icon-only buttons and fields; no mouse needed), then by reading the screen
(OCR) as a fallback. Everything shows the amber "controlling" frame, and the
emergency stop (Esc, or "Jarvis stop") halts it between steps.
"""
from __future__ import annotations

import asyncio
import time

from ...automation import ax, guard
from ...ui_bridge import control_blocked, screen_activity_sync
from ..base import tool
from .screen_click import _PERMS, _accessibility_ok, _activate, _click_at, _find_on_screen

STOPPED = "Stopped — the user pressed the emergency stop. Don't continue; tell them it stopped."
NO_AX = (f"macOS won't let Jarvis control apps yet. Ask the user to allow Jarvis (or the "
         f"Terminal running it) in {_PERMS} → Accessibility, then try again.")

# ---- keyboard ---------------------------------------------------------------------

KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
    "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21,
    "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31,
    "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41,
    "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
    "escape": 53, "esc": 53, "forwarddelete": 117, "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121, "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}
MODIFIERS = {"cmd": "Command", "command": "Command", "⌘": "Command", "shift": "Shift",
             "alt": "Alternate", "option": "Alternate", "opt": "Alternate",
             "ctrl": "Control", "control": "Control", "fn": "SecondaryFn"}


def _post_key(code: int, down: bool, flags: int = 0) -> None:
    import Quartz
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    ev = Quartz.CGEventCreateKeyboardEvent(src, code, down)
    Quartz.CGEventSetFlags(ev, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def press_combo(combo: str) -> str:
    """'cmd+shift+t', 'enter', 'esc' -> posted key events."""
    import Quartz
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return "No keys given."
    *mods, key = parts
    flags = 0
    for m in mods:
        if m not in MODIFIERS:
            return f"Unknown modifier '{m}' (use cmd, shift, option/alt, ctrl)."
        flags |= getattr(Quartz, f"kCGEventFlagMask{MODIFIERS[m]}")
    if key not in KEYCODES:
        return f"Unknown key '{key}'."
    _post_key(KEYCODES[key], True, flags)
    time.sleep(0.02)
    _post_key(KEYCODES[key], False, flags)
    return ""


def type_unicode(text: str) -> bool:
    """Type text as keystrokes (any characters, any keyboard layout). Returns
    False when stopped part-way."""
    import Quartz
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for i in range(0, len(text), 16):
        if control_blocked():
            return False
        chunk = text[i:i + 16]
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(src, 0, down)
            # No modifiers: inherited flags (e.g. Cmd right after Cmd+A) made
            # apps treat the text as shortcuts, so nothing was typed.
            Quartz.CGEventSetFlags(ev, 0)
            Quartz.CGEventKeyboardSetUnicodeString(ev, len(chunk), chunk)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.012)
    return True


# ---- finding things ------------------------------------------------------------------

def _locate(target: str, app: str, occurrence: int = 1, roles=None):
    """(element-or-None, (x, y)-or-None, how, alternatives) — AX first, then OCR."""
    el, alts, _ = ax.find(target, app, roles=roles, occurrence=occurrence)
    if el is not None:
        return el, el.center, "accessibility", alts
    hits = _find_on_screen(target)
    if hits:
        best = round(hits[0][0], 2)
        same = [h for h in hits if round(h[0], 2) >= best - 0.05]
        h = same[min(max(occurrence, 1), len(same)) - 1]
        return None, (h[2], h[3]), "screen", same
    return None, None, "", []


def _guard(app: str = "") -> str:
    if control_blocked():
        return STOPPED
    if not _accessibility_ok():
        return NO_AX
    return guard.check(app)   # off-limits apps and sites


# ---- tools ------------------------------------------------------------------------------

@tool(
    name="ui_elements",
    description="List the buttons, links, fields, tabs and menu items of an app's front "
                "window (default: the frontmost app) with their labels — including "
                "icon-only buttons. Use it to see what can be pressed or filled before "
                "ui_press / ui_type, or to find a control by its exact name.",
    parameters={"type": "object", "properties": {
        "app": {"type": "string", "description": "app name, e.g. Safari, Finder (optional)"},
        "query": {"type": "string", "description": "only show elements whose label contains this"},
    }},
    agent_tags=["automation", "browser"],
)
def ui_elements(app: str = "", query: str = "") -> str:
    if not ax.trusted():
        return NO_AX
    if reason := guard.check(app):
        return reason
    if app:
        _activate(app)
    els, name = ax.elements(app, include_menus=False)
    if not els:
        return f"No controls found in {name or app or 'the front app'} (is a window open?)."
    if query:
        els = [e for e in els if query.lower() in e.label.lower()] or els
    lines = [f"{i}. {e.describe()}" for i, e in enumerate(els[:80], 1)]
    more = f"\n… {len(els) - 80} more (use query to narrow)" if len(els) > 80 else ""
    return f"{name or app} — {len(els)} controls:\n" + "\n".join(lines) + more


@tool(
    name="ui_press",
    description="Press a button, link, tab, checkbox or menu item in any app by its label "
                "(\"Send\", \"Back\", \"New Folder\", \"Accept all\"). Works for icon-only "
                "buttons too. Brings the app forward first if given. Use this to click "
                "anything; never tell the user you can't.",
    parameters={"type": "object", "properties": {
        "target": {"type": "string", "description": "the control's label or visible text"},
        "app": {"type": "string", "description": "app to act in (optional; default front app)"},
        "occurrence": {"type": "integer", "description": "which match from the top (default 1)"},
    }, "required": ["target"]},
    risk="confirm",
    agent_tags=["automation", "browser"],
)
async def ui_press(target: str, app: str = "", occurrence: int = 1) -> str:
    def run() -> str:
        if err := _guard(app):
            return err
        if app:
            _activate(app)
        with screen_activity_sync("controlling"):
            el, point, how, alts = _locate(target, app, occurrence)
            if point is None:
                return (f"I couldn't find '{target}'. Call ui_elements to see the exact "
                        "control names, or scroll if it's off-screen.")
            if el is not None and el.role not in ("AXTextField", "AXTextArea") and ax.press(el):
                done = f"Pressed {el.describe()}"
            else:
                _click_at(*point)
                done = f"Clicked '{getattr(el, 'label', '') or target}' ({how})"
            note = (f" — {len(alts)} matches; pressed number {min(max(occurrence, 1), len(alts))} "
                    "from the top" if len(alts) > 1 else "")
            return done + note + "."
    return await asyncio.to_thread(run)


@tool(
    name="ui_type",
    description="Type text. With `field`, first finds that text field by its label or "
                "placeholder (\"Search\", \"To\", \"Email\") and fills it; without, types "
                "where the cursor is. submit=true presses Return afterwards. Never type "
                "passwords or card numbers.",
    parameters={"type": "object", "properties": {
        "text": {"type": "string"},
        "field": {"type": "string", "description": "label/placeholder of the field (optional)"},
        "app": {"type": "string", "description": "app to type in (optional)"},
        "submit": {"type": "boolean", "description": "press Return after typing"},
        "replace": {"type": "boolean", "description": "clear the field first (default true)"},
    }, "required": ["text"]},
    risk="confirm",
    agent_tags=["automation", "browser"],
)
async def ui_type(text: str, field: str = "", app: str = "", submit: bool = False,
                  replace: bool = True) -> str:
    def run() -> str:
        if err := _guard(app):
            return err
        if app:
            _activate(app)
        with screen_activity_sync("controlling"):
            where = "the focused field"
            if field:
                el, point, how, _ = _locate(field, app, roles=ax.TEXT_INPUTS | {"AXSecureTextField"})
                if point is None:
                    return f"I couldn't find a field called '{field}'. Call ui_elements to see the fields."
                if el is not None and el.role == "AXSecureTextField":
                    return "That's a password field — the user must type passwords themselves."
                if el is None or not ax.focus(el):
                    _click_at(*point)
                time.sleep(0.15)
                where = f"'{field}'"
            if replace and field:
                press_combo("cmd+a")
                time.sleep(0.05)
            if not type_unicode(text):
                return STOPPED
            if submit:
                time.sleep(0.1)
                press_combo("return")
            return f"Typed {len(text)} characters into {where}" + (" and pressed Return." if submit else ".")
    return await asyncio.to_thread(run)


@tool(
    name="press_keys",
    description="Press a key or keyboard shortcut in the front app: 'cmd+t', 'cmd+shift+n', "
                "'enter', 'esc', 'tab', 'down', 'cmd+w', 'space'. Several presses: "
                "comma-separated ('down, down, enter').",
    parameters={"type": "object", "properties": {
        "keys": {"type": "string"},
        "app": {"type": "string", "description": "bring this app forward first (optional)"},
    }, "required": ["keys"]},
    risk="confirm",
    agent_tags=["automation", "browser"],
)
async def press_keys(keys: str, app: str = "") -> str:
    def run() -> str:
        if err := _guard(app):
            return err
        if app:
            _activate(app)
        with screen_activity_sync("controlling"):
            combos = [k.strip() for k in keys.split(",") if k.strip()]
            for combo in combos:
                if control_blocked():
                    return STOPPED
                if err := press_combo(combo):
                    return err
                time.sleep(0.08)
            return f"Pressed {', '.join(combos)}."
    return await asyncio.to_thread(run)


@tool(
    name="scroll",
    description="Scroll the window under the pointer or the front app: direction up/down/"
                "left/right, amount in 'pages' (default 1). Use to reveal things that are "
                "off-screen before pressing them.",
    parameters={"type": "object", "properties": {
        "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
        "amount": {"type": "number", "description": "pages to scroll (default 1)"},
        "app": {"type": "string", "description": "bring this app forward first (optional)"},
    }, "required": ["direction"]},
    agent_tags=["automation", "browser"],
)
async def scroll(direction: str, amount: float = 1, app: str = "") -> str:
    import Quartz

    def run() -> str:
        if err := _guard(app):
            return err
        if app:
            _activate(app)
        with screen_activity_sync("controlling"):
            # Scroll over the front window, not wherever the pointer happens to be.
            from .screen_click import _front_window
            front = _front_window()
            if front:
                x, y, w, h = front
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(
                    None, Quartz.kCGEventMouseMoved, (x + w / 2, y + h / 2), 0))
            lines = int(max(0.2, min(amount, 20)) * 12)
            dy = lines if direction == "up" else -lines if direction == "down" else 0
            dx = lines if direction == "left" else -lines if direction == "right" else 0
            for _ in range(lines // 3 or 1):
                if control_blocked():
                    return STOPPED
                ev = Quartz.CGEventCreateScrollWheelEvent(
                    None, Quartz.kCGScrollEventUnitLine, 2, int(dy and dy / abs(dy) * 3),
                    int(dx and dx / abs(dx) * 3))
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
                time.sleep(0.01)
            return f"Scrolled {direction}."
    return await asyncio.to_thread(run)


@tool(
    name="drag",
    description="Drag one thing onto another by their labels or visible text — e.g. a "
                "file onto a folder, a slider handle, a card to another list.",
    parameters={"type": "object", "properties": {
        "source": {"type": "string", "description": "what to pick up"},
        "destination": {"type": "string", "description": "where to drop it"},
        "app": {"type": "string", "description": "app to act in (optional)"},
    }, "required": ["source", "destination"]},
    risk="confirm",
    agent_tags=["automation"],
)
async def drag(source: str, destination: str, app: str = "") -> str:
    import Quartz

    def run() -> str:
        if err := _guard(app):
            return err
        if app:
            _activate(app)
        with screen_activity_sync("controlling"):
            _, a, _, _ = _locate(source, app)
            _, b, _, _ = _locate(destination, app)
            if a is None or b is None:
                missing = source if a is None else destination
                return f"I couldn't find '{missing}' on screen."
            src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)

            def post(kind, p):
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(
                    src, kind, p, Quartz.kCGMouseButtonLeft))
            post(Quartz.kCGEventMouseMoved, a)
            time.sleep(0.15)
            post(Quartz.kCGEventLeftMouseDown, a)
            time.sleep(0.2)
            for i in range(1, 31):
                if control_blocked():
                    post(Quartz.kCGEventLeftMouseUp, a)
                    return STOPPED
                post(Quartz.kCGEventLeftMouseDragged,
                     (a[0] + (b[0] - a[0]) * i / 30, a[1] + (b[1] - a[1]) * i / 30))
                time.sleep(0.015)
            time.sleep(0.15)
            post(Quartz.kCGEventLeftMouseUp, b)
            return f"Dragged '{source}' onto '{destination}'."
    return await asyncio.to_thread(run)

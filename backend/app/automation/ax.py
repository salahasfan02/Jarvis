"""The macOS accessibility tree: an app's real buttons, links, fields and menu
items with their labels and positions — what VoiceOver reads.

Better than OCR for controlling apps: icon-only buttons still have labels
("Close", "Back", "Search"), text fields can be found and filled directly, and
buttons can be pressed without moving the mouse.
"""
from __future__ import annotations

import difflib
import time
from dataclasses import dataclass, field

# Roles worth showing/acting on (the rest is layout scaffolding).
ACTIONABLE = {
    "AXButton", "AXLink", "AXTextField", "AXTextArea", "AXSearchField", "AXCheckBox",
    "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXMenuItem", "AXTab", "AXComboBox",
    "AXSlider", "AXDisclosureTriangle", "AXCell", "AXRow", "AXMenuBarItem", "AXSecureTextField",
}
_CHROMIUM = ("chrome", "edge", "brave", "arc", "opera", "vivaldi", "electron", "slack",
             "discord", "code", "notion", "spotify", "whatsapp")
TEXT_INPUTS = {"AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"}
ROLE_NAMES = {"AXButton": "button", "AXLink": "link", "AXTextField": "text field",
              "AXTextArea": "text area", "AXSearchField": "search field",
              "AXCheckBox": "checkbox", "AXRadioButton": "radio", "AXPopUpButton": "pop-up",
              "AXMenuButton": "menu button", "AXMenuItem": "menu item", "AXTab": "tab",
              "AXComboBox": "combo box", "AXSlider": "slider", "AXCell": "cell", "AXRow": "row",
              "AXDisclosureTriangle": "disclosure", "AXMenuBarItem": "menu",
              "AXSecureTextField": "password field"}


@dataclass
class Element:
    role: str
    label: str
    value: str
    x: float
    y: float
    w: float
    h: float
    enabled: bool
    ref: object = field(repr=False, default=None)

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    def describe(self) -> str:
        kind = ROLE_NAMES.get(self.role, self.role.removeprefix("AX").lower())
        text = f"{kind} '{self.label}'" if self.label else kind
        if self.value and self.role in TEXT_INPUTS | {"AXCheckBox", "AXSlider", "AXPopUpButton"}:
            text += f" = {self.value[:40]!r}"
        return text + ("" if self.enabled else " (disabled)")


def _AS():
    import ApplicationServices as AS
    return AS


def trusted() -> bool:
    try:
        return bool(_AS().AXIsProcessTrusted())
    except Exception:
        return False


def _attr(el, name):
    err, value = _AS().AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def _point(value, kind) -> tuple[float, float] | None:
    if value is None:
        return None
    ok, v = _AS().AXValueGetValue(value, kind, None)
    if not ok:
        return None
    return (v.x, v.y) if hasattr(v, "x") else (v.width, v.height)


def _text(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.startswith("<") and "AXValue" in s else s


def app_element(name: str = ""):
    """(AX element, app name) for the named app, or the frontmost app."""
    AS = _AS()
    from AppKit import NSWorkspace
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    if name:
        want = name.lower().strip()
        match = [a for a in apps if (a.localizedName() or "").lower() == want] or \
                [a for a in apps if want in (a.localizedName() or "").lower()]
        if not match:
            return None, name
        app = match[0]
        return AS.AXUIElementCreateApplication(app.processIdentifier()), app.localizedName()
    focused = _attr(AS.AXUIElementCreateSystemWide(), "AXFocusedApplication")
    if focused is None:
        return None, ""
    return focused, _text(_attr(focused, "AXTitle"))


def elements(app_name: str = "", limit: int = 300, include_menus: bool = False,
             deadline_s: float = 2.5) -> tuple[list[Element], str]:
    """Actionable elements in the app's focused window (plus its menu bar if
    asked), in reading order."""
    AS = _AS()
    app, name = app_element(app_name)
    if app is None:
        return [], name
    # Chrome/Electron only build the web page's tree when a screen reader
    # asks; this flag asks (harmless for other apps).
    AS.AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    roots = []
    window = _attr(app, "AXFocusedWindow") or _attr(app, "AXMainWindow")
    if window is not None:
        roots.append(window)
    if include_menus and (bar := _attr(app, "AXMenuBar")) is not None:
        roots.append(bar)
    out: list[Element] = []
    stop_at = time.time() + deadline_s
    stack = list(reversed(roots))
    seen = 0
    while stack and len(out) < limit and time.time() < stop_at:
        el = stack.pop()
        seen += 1
        role = _text(_attr(el, "AXRole"))
        if role in ACTIONABLE:
            label = (_text(_attr(el, "AXTitle")) or _text(_attr(el, "AXDescription"))
                     or _text(_attr(el, "AXPlaceholderValue")) or _text(_attr(el, "AXHelp")))
            value = _text(_attr(el, "AXValue"))
            if role in ("AXLink", "AXCell", "AXRow") and not label:
                label = value
            pos = _point(_attr(el, "AXPosition"), AS.kAXValueCGPointType)
            size = _point(_attr(el, "AXSize"), AS.kAXValueCGSizeType)
            if pos and size and size[0] > 1 and size[1] > 1 and (label or role in TEXT_INPUTS):
                enabled = _attr(el, "AXEnabled")
                out.append(Element(role, label[:120], value[:200], pos[0], pos[1], size[0],
                                   size[1], enabled is not False, el))
        if role in ("AXMenuItem", "AXMenuBarItem") and not include_menus:
            continue
        children = _attr(el, "AXChildren") or []
        stack.extend(reversed(list(children)))
    out.sort(key=lambda e: (round(e.y / 8), e.x))
    return out, name


def find(target: str, app_name: str = "", roles: set[str] | None = None,
         occurrence: int = 1) -> tuple[Element | None, list[Element], str]:
    """Best element for `target` (by label/value), the close alternatives, app."""
    els, name = elements(app_name, include_menus=True)
    if roles:
        els = [e for e in els if e.role in roles]
    want = target.lower().strip()
    if (not any(want in e.label.lower() for e in els)
            and any(b in name.lower() for b in _CHROMIUM)):
        # A browser builds its page tree ~2 s after first being asked.
        time.sleep(2.2)
        els, name = elements(app_name, include_menus=True)
        if roles:
            els = [e for e in els if e.role in roles]

    def score(e: Element) -> float:
        label = e.label.lower()
        if label == want:
            return 1.0
        if want and want in label:
            return 0.6 + 0.35 * len(want) / max(len(label), 1)
        r = difflib.SequenceMatcher(None, label, want).ratio()
        return r * 0.85 if r >= 0.75 else 0.0
    scored = sorted(((score(e), i, e) for i, e in enumerate(els) if score(e) > 0),
                    key=lambda t: (-round(t[0], 2), t[1]))
    if not scored:
        return None, [], name
    best = round(scored[0][0], 2)
    top = [e for s, _, e in scored if round(s, 2) >= best - 0.05]
    pick = top[min(max(occurrence, 1), len(top)) - 1]
    return pick, top, name


def press(el: Element) -> bool:
    AS = _AS()
    for action in ("AXPress", "AXConfirm", "AXPick"):
        if AS.AXUIElementPerformAction(el.ref, action) == 0:
            return True
    return False


def focus(el: Element) -> bool:
    return _AS().AXUIElementSetAttributeValue(el.ref, "AXFocused", True) == 0


def set_value(el: Element, text: str) -> bool:
    return _AS().AXUIElementSetAttributeValue(el.ref, "AXValue", text) == 0

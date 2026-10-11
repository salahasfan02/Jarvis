"""The user's own details, and filling in forms with them."""
from __future__ import annotations

import asyncio
import time

from ...automation import ax, guard
from ...config import settings
from ...memory import profile
from ...ui_bridge import control_blocked, screen_activity_sync
from ..base import tool
from .control import NO_AX, STOPPED, press_combo, type_unicode
from .screen_click import _activate


@tool(
    name="my_details",
    description="The user's own saved details (name, email, phone, address, company, "
                "email sign-off) — for filling in forms or writing on their behalf.",
    parameters={"type": "object", "properties": {}},
    agent_tags=["automation", "browser", "messaging", "email", "_conversation"],
)
def my_details() -> str:
    return profile.describe()


@tool(
    name="update_my_details",
    description="Save the user's own details when they tell you them (\"my address is …\", "
                "\"my phone number is …\"). Never store passwords, card or bank details.",
    parameters={"type": "object", "properties": {
        k: {"type": "string"} for k in profile.FIELDS}},
    agent_tags=["automation", "messaging", "email", "_conversation"],
)
def update_my_details(**details) -> str:
    clean = {k: str(v).strip() for k, v in details.items() if k in profile.FIELDS and str(v).strip()}
    if not clean:
        return "Nothing to save."
    settings.update({"profile": clean})
    return "Saved: " + ", ".join(f"{profile.FIELDS[k]} = {v}" for k, v in clean.items()) + "."


def _focused_is(app_el, el) -> bool:
    """Is `el` the element that has keyboard focus right now?"""
    focused = ax._attr(app_el, "AXFocusedUIElement")
    if focused is None:
        return False
    if focused == el.ref:
        return True
    # Web fields sometimes report a child/parent; compare by frame.
    pos = ax._point(ax._attr(focused, "AXPosition"), ax._AS().kAXValueCGPointType)
    return bool(pos) and abs(pos[0] - el.x) < 3 and abs(pos[1] - el.y) < 3


def fill(app: str, extra: dict[str, str], use_profile: bool = True) -> str:
    """Fill the front form (blocking). `extra`: label words -> value."""
    if control_blocked():
        return STOPPED
    if not ax.trusted():
        return NO_AX
    if reason := guard.check(app):
        return reason
    if app:
        _activate(app)
    els, name = ax.elements(app, include_menus=False, deadline_s=4, page_only=True)
    fields = [e for e in els if e.role in ax.TEXT_INPUTS or e.role == "AXSecureTextField"]
    if not fields:
        time.sleep(2.2)   # browsers build the page tree on first request
        els, name = ax.elements(app, include_menus=False, deadline_s=4, page_only=True)
        fields = [e for e in els if e.role in ax.TEXT_INPUTS or e.role == "AXSecureTextField"]
    if not fields:
        return f"I couldn't find a form in {name or 'the front window'}."
    details = profile.get() if use_profile else {}
    app_el, _ = ax.app_element(app)
    filled, skipped, never = [], [], []
    with screen_activity_sync("controlling"):
        for f in fields:
            label = f.label or ""
            if f.role == "AXSecureTextField" or profile.NEVER.search(label):
                never.append(label or "a password field")
                continue
            value = next((v for k, v in extra.items() if k and k.lower() in label.lower()), None)
            if value is None:
                key = profile.key_for(label)
                value = details.get(key) if key else None
            if not value:
                if label:
                    skipped.append(label)
                continue
            if control_blocked():
                return STOPPED
            ax.focus(f)
            time.sleep(0.12)
            if not _focused_is(app_el, f):
                from .screen_click import _click_at
                _click_at(*f.center)
                time.sleep(0.15)
            if not _focused_is(app_el, f):
                skipped.append(f"{label} (couldn't put the cursor there)")
                continue
            press_combo("cmd+a")
            time.sleep(0.04)
            if not type_unicode(value):
                return STOPPED
            filled.append(f"{label}: {value}")
            time.sleep(0.08)
    out = [f"Filled {len(filled)} field(s) in {name or 'the form'}:"] + [f"  • {x}" for x in filled]
    if skipped:
        out.append("Left empty (no matching detail): " + ", ".join(skipped))
    if never:
        out.append("Never filled by Jarvis: " + ", ".join(never))
    out.append("Nothing was submitted — the user should check it and press submit themselves.")
    return "\n".join(out)


@tool(
    name="fill_form",
    description="Fill in the form on screen (a web page or app window) with the user's saved "
                "details — name, email, phone, address, company… — plus any `extra` values "
                "for other fields (e.g. {\"message\": \"I'll be there\"}). Never fills "
                "passwords, card/bank details or ID numbers, and never submits.",
    parameters={"type": "object", "properties": {
        "app": {"type": "string", "description": "app with the form (optional: front app)"},
        "extra": {"type": "object", "description": "field label words -> value"},
        "use_profile": {"type": "boolean", "description": "use saved details (default true)"},
    }},
    risk="confirm",
    agent_tags=["automation", "browser"],
)
async def fill_form(app: str = "", extra: dict | None = None, use_profile: bool = True) -> str:
    return await asyncio.to_thread(fill, app, {str(k): str(v) for k, v in (extra or {}).items()},
                                   use_profile)

"""What "this" / "that" means right now.

"Email this to Sam", "summarize this", "what does this say?" refer to what
the user was looking at: the document open in the app they were using, the
page in their browser, files selected in Finder, or text they highlighted.
When Jarvis's own window is in front, the app before it counts.
"""
from __future__ import annotations

import re
import subprocess
import urllib.parse

from . import ax

# Words that point at something on screen. ("it" alone is too common — it
# usually means something from the conversation.)
DEICTIC = re.compile(
    r"\b(?:this|these|selected|highlighted|current)\b"
    r"|\bthat (?:file|page|document|doc|pdf|email|tab|photo|picture|image|video|text|link|site)\b"
    r"|\bwhat i(?:'m| am) (?:looking at|reading|on)\b", re.I)

BROWSERS = {"Safari", "Google Chrome", "Arc", "Microsoft Edge", "Brave Browser"}
OWN = {"Electron", "Jarvis"}   # Jarvis's own windows never count as "this"


def mentions_this(text: str) -> bool:
    return bool(DEICTIC.search(text))


def _run(script: str, timeout: float = 3) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        return ""


def user_app() -> str:
    """The app the user is working in (frontmost, skipping Jarvis itself)."""
    try:
        out = subprocess.run(["lsappinfo", "visibleProcessList"], capture_output=True,
                             text=True, timeout=2).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    for name in re.findall(r'"([^"]+)"', out):
        name = name.replace("_", " ")
        if name not in OWN:
            return name
    return ""


def _document(app: str) -> tuple[str, str]:
    """(file path of the front document, window title) via accessibility."""
    el, _ = ax.app_element(app)
    if el is None:
        return "", ""
    window = ax._attr(el, "AXFocusedWindow") or ax._attr(el, "AXMainWindow")
    if window is None:
        return "", ""
    title = ax._text(ax._attr(window, "AXTitle"))
    doc = ax._text(ax._attr(window, "AXDocument"))
    path = urllib.parse.unquote(doc[7:]) if doc.startswith("file://") else ""
    return path, title


def _selected_text(app: str) -> str:
    el, _ = ax.app_element(app)
    if el is None:
        return ""
    focused = ax._attr(el, "AXFocusedUIElement")
    return ax._text(ax._attr(focused, "AXSelectedText")) if focused is not None else ""


def _browser_page(app: str) -> tuple[str, str]:
    if "Safari" in app:
        out = _run(f'tell application "{app}" to return (name of current tab of front window) '
                   f'& linefeed & (URL of current tab of front window)')
    else:
        out = _run(f'tell application "{app}" to return (title of active tab of front window) '
                   f'& linefeed & (URL of active tab of front window)')
    title, _, url = out.partition("\n")
    return title.strip(), url.strip()


def _finder_selection() -> list[str]:
    out = _run('tell application "Finder"\nset out to ""\nrepeat with f in (selection as alias list)\n'
               'set out to out & POSIX path of f & linefeed\nend repeat\nreturn out\nend tell')
    return [line for line in out.splitlines() if line.strip()][:20]


def describe() -> str:
    """A short block for the model: what "this" most likely is."""
    app = user_app()
    if not app:
        return ""
    lines = [f"App the user is in: {app}"]
    try:
        if app == "Finder":
            picked = _finder_selection()
            if picked:
                lines.append("Selected in Finder:\n" + "\n".join(f"  {p}" for p in picked))
        elif app in BROWSERS:
            title, url = _browser_page(app)
            if url:
                lines.append(f"Browser page: {title} — {url}  (read it with browser_read_page)")
        else:
            path, title = _document(app)
            if path:
                lines.append(f"Open document: {path}  (read it with read_document; attach this path)")
            elif title:
                lines.append(f"Front window: {title}")
        text = _selected_text(app)
        if text.strip():
            lines.append(f"Highlighted text:\n\"\"\"\n{text.strip()[:3000]}\n\"\"\"")
    except Exception:
        pass
    if len(lines) == 1:
        lines.append("(nothing specific selected — if they mean the screen, use screen_read)")
    return "\n".join(lines)

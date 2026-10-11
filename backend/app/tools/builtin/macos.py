"""macOS automation via AppleScript / system commands.

Anything that changes state on the machine or could expose personal data is
risk-gated: the UI shows a confirmation dialog before it runs. iMessage is
draft-only (the user presses send). Email can be drafted, or — when the user
explicitly says send — sent after they approve that exact message.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..base import tool


def _osascript(script: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        app = re.search(r'tell application "([^"]+)"', script)
        name = app.group(1) if app else "The app"
        return (f"Failed: {name} didn't respond within {timeout} s — nothing was done. "
                f"macOS may be showing a dialog asking to let Jarvis control {name} "
                "(click OK), or the app is busy. Tell the user, then try again.")
    if result.returncode != 0:
        return f"AppleScript error: {result.stderr.strip()}"
    return result.stdout.strip() or "OK"


def _q(s: str) -> str:
    """Escape a string for embedding in an AppleScript double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


@tool(
    name="open_app",
    description="Open a macOS application by name, e.g. Safari, Notes, Terminal, Spotify.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "application name"}},
        "required": ["name"],
    },
    agent_tags=["automation"],
)
def open_app(name: str) -> str:
    result = subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return f"Could not open '{name}': {result.stderr.strip()}"
    return f"Opened {name}"


@tool(
    name="quit_app",
    description="Quit a running macOS application by name.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    risk="confirm",
    agent_tags=["automation"],
)
def quit_app(name: str) -> str:
    return _osascript(f'tell application "{_q(name)}" to quit')


@tool(
    name="open_url",
    description="Open a URL in the default browser.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    agent_tags=["automation", "research"],
)
def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    subprocess.run(["open", url], timeout=10)
    return f"Opened {url}"


@tool(
    name="notification",
    description="Show a macOS notification to the user.",
    parameters={
        "type": "object",
        "properties": {"title": {"type": "string"}, "message": {"type": "string"}},
        "required": ["title", "message"],
    },
    agent_tags=["automation"],
)
def notification(title: str, message: str) -> str:
    return _osascript(
        f'display notification "{_q(message)}" with title "{_q(title)}"')


@tool(
    name="clipboard_read",
    description="Read the current contents of the clipboard.",
    parameters={"type": "object", "properties": {}},
    risk="confirm",
    agent_tags=["automation"],
)
def clipboard_read() -> str:
    result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
    return result.stdout[:5000] or "(clipboard is empty)"


@tool(
    name="clipboard_write",
    description="Copy text to the clipboard.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    agent_tags=["automation"],
)
def clipboard_write(text: str) -> str:
    subprocess.run(["pbcopy"], input=text, text=True, timeout=5)
    return f"Copied {len(text)} characters to clipboard"


@tool(
    name="create_note",
    description="Create a new note in Apple Notes.",
    parameters={
        "type": "object",
        "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
        "required": ["title", "body"],
    },
    risk="confirm",
    agent_tags=["automation"],
)
def create_note(title: str, body: str) -> str:
    body_html = _q(body).replace("\n", "<br>")
    return _osascript(
        f'tell application "Notes" to make new note at folder "Notes" with properties '
        f'{{name:"{_q(title)}", body:"{body_html}"}}')


@tool(
    name="search_notes",
    description="Search Apple Notes by title/content and return matching note titles.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    risk="confirm",
    agent_tags=["automation", "notes"],
)
def search_notes(query: str) -> str:
    script = f'''
    set out to ""
    tell application "Notes"
        repeat with n in notes
            if (name of n as string) contains "{_q(query)}" or (plaintext of n) contains "{_q(query)}" then
                set out to out & "- " & (name of n) & "\\n"
                if (count of paragraphs of out) > 20 then exit repeat
            end if
        end repeat
    end tell
    return out'''
    result = _osascript(script, timeout=60)
    return result if result not in ("", "OK") else f"No notes matching '{query}'."


@tool(
    name="read_note",
    description="Read the full text of an Apple Note by its exact title.",
    parameters={
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    },
    risk="confirm",
    agent_tags=["automation", "notes"],
)
def read_note(title: str) -> str:
    out = _osascript(f'tell application "Notes" to get plaintext of note "{_q(title)}"', 30)
    return out[:6000]


@tool(
    name="append_note",
    description="Append text to the end of an existing Apple Note.",
    parameters={
        "type": "object",
        "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
        "required": ["title", "text"],
    },
    risk="confirm",
    agent_tags=["automation", "notes"],
)
def append_note(title: str, text: str) -> str:
    body_html = _q(text).replace("\n", "<br>")
    return _osascript(
        f'tell application "Notes" to set body of note "{_q(title)}" to '
        f'(body of note "{_q(title)}") & "<br>{body_html}"')


@tool(
    name="calendar_create_event",
    description="Create an event in Apple Calendar. Dates use 'YYYY-MM-DD HH:MM' 24h format.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
            "end": {"type": "string", "description": "YYYY-MM-DD HH:MM; default start + 1h"},
            "location": {"type": "string"},
        },
        "required": ["title", "start"],
    },
    risk="confirm",
    agent_tags=["automation", "calendar"],
)
def calendar_create_event(title: str, start: str, end: str = "", location: str = "") -> str:
    import datetime
    try:
        start_dt = datetime.datetime.strptime(start, "%Y-%m-%d %H:%M")
        end_dt = (datetime.datetime.strptime(end, "%Y-%m-%d %H:%M") if end
                  else start_dt + datetime.timedelta(hours=1))
    except ValueError:
        return "Invalid date format — use YYYY-MM-DD HH:MM."
    fmt = "%A, %B %d, %Y %H:%M:%S"  # AppleScript-friendly
    props = f'summary:"{_q(title)}", start date:startD, end date:endD'
    if location:
        props += f', location:"{_q(location)}"'
    script = f'''
    set startD to date "{start_dt.strftime(fmt)}"
    set endD to date "{end_dt.strftime(fmt)}"
    tell application "Calendar"
        tell calendar 1
            make new event with properties {{{props}}}
        end tell
    end tell
    return "created"'''
    out = _osascript(script, timeout=60)
    return (f"Created event '{title}' on {start}." if out == "created" else out)


@tool(
    name="create_reminder",
    description="Create a reminder in Apple Reminders. due is optional, format 'YYYY-MM-DD HH:MM'.",
    parameters={
        "type": "object",
        "properties": {"title": {"type": "string"}, "due": {"type": "string"}},
        "required": ["title"],
    },
    risk="confirm",
    agent_tags=["automation"],
)
def create_reminder(title: str, due: str = "") -> str:
    props = f'{{name:"{_q(title)}"}}'
    if due:
        return _osascript(
            f'set dueDate to date "{_q(due)}"\n'
            f'tell application "Reminders" to make new reminder with properties '
            f'{{name:"{_q(title)}", due date:dueDate}}')
    return _osascript(
        f'tell application "Reminders" to make new reminder with properties {props}')


@tool(
    name="draft_imessage",
    description="Open Messages with a drafted text to a recipient. The DRAFT is prepared "
                "but the user must press send themselves — this tool never sends.",
    parameters={
        "type": "object",
        "properties": {
            "recipient": {"type": "string", "description": "phone number or contact handle"},
            "body": {"type": "string"},
        },
        "required": ["recipient", "body"],
    },
    risk="confirm",
    agent_tags=["messaging"],
)
def draft_imessage(recipient: str, body: str) -> str:
    import urllib.parse
    url = f"sms:{urllib.parse.quote(recipient)}&body={urllib.parse.quote(body)}"
    subprocess.run(["open", url], timeout=10)
    return f"Opened Messages with a draft to {recipient}. The user must press send."


_EMAIL = re.compile(r"[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+")


def _addresses(field: str) -> list[str]:
    return [a.strip() for a in re.split(r"[,;]", field or "") if a.strip()]


def _mail_script(to: list[str], subject: str, body: str, cc: list[str],
                 attachments: list[Path], send: bool) -> str:
    """One AppleScript for Mail: build the message, then send it or save it
    as a draft (Drafts sync to the user's iPhone through their mail account)."""
    recipients = "\n".join(
        f'make new {kind} recipient at end of {kind} recipients with properties '
        f'{{address:"{_q(addr)}"}}'
        for kind, addrs in (("to", to), ("cc", cc)) for addr in addrs)
    files = "\n".join(
        f'make new attachment with properties {{file name:(POSIX file "{_q(str(f))}") '
        f'as alias}} at after the last paragraph' for f in attachments)
    attach_block = f"tell content\n{files}\nend tell" if files else ""
    finish = ("delay 1\nsend newMessage" if send else  # delay: let attachments load
              "try\nsave newMessage\nend try\nactivate")  # draft stays open for review
    return f"""
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{subject:"{_q(subject)}", content:"{_q(body)}" & return & return, visible:{'false' if send else 'true'}}}
        tell newMessage
            {recipients}
            {attach_block}
        end tell
        {finish}
    end tell
    return "ok\""""


def _email_parts(to: str, cc: str, attachments: list[str] | None
                 ) -> tuple[list[str], list[str], list[Path], str]:
    """Validate recipients and attachment paths. Returns (to, cc, files, error)."""
    to_list, cc_list = _addresses(to), _addresses(cc)
    if not to_list:
        return [], [], [], "No recipient given."
    # "Sam" / "my landlord" -> their saved (or Contacts) address.
    from ...memory import people
    for lst in (to_list, cc_list):
        for i, who in enumerate(lst):
            if _EMAIL.fullmatch(who):
                continue
            email, options = people.resolve_email(who)
            if email:
                lst[i] = email
            elif options:
                return [], [], [], (f"Several people could be '{who}' — ask the user which:\n"
                                    + "\n".join(people.describe(o) for o in options[:6]))
    bad = [a for a in to_list + cc_list if not _EMAIL.fullmatch(a)]
    if bad:
        return [], [], [], (f"Not an email address: {', '.join(bad)}. Find the address "
                            "(e.g. search the user's contacts or ask them) and try again.")
    files, error = resolve_attachments(attachments)
    if error:
        return [], [], [], error
    return to_list, cc_list, files, ""


def resolve_attachments(attachments: list[str] | str | None) -> tuple[list[Path], str]:
    """Attachment paths OR names ("my CV", "lease.pdf", the path
    create_word_document returned) -> files. Folders can't be attached."""
    from .documents import find_file
    if isinstance(attachments, str):   # models often pass one path as a plain string
        attachments = [attachments] if attachments.strip() else []
    files: list[Path] = []
    for item in attachments or []:
        p, candidates = find_file(item)
        if p is None:
            if candidates:
                return [], (f"Several files could be '{item}' — ask the user which one, "
                            "then retry with its full path:\n" + "\n".join(candidates))
            return [], f"Attachment not found: {item}."
        if p.is_dir():
            return [], f"{p} is a folder — attach the files inside it instead."
        files.append(p)
    return files, ""


_EMAIL_PARAMS = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "description": "email address(es), comma-separated — or "
                                         "a saved person's name/relation (\"Sam\", \"my landlord\")"},
        "subject": {"type": "string"},
        "body": {"type": "string", "description": "plain-text body, signed with the "
                                                  "user's name (no placeholders)"},
        "cc": {"type": "string", "description": "optional, comma-separated"},
        "attachments": {"type": "array", "items": {"type": "string"},
                        "description": "optional files to attach: full paths, or just the "
                                       "names the user said (\"my CV\") — they're found "
                                       "on the Mac. To send a new document, create it "
                                       "first (create_word_document) and attach that path."},
    },
    "required": ["to", "subject", "body"],
}


@tool(
    name="draft_email",
    description="DRAFT an email in Apple Mail without sending it: saves it to Drafts and "
                "opens it for the user to review. Use when the user says draft, write, "
                "prepare or compose an email. If they say SEND, use send_email instead.",
    parameters=_EMAIL_PARAMS,
    agent_tags=["email"],
)
def draft_email(to: str, subject: str, body: str, cc: str = "",
                attachments: list[str] | None = None) -> str:
    # Drafts may name a contact ("Mom"): Mail resolves names in the open window.
    files, error = resolve_attachments(attachments)
    if error:
        return error
    out = _osascript(_mail_script(_addresses(to) or [to], subject, body,
                                  _addresses(cc), files, send=False))
    if out != "ok":
        return out
    return (f"Drafted an email to {to} (subject: {subject}). It's saved in Mail's Drafts "
            "and open on the Mac — nothing was sent.")


@tool(
    name="send_email",
    description="SEND an email right away from the user's Apple Mail account. Use ONLY "
                "when the user explicitly asks to send (\"send an email to…\", \"email "
                "Sam that…\"); for draft/write/prepare use draft_email. Needs real email "
                "addresses. The user approves the exact message before it goes out.",
    parameters=_EMAIL_PARAMS,
    risk="confirm",
    always_ask=True,       # irreversible: approved every time, never auto-allowed
    agent_tags=["email"],
)
def send_email(to: str, subject: str, body: str, cc: str = "",
               attachments: list[str] | None = None) -> str:
    to_list, cc_list, files, error = _email_parts(to, cc, attachments)
    if error:
        return f"Not sent. {error}"
    out = _osascript(_mail_script(to_list, subject, body, cc_list, files, send=True),
                     timeout=60)
    if out != "ok":
        return f"Not sent — Mail reported: {out}"
    extra = f" with {len(files)} attachment(s)" if files else ""
    return f"Sent the email to {', '.join(to_list)}{extra} (subject: {subject})."


@tool(
    name="run_applescript",
    description="Run arbitrary AppleScript. Powerful — can control most Mac apps. "
                "Use only when no dedicated tool exists for the task.",
    parameters={
        "type": "object",
        "properties": {"script": {"type": "string"}},
        "required": ["script"],
    },
    risk="dangerous",
    agent_tags=["automation"],
)
def run_applescript(script: str) -> str:
    return _osascript(script, timeout=60)

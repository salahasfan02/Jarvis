"""Calls from the Mac: "FaceTime Salah's business number", "video call mum",
"FaceTime audio Sam", "phone the office through my iPhone".

The person is found the way email finds them — Jarvis's saved people first,
then the Mac's Contacts — but with every number and address they have and its
label, so "business number" means the one labelled work. It's never a guess:
someone with no work number is reported, not called on their mobile. The
`prepare` step does all this before the user is asked, so the confirmation
shows exactly who and which number.

macOS asks before any call starts (a notification with a Call button, so a web
page can't place calls by opening a link). With Accessibility allowed, Jarvis
presses that button itself; otherwise it tells the user to.
"""
from __future__ import annotations

import re
import subprocess
import time
import urllib.parse

from ... import channels
from ...memory import people
from ..base import tool

KINDS = {"video": "FaceTime video call", "audio": "FaceTime audio call",
         "phone": "phone call through your iPhone"}
SCHEMES = {"video": "facetime", "audio": "facetime-audio", "phone": "tel"}
_KIND_WORDS = {"voice": "audio", "facetime audio": "audio", "facetime": "video",
               "facetime video": "video", "cellular": "phone", "iphone": "phone",
               "tel": "phone", "telephone": "phone"}

# Which of their numbers the user means. The matched words are taken out of
# the name: "Salah's business number" -> ("Salah", "work").
_WANT = (
    ("work", r"\b(?:work|business|office|company|job)(?:\s+(?:mobile|cell|iphone))?"
             r"(?:\s+(?:number|phone|line|no))?\b"
             r"|\b(?:at|on)\s+(?:his\s+|her\s+|their\s+|the\s+)?(?:work|office)\b"),
    ("mobile", r"\b(?:mobile|cell\s*phone|cell|iphone)(?:\s+(?:number|phone|no))?\b"),
    ("home", r"\b(?:home|house)\s+(?:number|phone|line|no)\b|\blandline\b"
             r"|['’]s\s+home\b|\b(?:at|on)\s+(?:his\s+|her\s+|their\s+)?home\b"),
    ("email", r"\b(?:e-?mail|icloud|apple\s*id|apple\s+account)(?:\s+(?:address|account))?\b"),
)
_EMAIL = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[a-z]{2,}", re.I)
_PRETTY = {"iphone": "iPhone", "icloud": "iCloud"}


def parse(contact: str) -> tuple[str, str]:
    """'Salah's business number' -> ('Salah', 'work'); 'mum' -> ('mum', '')."""
    original = contact.strip().strip("\"'“”‘’").strip()
    text, want = original, ""
    for label, pattern in _WANT:
        if m := re.search(pattern, text, re.I):
            want, text = label, f"{text[:m.start()]} {text[m.end():]}"
            break
    text = re.sub(r"\b(?:phone\s+)?(?:numbers?|no\.?|phone|line|address)\b", " ", text, flags=re.I)
    # "mum on her mobile" / "Sam at his work number": the words left hanging
    text = re.sub(r"\s+(?:at|on|via|using)(?:\s+(?:his|her|their|my|the))?\s*$", "",
                  text.rstrip(), flags=re.I)
    text = re.sub(r"['’]s\b", "", text)                   # Salah's -> Salah
    text = re.sub(r"(?<=s)['’](?=\s|$)", "", text)        # James' -> James
    who = re.sub(r"\s+", " ", text).strip(" ,.-'’")
    if not who or who.lower() in ("my", "the", "our", "a", "his", "her", "their"):
        return original, ""
    return who, want


def direct(text: str) -> str:
    """A number or address the user said outright ('+44 7700 900123'), else ''."""
    t = text.strip()
    if _EMAIL.fullmatch(t):
        return t
    if re.fullmatch(r"\+?[\d\s().-]{6,}", t) and len(re.sub(r"\D", "", t)) >= 6:
        return t
    return ""


def _category(label: str) -> str:
    """A Contacts label -> work / mobile / home / fax / other / '' (none)."""
    low = label.lower()
    if "fax" in low or "pager" in low:
        return "fax"
    if re.search(r"work|business|office|company|job", low):
        return "work"
    if re.search(r"mobile|iphone|cell", low):
        return "mobile"
    if re.search(r"home|landline|house", low):
        return "home"
    return "other" if low else ""


def _same(a: dict, b: dict) -> bool:
    if a["kind"] != b["kind"]:
        return False
    if a["kind"] == "email":
        return a["value"].strip().lower() == b["value"].strip().lower()
    da, db = re.sub(r"\D", "", a["value"]), re.sub(r"\D", "", b["value"])
    # 07700 900123 and +44 7700 900123 are the same phone
    return bool(da) and (da == db or (min(len(da), len(db)) >= 9 and da[-9:] == db[-9:]))


def candidates(who: str) -> list[dict]:
    """Everyone `who` could mean: [{"name", "relation", "handles": [...]}].
    Saved people come first (they know relations: "mum", "my landlord");
    their Contacts card adds its labelled numbers when it's clearly theirs."""
    found = []
    for p in people.known(who):
        handles = [{"kind": "phone", "label": "", "value": p["phone"]}] if p.get("phone") else []
        if p.get("email"):
            handles.append({"kind": "email", "label": "", "value": p["email"]})
        found.append({"name": p["name"], "relation": p.get("relation", ""), "handles": handles})
    if found:
        for person in found:
            if person["name"].lower() == person["relation"].lower():
                continue          # saved by relation only ("Landlord"): no card to look up
            cards = people.contact_cards(person["name"])
            mine = [c for c in cards if c["name"].lower() == person["name"].lower()]
            for card in (mine or (cards if len(cards) == 1 else []))[:1]:
                for h in card["handles"]:
                    twin = next((x for x in person["handles"] if _same(h, x)), None)
                    if twin is None:
                        person["handles"].append(h)
                    elif not twin["label"]:
                        twin["label"] = h["label"]     # the card knows it's their work number
        return found
    query = re.sub(r"^(?:my|the|our)\s+", "", who.strip(), flags=re.I)
    return [{"name": c["name"], "relation": "", "handles": c["handles"]}
            for c in people.contact_cards(query)]


def _one(who: str, found: list[dict]) -> dict | str:
    if not found:
        return (f"I couldn't find {who} in your saved people or Contacts. What's their "
                "number or Apple ID email?")
    if len(found) == 1:
        return found[0]
    want = re.sub(r"^(?:my|the|our)\s+", "", who.strip().lower())
    for test in (lambda p: p["name"].lower() == want,
                 lambda p: p["relation"].lower() == want,
                 lambda p: p["name"].lower().split()[0] == want):
        hits = [p for p in found if test(p)]
        if len(hits) == 1:
            return hits[0]
    names = ", ".join(p["name"] for p in found[:6])
    return f"There's more than one {who}: {names}. Which one should I call?"


def _rank(h: dict) -> int:
    """Lower is better: FaceTime reaches iPhones and Apple IDs best."""
    label = h["label"].lower()
    if h["kind"] == "email":
        return 3 if "icloud" in label else 4
    order = {"mobile": 1, "": 2, "other": 5, "work": 6, "home": 7}
    return 0 if label == "iphone" else order.get(_category(label), 8)


def _shown(h: dict) -> str:
    label = _PRETTY.get(h["label"], h["label"])
    return f"{h['value']} ({label})" if label else h["value"]


def choose(person: dict, want: str, kind: str) -> dict | str:
    """The number or address to call `person` on, or why there isn't one."""
    usable = [h for h in person["handles"] if _category(h["label"]) != "fax"
              and (kind != "phone" or h["kind"] == "phone")]
    have = "; ".join(_shown(h) for h in usable)
    name = person["name"]
    if want == "email":
        if kind == "phone":
            return f"A phone call needs a number, not an email. FaceTime {name} instead?"
        emails = sorted((h for h in usable if h["kind"] == "email"), key=_rank)
        if emails:
            return emails[0]
        return (f"{name} has no email address saved"
                + (f" — I have: {have}. Which one should I call?" if have else "."))
    if want:
        hits = [h for h in usable if h["kind"] == "phone" and _category(h["label"]) == want]
        if not hits and want == "mobile":
            # Numbers people tell Jarvis ("mum's number is …") carry no label,
            # and they're nearly always mobiles. A work or home number must be one.
            hits = [h for h in usable if h["kind"] == "phone" and not h["label"]]
        if hits:
            return hits[0]
        word = {"work": "work / business", "mobile": "mobile", "home": "home"}[want]
        return (f"{name} has no {word} number saved"
                + (f" — I have: {have}. Which one should I call?" if have
                   else ". What's the number?"))
    if not usable:
        what = "phone number" if kind == "phone" else "phone number or Apple ID email"
        return f"I don't have a {what} for {name}. What is it?"
    return sorted(usable, key=_rank)[0]


def resolve(contact: str, kind: str = "video") -> dict | str:
    """"Salah's business number" -> {"name", "handle", "shown"} — or a
    question for the user (nobody by that name, which one, no work number)."""
    contact = (contact or "").strip()
    if not contact:
        return "Who should I call?"
    if handle := direct(contact):
        if kind == "phone" and "@" in handle:
            return f"A phone call needs a number, not an email. FaceTime {handle} instead?"
        return {"name": handle, "handle": handle, "shown": handle}
    who, want = parse(contact)
    person = _one(who, candidates(who))
    if isinstance(person, str):
        return person
    h = choose(person, want, kind)
    if isinstance(h, str):
        return h
    return {"name": person["name"], "handle": h["value"], "shown": _shown(h)}


def call_url(handle: str, kind: str) -> str:
    target = handle.strip() if "@" in handle else re.sub(r"[^\d+]", "", handle)
    return f"{SCHEMES[kind]}://{urllib.parse.quote(target, safe='+@.')}"


def _kind(value) -> str:
    v = str(value or "video").strip().lower()
    v = _KIND_WORDS.get(v, v)
    return v if v in KINDS else "video"


def _not_here() -> str:
    """Calls ring out from the Mac: only when the user is at it."""
    channel = channels.current.get()
    if channel is None:
        return ""
    if getattr(channel, "auto_approve", False):
        return "Not calling: calls need you at the Mac, so routines can't place them."
    return ("Not calling: calls start on the Mac, and you're messaging from your phone — "
            "call from the phone instead.")


# ---- the Call button macOS shows before a call --------------------------------------

_CALL_WORDS = {"call", "appeler", "anrufen", "llamar", "chiama", "bellen", "ligar", "ring",
               "اتصال"}
_PROMPT_APP = "com.apple.notificationcenterui"


def _ax():
    try:
        import ApplicationServices as AS
        from AppKit import NSWorkspace
        return (AS, NSWorkspace) if AS.AXIsProcessTrusted() else None
    except Exception:
        return None


def _call_button(AS, root, deadline: float):
    def attr(el, name):
        err, value = AS.AXUIElementCopyAttributeValue(el, name, None)
        return value if err == 0 else None

    queue, seen = [root], 0
    while queue and seen < 3000 and time.time() < deadline:
        el = queue.pop(0)
        seen += 1
        if str(attr(el, "AXRole") or "") == "AXButton":
            for name in ("AXTitle", "AXDescription"):
                if str(attr(el, name) or "").strip().lower() in _CALL_WORDS:
                    return el
        queue.extend(list(attr(el, "AXChildren") or []))
        if seen == 1:
            queue.extend(list(attr(el, "AXWindows") or []))
    return None


def _find_call_button(ax, deadline: float):
    AS, NSWorkspace = ax
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if (app.bundleIdentifier() or "") == _PROMPT_APP:
            root = AS.AXUIElementCreateApplication(app.processIdentifier())
            if (button := _call_button(AS, root, deadline)) is not None:
                return button
    return None


def _waiting_prompt() -> bool:
    """An earlier call prompt still on screen: pressing "Call" now could ring
    whoever THAT one was for, so the user presses it."""
    ax = _ax()
    return ax is not None and _find_call_button(ax, time.time() + 1.0) is not None


def _press_call(timeout: float = 8.0) -> bool:
    """Press Call on the prompt macOS shows before a call starts. Needs
    Accessibility; False when it doesn't appear in time."""
    ax = _ax()
    if ax is None:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        button = _find_call_button(ax, min(deadline, time.time() + 2.0))
        if button is not None and ax[0].AXUIElementPerformAction(button, "AXPress") == 0:
            return True
        time.sleep(0.3)
    return False


# ---- the tool ----------------------------------------------------------------------

def _prepare(args: dict) -> dict | str:
    """Find who and which number before the user is asked to allow the call.
    Always worked out here from `contact`: a name or number the model adds
    itself must never be what the user approves while another is dialled."""
    if refusal := _not_here():
        return refusal
    kind = _kind(args.get("kind"))
    contact = str(args.get("contact") or args.get("handle") or "").strip()
    callee = resolve(contact, kind)
    if isinstance(callee, str):
        return callee
    return {"contact": contact, "kind": kind, "who": callee["name"],
            "number": callee["shown"], "handle": callee["handle"]}


@tool(
    name="facetime_call",
    description="Call someone from this Mac. kind='video' (default) is a FaceTime video "
                "call, 'audio' a FaceTime audio call, 'phone' an ordinary phone call through "
                "the user's iPhone. Pass contact exactly as the user said it — a name, a "
                "relation or a number, including WHICH number (\"Salah's business number\", "
                "\"mum's mobile\", \"+44 7700 900123\"): the tool finds the person in saved "
                "people and Contacts and picks the right number itself. Use it for "
                "'FaceTime X', 'video call X', 'call X'.",
    parameters={
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "who to call, as the user said it"},
            "kind": {"type": "string", "enum": ["video", "audio", "phone"]},
        },
        "required": ["contact"],
    },
    risk="confirm",
    # It rings someone, and Jarvis then presses macOS's own Call prompt: the user
    # sees who and which number every time (a misheard name, or a number planted
    # in an email the model read, must never ring unseen) — like sending email.
    always_ask=True,
    agent_tags=["messaging", "_conversation"],
    prepare=_prepare,
)
def facetime_call(contact: str = "", kind: str = "video", who: str = "", number: str = "",
                  handle: str = "") -> str:
    if refusal := _not_here():
        return refusal
    kind = _kind(kind)
    if not handle:
        callee = resolve(contact, kind)
        if isinstance(callee, str):
            return callee
        who, number, handle = callee["name"], callee["shown"], callee["handle"]
    if kind == "phone" and "@" in handle:
        return f"A phone call needs a number, not an email. FaceTime {handle} instead?"
    number = number or handle
    target = f"{who} ({number})" if who and who != handle else number
    earlier_prompt = _waiting_prompt()
    try:
        r = subprocess.run(["open", call_url(handle, kind)], capture_output=True, text=True,
                           timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return f"Couldn't start the call: {e}"
    if r.returncode != 0:
        return f"Couldn't start the call: {(r.stderr or '').strip() or 'FaceTime did not open'}."
    what = KINDS[kind]
    if not earlier_prompt and _press_call():
        return f"Calling {target} — {what}."
    hint = "" if _ax() is not None else (
        " (Allow Jarvis in System Settings → Privacy & Security → Accessibility and I'll "
        "press it for you.)")
    return (f"Ready to call {target} — {what}. Press Call on the notification at the top "
            f"right of the screen to start it.{hint}")

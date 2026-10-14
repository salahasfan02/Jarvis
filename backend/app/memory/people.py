"""People Jarvis knows: "my landlord", "Sam", "mum" -> name, email, phone.

So "email Sam the report" or "text my landlord" works without asking for an
address. Jarvis's own list comes first (it knows relations like "landlord");
the Mac's Contacts app is the fallback.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import uuid

from .. import db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
"""
_ready = False
EMAIL = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[a-z]{2,}", re.I)
_FILLER = {"my", "the", "our", "to", "a", "an", "mr", "mrs", "ms", "dr"}


def _ensure() -> None:
    global _ready
    if not _ready:
        with db.connect() as conn:
            conn.executescript(_SCHEMA)
        _ready = True


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in _FILLER]


def all_people() -> list[dict]:
    _ensure()
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM people ORDER BY name")]


def remember(name: str, relation: str = "", email: str = "", phone: str = "",
             notes: str = "") -> dict:
    """Add or update a person (matched by name, else by relation)."""
    _ensure()
    name, relation = name.strip(), relation.strip().lower()
    # "my landlord" is a relation, not a name.
    m = re.match(r"(?i)^(?:my|our|the)\s+(.+)$", name)
    if m:
        relation, name = relation or m.group(1).lower(), ""
    everyone = all_people()
    existing = next((p for p in everyone if name and p["name"].lower() == name.lower()), None)
    if existing is None and relation:
        # A placeholder saved by relation only ("Landlord") gets their real name later.
        existing = next((p for p in everyone if p["relation"] == relation
                         and (not name or p["name"].lower() == relation)), None)
    now = time.time()
    with db.connect() as conn:
        if existing:
            merged = {
                "name": name or existing["name"],
                "relation": relation or existing["relation"],
                "email": email.strip() or existing["email"],
                "phone": phone.strip() or existing["phone"],
                "notes": "; ".join(x for x in (existing["notes"], notes.strip()) if x)[-1000:],
            }
            conn.execute("UPDATE people SET name=?, relation=?, email=?, phone=?, notes=?, "
                         "updated_at=? WHERE id=?", (*merged.values(), now, existing["id"]))
            return {**existing, **merged}
        person = {"id": uuid.uuid4().hex, "name": name or relation.title(), "relation": relation,
                  "email": email.strip(), "phone": phone.strip(), "notes": notes.strip(),
                  "updated_at": now}
        conn.execute("INSERT INTO people VALUES (:id, :name, :relation, :email, :phone, "
                     ":notes, :updated_at)", person)
        return person


def forget(name: str) -> bool:
    _ensure()
    with db.connect() as conn:
        return conn.execute("DELETE FROM people WHERE lower(name)=?",
                            (name.strip().lower(),)).rowcount > 0


def known(query: str) -> list[dict]:
    """People in Jarvis's own list matching a name or relation ("landlord")."""
    words = _words(query)
    if not words:
        return []
    hits = []
    for p in all_people():
        hay = set(_words(p["name"])) | set(_words(p["relation"]))
        if all(any(h.startswith(w) or w.startswith(h) for h in hay if len(h) > 1) for w in words):
            hits.append(p)
    return hits


def from_contacts(query: str) -> list[dict]:
    """Search the Mac's Contacts app by name (needs Contacts permission)."""
    name = query.strip().replace('"', "")
    if len(name) < 2:
        return []
    script = f'''
    set out to ""
    tell application "Contacts"
        repeat with p in (every person whose name contains "{name}")
            set em to ""
            set ph to ""
            try
                set em to value of first email of p
            end try
            try
                set ph to value of first phone of p
            end try
            set out to out & (name of p) & tab & em & tab & ph & linefeed
        end repeat
    end tell
    return out'''
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    people = []
    for line in r.stdout.splitlines()[:10]:
        parts = (line.split("\t") + ["", "", ""])[:3]
        if parts[0].strip():
            people.append({"name": parts[0].strip(), "relation": "", "email": parts[1].strip(),
                           "phone": parts[2].strip(), "notes": "from Contacts"})
    return people


def lookup(query: str) -> list[dict]:
    return known(query) or from_contacts(re.sub(r"^(?:my|the)\s+", "", query.strip(), flags=re.I))


def contact_cards(query: str) -> list[dict]:
    """Contacts cards whose name (or nickname) contains `query`, with EVERY
    phone number and email address and its label — for calls, where "Salah's
    business number" must be the one labelled work, not just the first one.
    -> [{"name", "handles": [{"kind": "phone"|"email", "label", "value"}]}]"""
    name = query.strip().replace('"', "").replace("\\", "")
    if len(name) < 2:
        return []
    script = f'''
    set out to ""
    tell application "Contacts"
        set found to {{}}
        try
            set found to found & (every person whose name contains "{name}")
        end try
        try
            set found to found & (every person whose nickname contains "{name}")
        end try
        repeat with p in found
            set pid to id of p
            set nm to name of p
            repeat with ph in (phones of p)
                set lb to ""
                try
                    set lb to (label of ph) as text
                end try
                set out to out & pid & tab & nm & tab & "phone" & tab & lb & tab & (value of ph) & linefeed
            end repeat
            repeat with em in (emails of p)
                set lb to ""
                try
                    set lb to (label of em) as text
                end try
                set out to out & pid & tab & nm & tab & "email" & tab & lb & tab & (value of em) & linefeed
            end repeat
        end repeat
    end tell
    return out'''
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    return parse_cards(r.stdout or "")


def parse_cards(text: str) -> list[dict]:
    """The Contacts script's lines (id, name, kind, label, value) -> cards."""
    cards: dict[str, dict] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 5 or not parts[1].strip() or not parts[4].strip():
            continue
        pid, name, kind, label, value = (p.strip() for p in parts[:5])
        card = cards.setdefault(pid or name, {"name": name, "handles": []})
        handle = {"kind": "email" if kind == "email" else "phone",
                  "label": clean_label(label), "value": value}
        if handle not in card["handles"]:
            card["handles"].append(handle)
    return list(cards.values())


def clean_label(raw: str) -> str:
    """Contacts' '_$!<Work>!$_' -> 'work'; 'iPhone' -> 'iphone'; none -> ''."""
    raw = (raw or "").strip()
    if raw.lower() in ("", "missing value"):
        return ""
    m = re.fullmatch(r"_\$!<(.+?)>!\$_", raw)
    return (m.group(1) if m else raw).strip().lower()


def resolve_email(recipient: str) -> tuple[str | None, list[dict]]:
    """'Sam' / 'my landlord' -> (email, []) when clear, else (None, candidates)."""
    if EMAIL.fullmatch(recipient.strip()):
        return recipient.strip(), []
    people = [p for p in lookup(recipient) if p.get("email")]
    if len(people) == 1:
        return people[0]["email"], []
    return None, people


def describe(p: dict) -> str:
    bits = [p["name"]]
    if p.get("relation"):
        bits.append(f"({p['relation']})")
    if p.get("email"):
        bits.append(f"email {p['email']}")
    if p.get("phone"):
        bits.append(f"phone {p['phone']}")
    if p.get("notes"):
        bits.append(f"— {p['notes'][:120]}")
    return " ".join(bits)


def to_json(people: list[dict]) -> str:
    return json.dumps([{k: p.get(k, "") for k in ("name", "relation", "email", "phone")}
                       for p in people])

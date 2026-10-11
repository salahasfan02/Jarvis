"""The user's own details ("me" profile): name, contact details, address,
work, sign-off. Kept only in Jarvis's local settings; used to fill in forms
and sign emails. Never includes passwords, card or bank details, or ID numbers."""
from __future__ import annotations

import re

from ..config import settings

FIELDS = {
    "full_name": "Full name", "first_name": "First name", "last_name": "Last name",
    "email": "Email", "phone": "Phone", "address_line1": "Address line 1",
    "address_line2": "Address line 2", "city": "Town / city", "county": "County / state",
    "postcode": "Postcode / ZIP", "country": "Country", "company": "Company",
    "job_title": "Job title", "website": "Website", "linkedin": "LinkedIn",
    "signature": "Email sign-off",
}

# Labels in forms -> profile keys. First match wins, so specific before general.
_LABELS = [
    (r"first\s*name|given\s*name|forename", "first_name"),
    (r"last\s*name|surname|family\s*name", "last_name"),
    (r"full\s*name|^name$|your\s*name|^name\b|contact\s*name", "full_name"),
    (r"e-?mail", "email"),
    (r"phone|mobile|tel(?:ephone)?\b|cell", "phone"),
    (r"address\s*(?:line)?\s*2|apartment|suite|flat", "address_line2"),
    (r"address|street|line\s*1", "address_line1"),
    (r"city|town", "city"),
    (r"county|state|province|region", "county"),
    (r"post\s*code|postal|zip", "postcode"),
    (r"country", "country"),
    (r"company|organi[sz]ation|employer|business", "company"),
    (r"job\s*title|position|role|occupation", "job_title"),
    (r"linkedin", "linkedin"),
    (r"website|url|homepage|portfolio", "website"),
]

# Never typed by Jarvis, whatever the form says.
NEVER = re.compile(r"pass(?:word|code)|card|cvv|cvc|security\s*code|expir|iban|sort\s*code|"
                   r"account\s*(?:number|no)|routing|ssn|social\s*security|national\s*insurance|"
                   r"passport|licen[cs]e\s*number|tax\s*id|pin\b|one-?time|otp|2fa|verification\s*code",
                   re.I)


def get() -> dict:
    p = dict(settings.get("profile", {}) or {})
    full = p.get("full_name", "").strip()
    if full and not p.get("first_name"):
        p["first_name"] = full.split()[0]
    if full and not p.get("last_name") and len(full.split()) > 1:
        p["last_name"] = full.split()[-1]
    if not full and (p.get("first_name") or p.get("last_name")):
        p["full_name"] = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    return {k: v for k, v in p.items() if isinstance(v, str) and v.strip()}


def key_for(label: str) -> str | None:
    """Which profile detail a form field wants, or None."""
    text = (label or "").strip().lower()
    if not text or NEVER.search(text):
        return None
    for pattern, key in _LABELS:
        if re.search(pattern, text):
            return key
    return None


def describe() -> str:
    p = get()
    if not p:
        return ("No personal details saved yet. The user can add them in Settings → About "
                "you, or tell you and you save them with update_my_details.")
    return "\n".join(f"{FIELDS.get(k, k)}: {v}" for k, v in p.items() if k in FIELDS)

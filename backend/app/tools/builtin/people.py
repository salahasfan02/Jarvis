"""People tools: remember who someone is, and look them up."""
from __future__ import annotations

import asyncio

from ...memory import people
from ..base import tool


@tool(
    name="remember_person",
    description="Save or update someone the user mentions: their name, how they relate to "
                "the user (landlord, boss, mum, dentist…), email, phone, notes. Use it "
                "whenever the user shares a person's contact details or relationship "
                "(\"my landlord is Tom, tom@x.com\"), so later \"email my landlord\" works.",
    parameters={"type": "object", "properties": {
        "name": {"type": "string", "description": "their name (or the relation if unknown)"},
        "relation": {"type": "string", "description": "e.g. landlord, boss, sister"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "notes": {"type": "string", "description": "anything else worth remembering"},
    }, "required": ["name"]},
    agent_tags=["messaging", "email", "_conversation"],
)
def remember_person(name: str, relation: str = "", email: str = "", phone: str = "",
                    notes: str = "") -> str:
    p = people.remember(name, relation, email, phone, notes)
    return f"Saved: {people.describe(p)}."


@tool(
    name="find_person",
    description="Look up someone's email/phone by name or relation (\"Sam\", \"my "
                "landlord\", \"mum\"): Jarvis's saved people first, then the Mac's Contacts.",
    parameters={"type": "object", "properties": {
        "query": {"type": "string", "description": "name or relation"},
    }, "required": ["query"]},
    agent_tags=["messaging", "email"],
)
async def find_person(query: str) -> str:
    found = await asyncio.to_thread(people.lookup, query)
    if not found:
        return (f"I don't know anyone called '{query}'. Ask the user for their email or "
                "number, then save it with remember_person.")
    return "\n".join(people.describe(p) for p in found[:8])

"""Send things to the user's phone (Telegram) — "send that to me".

At the Mac, "send it to me" means the user's phone: the answer Jarvis just
gave, the whole conversation, or either one as a Word document. From the
phone it lands in the same Telegram chat. Content comes straight from the
conversation, so a long answer isn't retyped by the model on the way.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from ... import channels, db
from ..base import tool

LONG_CHAT = 12000      # characters: a longer chat goes as a document, not 4+ messages


def _target():
    """The current Telegram chat, else the paired phone(s) — or None."""
    from ...channels import telegram
    channel = channels.current.get()
    if channel is not None and hasattr(channel, "send_text") and channel.name == "Telegram":
        return channel
    return telegram.owner()


def _earlier_messages() -> list[dict]:
    """This conversation so far, minus the request being answered now."""
    conv = channels.conversation.get()
    msgs = db.get_messages(conv) if conv else []
    if msgs and msgs[-1]["role"] == "user":
        msgs = msgs[:-1]
    return msgs


def _readable(text: str) -> str:
    # A folder listing block reads better as plain lines on a phone.
    return re.sub(r"```listing\n(.*?)```", r"\1", text, flags=re.S).strip()


_MADE = re.compile(r" at (/\S.*?\.(?:docx|xlsx|pptx|pdf|md|txt|csv|jpe?g|png))\b")


def _made_in(message: dict) -> str | None:
    """The document (or photo) an answer made ("I've written the report"), if
    any — then "send it to me" means that file, not the sentence about it."""
    for t in reversed(message.get("meta", {}).get("tools") or []):
        if str(t.get("name", "")).startswith(("create_", "research_report", "take_photo")):
            if m := _MADE.search(str(t.get("result", ""))):
                return m.group(1)
    return None


def _latest_photo(msgs: list[dict]) -> Path | None:
    """The photo meant by "send me that picture": the last one taken in this
    chat, else the newest in the photos folder."""
    from ...vision import photos
    for m in reversed(msgs):
        for t in reversed((m.get("meta") or {}).get("tools") or []):
            if t.get("name") == "take_photo" and (found := _MADE.search(str(t.get("result", "")))):
                if photos.is_photo(Path(found.group(1))):
                    return Path(found.group(1))
    newest = photos.recent(1)
    return newest[0] if newest else None


async def send_picture(path: Path, caption: str = "") -> str:
    """A photo to the user's phone: this Telegram chat, else the paired phone."""
    from ...channels import telegram
    target = _target()
    if target is None:
        return telegram.why_not_owner()
    return await target.send_photo(path, caption)


def _transcript(msgs: list[dict], name: str) -> str:
    return "\n\n".join(f"**{'You' if m['role'] == 'user' else name}:** {_readable(m['content'])}"
                       for m in msgs if m["content"].strip())


@tool(
    name="send_to_phone",
    description="Send something to the user's phone on Telegram. what='last_answer' sends "
                "your previous answer ('send that/it to me'), 'conversation' the whole chat "
                "('send me the whole chat'), 'photo' the photo just taken with take_photo "
                "('send me that picture'), 'text' the text you give. as_document=true "
                "puts it in a Word document and sends the file instead ('put that in a "
                "document and send it to me'). At the Mac, 'send it to me' always means this.",
    parameters={
        "type": "object",
        "properties": {
            "what": {"type": "string", "enum": ["last_answer", "conversation", "photo", "text"]},
            "text": {"type": "string", "description": "only for what='text'"},
            "as_document": {"type": "boolean", "description": "send a Word document instead"},
            "title": {"type": "string", "description": "document title (optional)"},
        },
    },
    risk="confirm",          # it leaves the Mac — unless the user just asked for it
)
async def send_to_phone(what: str = "last_answer", text: str = "", as_document: bool = False,
                        title: str = "") -> str:
    from ...channels import telegram
    from ...config import settings
    from ...vision import photos
    target = _target()
    if target is None:
        return telegram.why_not_owner()
    name = settings.get("assistant.name", "Jarvis")
    msgs = await asyncio.to_thread(_earlier_messages)
    if what == "photo":
        shot = await asyncio.to_thread(_latest_photo, msgs)
        if shot is None:
            return "There's no photo to send yet — say \"take a picture\" first."
        return await target.send_photo(shot, title)
    if what == "conversation":
        body = _transcript(msgs, name)
        if not body:
            return "There's nothing in this chat to send yet."
        conv = db.get_conversation(channels.conversation.get() or "") or {}
        default_title = conv.get("title") or "Chat with " + name
        if len(body) > LONG_CHAT:
            as_document = True
    elif what == "text":
        body, default_title = text.strip(), ""
        if not body:
            return "Error: give the text to send."
    else:
        last = next((m for m in reversed(msgs) if m["role"] == "assistant"), None)
        if last is None:
            return "There's no earlier answer in this chat to send."
        if (made := _made_in(last)) and Path(made).exists():
            if photos.is_photo(Path(made)):
                return await target.send_photo(Path(made))
            return await target.send_file(Path(made), Path(made).stem.replace("-", " "))
        body, default_title = _readable(last["content"]), ""

    if not as_document:
        return await target.send_text(body)

    from .documents import create_word_document
    doc_title = (title or default_title or body.split("\n", 1)[0][:60]).strip("#* ") or "From " + name
    made = await asyncio.to_thread(create_word_document, doc_title, body)
    m = re.search(r" at (/.+?\.docx)", made)
    if not m:
        return made
    return await target.send_file(Path(m.group(1)), doc_title)

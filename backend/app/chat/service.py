"""Chat orchestration: memory recall -> agent routing -> LLM streaming ->
tool-calling loop with user confirmations.

Emits event dicts consumed by the WebSocket layer:
  {"type": "agent", "agent": {...}}
  {"type": "memory", "recalled": [...]}
  {"type": "token", "content": "..."}
  {"type": "tool_start" | "tool_result", ...}
  {"type": "confirm_request", "id", "tool", "arguments", "risk"}
  {"type": "done", "content": "...", "message_id": "..."}
  {"type": "title", "title": "..."}
  {"type": "error", "message": "..."}
"""
from __future__ import annotations

import asyncio
import datetime
import functools
import json
import os
import re
import time
from typing import AsyncIterator

from .. import activity, channels, db, learned
from ..agents import registry as agents
from ..automation import context as app_context
from ..automation import guard, selection
from ..config import settings
from ..gaps import registry as gaps
from ..llm import ollama_client
from ..memory import store as memory_store
from ..security import audit
from ..security.permissions import confirmations
from ..tools import base as tools
from . import compact, prefetch, quick, toolpick

SMART_WINDOW_RULES = """Smart context rules (IMPORTANT):
- Before opening any website, check the open tabs (they are listed above, or
  call browser_tabs). If a tab for that site already exists, REUSE it.
- NEVER open a new browser window unless the user explicitly says "new window".
- Never launch an app that is already running; continue its existing session.
- To play ANY song or video on YouTube, ALWAYS call the youtube_play tool with
  the search query — it finds the video and starts it in the right tab. Never
  answer that you "cannot play media"; youtube_play CAN. Use youtube_control
  to pause/skip. Use music_play only for the user's Apple Music library.
- Continue the user's current activity in place; don't duplicate contexts."""


CONTEXT_RULES = """The latest user message may begin with a <context>…</context>
block. The SYSTEM adds it, not the user: the current time, what the user is
doing on the Mac, and things you remember about them. Use it silently: never
quote or list it, never volunteer it unprompted (no announcing the time or
which apps are open). Mention a detail only when it is directly relevant,
in your own words — e.g. 'I can see you're in Messages'."""


@functools.lru_cache(maxsize=1)
def _user_full_name() -> str:
    """The Mac account's full name ("Salah Asfan") — so emails get signed
    properly instead of with a "[Your Name]" placeholder."""
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
    except (ImportError, KeyError, OSError):
        return ""


def _static_system_prompt(agent: agents.Agent | None = None) -> str:
    """The big prompt (persona + rules; the tool schemas follow it in the
    template). It must contain NOTHING that changes between messages — or
    between agents: Ollama reuses its work for an unchanged prefix, so this
    plus the core tools is read once and then shared by every request. The
    agent's own instructions go in the per-message context block instead."""
    name = settings.get("assistant.name", "Jarvis")
    persona = settings.get("assistant.persona", "").format(name=name)
    parts = [persona]
    parts.append(SMART_WINDOW_RULES)
    parts.append("Always reply in the language the user used — if they write or speak "
                 "Arabic, answer in Arabic; English, in English.")
    parts.append(
        "When a tool would help, call it instead of guessing. Some tool calls "
        "require the user's confirmation; if one is denied, respect that and "
        "explain what you would have done.")
    parts.append(CONTEXT_RULES)
    from ..memory import profile
    me = profile.get()
    if user := (me.get("full_name") or _user_full_name()):
        sign = me.get("signature") or user
        parts.append(f"The user's name is {user}. Sign emails and messages you write "
                     f"for them as: {sign} — never leave placeholders like [Your Name].")
    return "\n\n".join(parts)


def _dynamic_block(memories: list[dict], ctx: dict, this: str = "",
                   role: str = "") -> str:
    """Small, changing facts for THIS message only (see CONTEXT_RULES)."""
    parts = ["Current date/time: "
             + datetime.datetime.now().strftime("%A, %B %d %Y, %H:%M")]
    if role:
        parts.append("How to handle this request:\n" + role)
    if this:
        parts.append("What \"this\"/\"that\" in the user's message refers to (use it — "
                     "e.g. attach that path, read that page or document, use that text):\n"
                     + this)
    ctx_summary = app_context.summary_for_prompt(ctx)
    if ctx_summary:
        parts.append("What the user is doing right now:\n" + ctx_summary)
    if memories:
        facts = "\n".join(f"- {m['content']}" for m in memories)
        parts.append("Relevant things you remember about the user:\n" + facts)
    channel = channels.current.get()
    if channel is not None and channel.name == "routine":
        parts.append(
            "This is an AUTOMATIC ROUTINE the user set up — they are not here to answer "
            "questions. Do the task with your tools and reply with the result itself, "
            "short and ready to read on a phone. Never ask anything.")
    elif channel is not None:
        parts.append(
            f"The user is messaging you from their PHONE via {channel.name}, away "
            "from this Mac. Keep replies short and phone-friendly. When they ask "
            "for a file from this Mac, find it (search_files / list_directory — "
            "results are newest first, with dates) and deliver it with send_file; "
            "for 'the latest/newest/last' one, just send the most recent match "
            "instead of asking which. When they ask for a document or report, write "
            "it with create_word_document, then send_file the path it returns.")
    return "\n\n".join(parts)


def _with_context(messages: list[dict], dyn: str) -> list[dict]:
    """Prepend the dynamic block to the LAST user message.

    Ollama's chat templates gather every system message into one block that
    sits before the tool schemas, so a changing system note (the clock ticks
    every minute) forced the model to re-read thousands of tokens of tool
    schemas on every message. In the user turn it leaves the system prompt,
    tools and history byte-identical, so only the new message is processed."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]["role"] == "user":
            messages[i] = {**messages[i], "content":
                           f"<context>\n{dyn}\n</context>\n\n{messages[i]['content']}"}
            break
    return messages


def _tools_for(agent: agents.Agent) -> list[tools.Tool]:
    """The routed agent's tools, plus the remote kit on phone turns. An agent
    with no tags already sees every tool, so it is left unfiltered."""
    tags = agent.tool_tags
    if tags and channels.current.get() is not None:
        tags = [*tags, *channels.REMOTE_TOOL_TAGS]
    return tools.registry.for_agent(tags)


REPLAY_RESULT_CHARS = 800   # per tool result carried into later turns
REPLAY_MAX_CALLS = 4


def _history_to_llm(history: list[dict]) -> list[dict]:
    """Stored turns -> model messages, INCLUDING what earlier tools returned.
    Without it a follow-up like "send number 1" fails: the paths a search found
    one message ago were gone, leaving only the model's own paraphrase. Every
    turn is replayed the same way each time, so the prefix stays cacheable."""
    msgs: list[dict] = []
    for m in history:
        if m["role"] == "user":
            msgs.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            calls = [c for c in (m.get("meta") or {}).get("tools") or []
                     if c.get("name")][:REPLAY_MAX_CALLS]
            if calls:
                msgs.append({"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": c["name"], "arguments": c.get("arguments") or {}}}
                    for c in calls]})
                msgs.extend({"role": "tool", "tool_name": c["name"],
                             "content": (c.get("result") or "")[:REPLAY_RESULT_CHARS]}
                            for c in calls)
            msgs.append({"role": "assistant", "content": m["content"]})
    return msgs


def _recent_tools(history: list[dict], turns: int = 2) -> set[str]:
    """Tools the last few replies used — kept on offer for follow-ups."""
    names: set[str] = set()
    replies = [m for m in history if m["role"] == "assistant"][-turns:]
    for m in replies:
        names.update(c.get("name") for c in (m.get("meta") or {}).get("tools") or []
                     if c.get("name"))
    return names


def _short_title(text: str) -> str:
    """Short first messages ("open youtube") are already a fine title — no need
    to spend a model call (which also evicts Ollama's cached prompt)."""
    words = text.split()
    if not words or len(words) > 6 or len(text) > 60:
        return ""
    title = " ".join(words).rstrip(".!?")
    return title[:1].upper() + title[1:]


def _sticky_agent(history: list[dict], user_content: str) -> agents.Agent | None:
    """A short reply to a question Jarvis just asked ("the first one", "yes,
    the PDF") continues with the same agent instead of being re-routed by
    keywords — "1. Screenshot …" used to land on the vision agent."""
    prev = next((m for m in reversed(history[:-1]) if m["role"] == "assistant"), None)
    if not prev or not prev["content"].rstrip().endswith("?"):
        return None
    if len(user_content.split()) > 12:
        return None
    agent = agents.AGENTS.get((prev.get("meta") or {}).get("agent", ""))
    return agent if agent and agent.id not in ("planner",) else None


def _round_timing(chunk: dict) -> dict:
    """Ollama's own counters from the final chunk. prompt_tokens counts only
    tokens it actually had to process — a small number means the cache hit."""
    ms = 1e6
    return {"prompt_tokens": chunk.get("prompt_eval_count", 0),
            "prompt_ms": round(chunk.get("prompt_eval_duration", 0) / ms),
            "gen_tokens": chunk.get("eval_count", 0),
            "gen_ms": round(chunk.get("eval_duration", 0) / ms),
            "load_ms": round(chunk.get("load_duration", 0) / ms)}


# "Send" vs "draft": with both tools on offer, a small local model often picks
# the wrong one — or writes "I've drafted it" and calls nothing at all.
_SAYS_DRAFT = re.compile(r"\b(draft|prepare|compose|write up)\b", re.I)
_SAYS_SEND = re.compile(
    r"\b(send|shoot|fire off)\b[^.?!]*\b(e-?mails?|mail|reply|it)\b"
    r"|^\s*(?:please\s+|can you\s+|could you\s+)?e-?mail\s+\w"
    r"|\b(?:and|then)\s+e-?mail\s+(?:it|this|that|them)\b"     # "...then email it to Sam"
    r"|\breply\b[^.?!]*\band send\b", re.I)


_SAYS_TEXT = re.compile(r"^\s*(?:please\s+)?(?:text|imessage|message|whatsapp)\s+(?!me\b)\w", re.I)


def _texting(user_content: str, name: str, args: dict) -> tuple[str, dict]:
    """"Text John that…" is an iMessage, not an email: the model sometimes
    reached for draft_email. Rewritten here (same reason as _respect_intent)."""
    if name in ("draft_email", "send_email") and _SAYS_TEXT.search(user_content):
        return "draft_imessage", {"recipient": args.get("to", ""), "body": args.get("body", "")}
    return name, args


def _respect_intent(user_content: str, name: str) -> str:
    """Draft-only requests never send; send requests never stop at a draft.
    Done here, not by hiding tools, so the cached prompt opening never changes."""
    dont_send = re.search(r"\b(?:don'?t|do not|not|never|without)\s+(?:send|sending)\b",
                          user_content, re.I)
    if dont_send or (_SAYS_DRAFT.search(user_content)
                     and not re.search(r"\bsend\b", user_content, re.I)):
        return {"send_email": "draft_email", "send_reply": "draft_reply"}.get(name, name)
    if _SAYS_SEND.search(user_content):
        # They said send: a draft would leave it unsent. Sending still shows
        # them the exact email to approve first.
        return {"draft_email": "send_email", "draft_reply": "send_reply"}.get(name, name)
    return name


_CLAIMS_ACTION = re.compile(
    r"\b(?:i(?:'ve| have)?|i just)\s+(?:sent|drafted|emailed|replied|opened|created|"
    r"scheduled|added|saved|moved|deleted|played|booked|set up|forwarded|found|located)\b"
    r"|\bi(?:'m| am) (?:opening|sending|moving|deleting|playing)\b"
    r"|\bi (?:found|can see you have)\b|\bhere are the files\b"
    r"|\bhas been (?:sent|drafted|created|scheduled|saved|added|moved|deleted)\b", re.I)
_ASKS_ACTION = re.compile(
    r"\b(send|e-?mail|draft|reply|forward|open|create|schedule|add|play|save|move|"
    r"delete|book|remind|text|find|search|list|show|what tabs)\b", re.I)
# Citing searches it never ran: never acceptable, whatever was asked.
_FAKE_SOURCES = re.compile(r"\baccording to (?:recent |my |the )?(?:web )?search(?:es)?\b"
                           r"|(?:^|[.!?]\s+)sources?:\s", re.I | re.M)
_ASKS_ABOUT_PAST = re.compile(r"^\s*(did|have|has|was|were|is|are|why|when)\b", re.I)
CLAIM_NUDGE = ("(You answered as if you had done or looked something up, but you didn't "
               "call any tool — so nothing happened and anything you 'found' is made up. "
               "Call the tool that does it now, or tell me plainly that you can't.)")


# A reply that ends by announcing an action it never took.
_ANNOUNCES = re.compile(r"\b(?:let me|let[’']s|i[’']ll|i will|i[’']m going to|i am going to)\b"
                        r"[^.?!]{0,80}(?:now|first|for you|right away)?[.!…:]?\s*$", re.I)
# Stalling instead of acting: asking permission for what was already asked
# (the tool shows its own confirmation), or asking for a path/address the
# tools find themselves.
_STALLS = re.compile(
    r"\b(?:would you like me to|shall i|should i|do you want me to|want me to)\s+"
    r"(?:go ahead and\s+)?(?:send|open|email|delete|move|create|draft|play|attach)\b"
    r"|\b(?:could|can|would) you (?:please )?(?:provide|tell me|specify|share|give me|confirm)"
    r"[^.?!]{0,40}\b(?:path|file ?name|location|email address|address|which file)\b"
    r"|\bi need (?:the |your |its )?(?:file ?(?:path|name)|path|location|email address|"
    r"address|name of the (?:file|document))\b"
    r"|\b(?:just )?(?:give|send|tell) me (?:its|the|their) (?:location|path|name|address|email)\b",
    re.I)
STALL_NUDGE = ("(The user already asked for this, and the tool asks them to approve it "
               "itself — don't ask in text. The tools find files and people by name, so "
               "call the tool now with what the user said.)")
_WANTS_FILE = re.compile(r"\b(?:word (?:doc|document|file)|\.docx|docx|spreadsheet|excel|"
                        r"\.xlsx|presentation|slide ?deck|powerpoint|\.pptx)\b", re.I)
FILE_NUDGE = ("(They asked for a FILE, not text in the chat. Create it now with the tool "
              "(create_word_document / create_spreadsheet / create_presentation), with the "
              "full content inside.)")
INTENT_NUDGE = ("(You said you would do that, but you didn't call the tool. Call it now — "
                "don't describe it.)")


_FAIL_STARTS = ("error", "failed", "applescript error", "couldn't", "could not",
                "attachment not found", "no recipient", "not an email address")
FAILED_NOTE = ("\n\n(This step FAILED — it did not happen. Fix it and retry if you can; "
               "otherwise tell the user plainly that it didn't work and why. Never say it "
               "succeeded.)")


def _failed(output: str) -> bool:
    return output.strip().lower().startswith(_FAIL_STARTS)


def _pretends(user_content: str, reply: str) -> bool:
    """The reply claims an action (or a search) though no tool ran."""
    if _FAKE_SOURCES.search(reply):
        return True
    return (bool(_ASKS_ACTION.search(user_content)) and not _ASKS_ABOUT_PAST.match(user_content)
            and bool(_CLAIMS_ACTION.search(reply)))


def text_tool_call(text: str, offered: list[tools.Tool]) -> dict | None:
    """Local models sometimes WRITE a tool call instead of making one —
    `CloseOperation{"name": "browser_close_tab", "arguments": {"tab_index": 2}}`,
    or JSON inside <tool_call> tags. Nothing would happen and the user would
    see raw JSON, so recover it as a real call. Prose that merely quotes some
    JSON (lots of other text around it) is left alone."""
    names = {t.name for t in offered}
    if "{" not in text or not any(n in text for n in names):
        return None
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("function"), dict):
            obj = obj["function"]
        if not isinstance(obj, dict) or obj.get("name") not in names:
            continue
        args = obj.get("arguments", obj.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            continue
        leftover = re.sub(r"</?tool_call>|```(?:json)?", "", text[:i] + text[end:]).strip()
        if len(leftover) > 120:
            return None
        return {"function": {"name": obj["name"], "arguments": args}}
    return None


# Long listings are shown to the user directly instead of being retyped by the
# model: a 14B model asked to repeat 236 file names writes three and stops (and
# would take a minute to write them all). The model gets a short excerpt.
DISPLAY_TOOLS = {"list_directory", "search_files"}
MODEL_LISTING_LINES = 40


def listing_for_display(name: str, output: str) -> tuple[str, str] | None:
    """(block shown to the user, what the model reads) — or None when the
    output isn't a listing (an error, 'No files found.')."""
    if name not in DISPLAY_TOOLS:
        return None
    lines = output.splitlines()
    if len(lines) < 2 or not (lines[0].startswith("/") or lines[0][:4].isdigit()):
        return None
    block = "```listing\n" + output.strip() + "\n```\n\n"
    shown = "\n".join(lines[:MODEL_LISTING_LINES])
    more = len(lines) - MODEL_LISTING_LINES
    excerpt = shown + (f"\n… and {more} more lines" if more > 0 else "")
    note = ("\n\n(The COMPLETE list is already displayed to the user above your reply. "
            "Do NOT retype or re-list it. Reply with one short sentence — e.g. how many "
            "items there are or anything notable — unless they asked for something else.)")
    return block, excerpt + note


EMPTY_NUDGE = ("(Your last reply was empty. Either call the tool that does what I "
               "asked, or answer me in words.)")
EMPTY_FALLBACK = ("Sorry — I didn't manage to do that. Could you say it another way?")


_THIS_TOOLS = ("read_document", "browser_read_page", "screen_read", "open_file")


async def assemble(conversation_id: str, conv: dict, agent: agents.Agent,
                   history: list[dict], user_content: str, memories: list[dict], ctx: dict,
                   keep: int = toolpick.KEEP,
                   this: str = "", spoken: bool = False) -> tuple[list[dict], list[tools.Tool]]:
    """The model's messages and tools for a turn. The opening — base system
    prompt, then the core tools — is the same for every request and agent, so
    Ollama keeps it cached; the agent's instructions, extra tools, history and
    context come after it. Also used to warm that opening up (prefetch)."""
    dyn = _dynamic_block(memories, ctx, this, agent.prompt)
    from ..speech.engines import is_arabic
    if is_arabic(user_content):
        dyn += ("\n\nThe user wrote in ARABIC: write your whole reply in Arabic only (Arabic "
                "script) — never switch to Chinese or English, except for names and "
                "technical terms.")
    if spoken:
        dyn += ("\n\nThe user is TALKING to you and will HEAR the reply: answer in one to "
                "three short spoken sentences — no lists, tables, headings, links or source "
                "lists (still look things up with your tools first when the answer needs "
                "current facts). If there's more worth knowing, end with a short offer like "
                "\"Want the details?\"")
    history = compact.fit(conv, history)   # long conversations: summary + recent turns
    llm_messages: list[dict] = [
        {"role": "system", "content": _static_system_prompt()},
        *_with_context(_history_to_llm(history), dyn),
    ]
    # Uploaded files ride along for the whole conversation (stable between
    # uploads, so the cached prefix survives).
    try:
        from ..knowledge import attachments as attach
        attach_block = attach.prompt_block(conversation_id)
        if attach_block:
            llm_messages.insert(1, {"role": "system", "content": attach_block})
    except Exception:
        pass

    # Project memory: conversations assigned to a project carry everything
    # Jarvis knows about that project.
    if conv.get("project_id"):
        project = db.get_project(conv["project_id"])
        if project:
            other = [c["title"] for c in db.conversations_in_project(project["id"])
                     if c["id"] != conversation_id][:8]
            block = (f"ACTIVE PROJECT: {project['name']}\n"
                     f"Description: {project['description'] or '—'}\n"
                     f"Project notes (accumulated knowledge):\n"
                     f"{project['notes'][-6000:] or '(none yet)'}")
            if other:
                block += "\nOther conversations in this project: " + "; ".join(other)
            block += ("\nWhen you learn something durable about this project "
                      "(decisions, progress, preferences), save it with the "
                      "project_remember tool.")
            llm_messages.insert(1, {"role": "system", "content": block})

    if not settings.get("tools.enabled", True):
        return llm_messages, []
    # Extra tools this message needs (every schema costs prompt tokens).
    picked = await toolpick.select(user_content, _tools_for(agent), _recent_tools(history),
                                   keep=keep)
    if this:
        # "Summarize this" / "email this": be able to read what "this" is.
        picked += [x for n in _THIS_TOOLS if (x := tools.registry.get(n)) is not None]
    return llm_messages, toolpick.arrange(picked)


async def run_chat(conversation_id: str, user_content: str,
                   spoken: bool = False) -> AsyncIterator[dict]:
    started = time.perf_counter()
    db.add_message(conversation_id, "user", user_content)
    history = db.get_messages(conversation_id)
    conv = db.get_conversation(conversation_id) or {}

    # Instant commands ("open youtube", "pause") skip the model entirely.
    if conv.get("mode") != "code" and quick.enabled():
        action = await asyncio.to_thread(quick.match, user_content)
        if action is not None:
            async for event in _run_quick(conversation_id, user_content, action,
                                          history, started):
                yield event
            return

    # Memory recall and routing both need the message embedding; run them
    # together (the embedding itself is cached, so it's computed once).
    async def recall() -> list[dict]:
        try:
            return await memory_store.recall(user_content)
        except Exception:
            return []

    async def pick_agent() -> agents.Agent:
        if conv.get("mode") == "code":  # unified workspace: code mode = coding agent
            return agents.AGENTS["coding"]
        return _sticky_agent(history, user_content) or await agents.route(user_content)

    memories, agent = await asyncio.gather(recall(), pick_agent())
    if memories:
        yield {"type": "memory",
               "recalled": [{"id": m["id"], "content": m["content"]} for m in memories]}
    yield {"type": "agent", "agent": {"id": agent.id, "name": agent.name}}
    routed_ms = round((time.perf_counter() - started) * 1000)

    try:
        ctx = await app_context.snapshot_nowait()
    except Exception:
        ctx = {}

    if agent.id == "planner":
        async for event in _run_plan(conversation_id, user_content, agent, ctx, memories):
            yield event
        return

    await prefetch.claim(conversation_id)   # a warm-up in flight: let it finish first
    this = ""
    if channels.current.get() is None and selection.mentions_this(user_content):
        try:   # "email this to Sam": what is the user looking at?
            this = await asyncio.wait_for(asyncio.to_thread(selection.describe), timeout=4)
        except Exception:
            this = ""
    llm_messages, tool_list = await assemble(conversation_id, conv, agent, history,
                                             user_content, memories, ctx, this=this,
                                             spoken=spoken)
    tool_schemas = [t.to_ollama() for t in tool_list] or None

    full_response = ""
    tool_events: list[dict] = []
    max_rounds = settings.get("tools.max_iterations", 6)
    rounds: list[dict] = []
    first_token_ms = None
    nudged = False
    claim_checked = False
    intent_nudged = False
    mistakes: list[str] = []      # what went wrong this turn (-> learned test cases)

    try:
        round_no = 0
        while round_no <= max_rounds:
            # Last round: no tools, force the model to answer with what it has.
            schemas = tool_schemas if round_no < max_rounds else None
            round_text = ""
            tool_calls: list[dict] = []

            async for chunk in ollama_client.chat_stream(
                    llm_messages, model=ollama_client.model_for(agent.model_task),
                    tools=schemas):
                msg = chunk.get("message", {})
                if msg.get("content"):
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - started) * 1000)
                    round_text += msg["content"]
                    full_response += msg["content"]
                    yield {"type": "token", "content": msg["content"]}
                for tc in msg.get("tool_calls") or []:
                    tool_calls.append(tc)
                if chunk.get("done"):
                    rounds.append(_round_timing(chunk))
                    break

            if not tool_calls and schemas:
                recovered = text_tool_call(round_text, tool_list)
                if recovered:
                    mistakes.append("wrote a tool call as text")
                    audit.log("text_tool_call_recovered",
                              tool=recovered["function"]["name"], text=round_text[:200])
                    full_response = full_response[:len(full_response) - len(round_text)]
                    round_text = ""
                    yield {"type": "reset_text", "content": full_response}
                    tool_calls = [recovered]

            if not tool_calls:
                if (tool_schemas and not tool_events and not claim_checked
                        and _pretends(user_content, full_response)):
                    # "I've drafted the email" with no tool call: nothing happened.
                    # Drop the false claim and make the model act or admit it can't.
                    claim_checked = True
                    mistakes.append("claimed results without a tool")
                    audit.log("claimed_without_tool", agent=agent.id, reply=full_response[:200])
                    llm_messages.append({"role": "assistant", "content": round_text})
                    llm_messages.append({"role": "user", "content": CLAIM_NUDGE})
                    full_response = ""
                    continue
                if (tool_schemas and not intent_nudged and not tool_events
                        and _WANTS_FILE.search(user_content)):
                    # "Write a report as a Word document" answered with the
                    # report as chat text: the file was the point.
                    intent_nudged = True
                    mistakes.append("didn't create the requested file")
                    llm_messages.append({"role": "assistant", "content": round_text})
                    llm_messages.append({"role": "user", "content": FILE_NUDGE})
                    full_response = full_response[:len(full_response) - len(round_text)]
                    yield {"type": "reset_text", "content": full_response}
                    continue
                if (tool_schemas and not intent_nudged and round_text.strip()
                        and _ASKS_ACTION.search(user_content) and _STALLS.search(round_text)
                        and not any(re.search(r"ask (?:the user )?which|several", e["result"], re.I)
                                    for e in tool_events)):
                    intent_nudged = True
                    mistakes.append("asked instead of acting")
                    audit.log("stall_nudged", agent=agent.id, reply=round_text[:200])
                    llm_messages.append({"role": "assistant", "content": round_text})
                    llm_messages.append({"role": "user", "content": STALL_NUDGE})
                    full_response = full_response[:len(full_response) - len(round_text)]
                    yield {"type": "reset_text", "content": full_response}
                    continue
                if (tool_schemas and not intent_nudged and round_text.strip()
                        and _ANNOUNCES.search(round_text[-200:])):
                    # "Let me find your CV files now." — and then nothing. Hold
                    # it to what it just said it would do.
                    intent_nudged = True
                    mistakes.append("announced an action without taking it")
                    llm_messages.append({"role": "assistant", "content": round_text})
                    llm_messages.append({"role": "user", "content": INTENT_NUDGE})
                    continue
                if full_response.strip() or nudged:
                    break
                # Local models occasionally return nothing at all (no words, no
                # tool call). Ask once more instead of silently giving up.
                nudged = True
                llm_messages.append({"role": "assistant", "content": round_text})
                llm_messages.append({"role": "user", "content": EMPTY_NUDGE})
                continue

            llm_messages.append({"role": "assistant", "content": round_text,
                                 "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = _respect_intent(user_content, fn.get("name", ""))
                args = fn.get("arguments") or {}
                if isinstance(args, dict):
                    name, args = _texting(user_content, name, args)
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                out: dict = {}
                async for event in _execute_with_permission(name, args, tool_events, out):
                    yield event
                model_output = out["output"]
                if _failed(model_output):
                    model_output += FAILED_NOTE
                listing = listing_for_display(name, out["output"])
                if listing:
                    block, model_output = listing
                    full_response += block
                    yield {"type": "token", "content": block}
                llm_messages.append({"role": "tool", "content": model_output,
                                     "tool_name": name})
            round_no += 1
    except ollama_client.OllamaError as e:
        yield {"type": "error", "message": str(e)}
        return
    except Exception as e:
        audit.log("chat_error", error=str(e))
        yield {"type": "error", "message": f"Unexpected error: {e}"}
        return

    if not full_response.strip():
        full_response = EMPTY_FALLBACK
        yield {"type": "token", "content": full_response}

    timing = {"total_ms": round((time.perf_counter() - started) * 1000),
              "route_ms": routed_ms, "first_token_ms": first_token_ms,
              "rounds": rounds}
    audit.log("chat_timing", agent=agent.id, **timing)
    saved = db.add_message(conversation_id, "assistant", full_response,
                           meta={"agent": agent.id, "tools": tool_events})
    yield {"type": "done", "content": full_response, "message_id": saved["id"],
           "timing": timing}

    # Long conversation? Fold older turns into a summary before the next one.
    compact.schedule(conversation_id)
    # Learn from mistakes (or "that's wrong"): keep the request as a test case.
    try:
        learned.note_turn(conversation_id, user_content, agent.id, tool_events,
                          full_response, mistakes)
    except Exception:
        pass
    # Self-improvement: analyze this turn for capability gaps (non-blocking).
    gaps.schedule_analysis(user_content, full_response, tool_events)
    # Auto-memory: quietly learn durable facts the user shared (toggleable).
    memory_store.schedule_auto_capture(user_content)

    async for event in _auto_title(conversation_id, user_content):
        yield event


async def _auto_title(conversation_id: str, user_content: str) -> AsyncIterator[dict]:
    """Title new conversations from the first message — never ones created
    with a name ("📱 Phone chat", "⏰ Routines")."""
    if (db.get_conversation(conversation_id) or {}).get("title") != "New conversation":
        return
    conv_msgs = db.get_messages(conversation_id)
    if len([m for m in conv_msgs if m["role"] == "user"]) != 1:
        return
    title = _short_title(user_content)
    if not title:
        try:
            title = await ollama_client.chat_once([
                {"role": "user",
                 "content": "Write a title of at most 5 words for this conversation. "
                            "Reply with only the title, no quotes.\n\nUser: "
                            + user_content[:500]}],
                model=ollama_client.model_for("utility"))
            title = title.strip().strip('"')[:60]
        except Exception:
            return
    if title:
        db.rename_conversation(conversation_id, title=title)
        yield {"type": "title", "title": title}


async def _run_quick(conversation_id: str, user_content: str, action: quick.QuickAction,
                     history: list[dict], started: float) -> AsyncIterator[dict]:
    """Run an instant command: one tool call, a canned reply, no model."""
    yield {"type": "agent", "agent": {"id": "quick", "name": "Instant command"}}
    tool_events: list[dict] = []
    out: dict = {}
    denied = False
    async for event in _execute_with_permission(action.tool, action.arguments,
                                                tool_events, out):
        denied = denied or bool(event.get("denied"))
        yield event
    reply = "Okay, I won't." if denied else quick.reply_for(action, out["output"])
    yield {"type": "token", "content": reply}
    timing = {"total_ms": round((time.perf_counter() - started) * 1000),
              "route_ms": 0, "first_token_ms": None, "rounds": []}
    audit.log("chat_timing", agent="quick", tool=action.tool, **timing)
    saved = db.add_message(conversation_id, "assistant", reply,
                           meta={"agent": "quick", "tools": tool_events})
    yield {"type": "done", "content": reply, "message_id": saved["id"], "timing": timing}
    async for event in _auto_title(conversation_id, user_content):
        yield event


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {"type": "array", "items": {"type": "string"},
                  "minItems": 1, "maxItems": 6},
    },
    "required": ["steps"],
}


async def _run_plan(conversation_id: str, goal: str, agent: agents.Agent,
                    ctx: dict, memories: list[dict]) -> AsyncIterator[dict]:
    """Multi-step autonomous execution: decompose the goal, run each step with
    tools (confirmations still flow to the user), then summarize."""
    tool_list = _tools_for(agent)
    tool_names = ", ".join(t.name for t in tool_list)

    try:
        raw = await ollama_client.chat_once([
            {"role": "system", "content":
                "Decompose the user's goal into 2-6 concrete, sequential steps. "
                "Each step must be a single achievable action, phrased as an "
                "instruction. Available tools: " + tool_names},
            {"role": "user", "content": goal[:1500]},
        ], format=PLAN_SCHEMA)
        steps = [s.strip() for s in json.loads(raw).get("steps", []) if s.strip()][:6]
    except Exception as e:
        yield {"type": "error", "message": f"Could not draft a plan: {e}"}
        return
    if not steps:
        yield {"type": "error", "message": "Could not break the goal into steps."}
        return

    yield {"type": "plan", "steps": steps}
    audit.log("plan_started", goal=goal[:200], steps=steps)

    tool_events: list[dict] = []
    step_summaries: list[str] = []
    transcript = ""
    streamed = ""   # everything sent as tokens, mirrored for reset_text

    for index, step in enumerate(steps):
        yield {"type": "step", "index": index, "total": len(steps),
               "title": step, "status": "running"}
        # Later steps build on earlier ones ("write the findings into a Word
        # doc"), so hand over real content, not a one-line teaser.
        prior = "\n\n".join(f"Step {i + 1} result:\n{s}"
                            for i, s in enumerate(step_summaries))[-8000:] or "(first step)"
        step_messages: list[dict] = _with_context([
            {"role": "system", "content": _static_system_prompt()},
            {"role": "user", "content":
                f"{agent.prompt}\n\n"
                f"OVERALL GOAL: {goal}\n\nPROGRESS SO FAR:\n{prior}\n\n"
                f"CURRENT STEP ({index + 1}/{len(steps)}): {step}\n"
                f"Complete only this step now."},
        ], _dynamic_block(memories, ctx))
        # The planner may use any tool, but each step only needs a few.
        step_tools = toolpick.arrange(await toolpick.select(
            step, tool_list, {e["name"] for e in tool_events if e.get("name")}))
        schemas = [t.to_ollama() for t in step_tools] or None
        step_text = ""
        # The duplicate-call guard is per step: a later step may legitimately
        # repeat an earlier call (e.g. read the screen again).
        step_events: list[dict] = []
        step_outputs: list[str] = []

        try:
            for _round in range(4):
                use_tools = schemas if _round < 3 else None
                round_text = ""
                tool_calls: list[dict] = []
                async for chunk in ollama_client.chat_stream(
                        step_messages,
                        model=ollama_client.model_for(agent.model_task),
                        tools=use_tools):
                    msg = chunk.get("message", {})
                    if msg.get("content"):
                        round_text += msg["content"]
                        step_text += msg["content"]
                        streamed += msg["content"]
                        yield {"type": "token", "content": msg["content"]}
                    for tc in msg.get("tool_calls") or []:
                        tool_calls.append(tc)
                    if chunk.get("done"):
                        break
                if not tool_calls and use_tools:
                    recovered = text_tool_call(round_text, step_tools)
                    if recovered:
                        audit.log("text_tool_call_recovered",
                                  tool=recovered["function"]["name"], text=round_text[:200])
                        step_text = step_text[:len(step_text) - len(round_text)]
                        streamed = streamed[:len(streamed) - len(round_text)]
                        round_text = ""
                        yield {"type": "reset_text", "content": streamed}
                        tool_calls = [recovered]
                if not tool_calls:
                    break
                step_messages.append({"role": "assistant", "content": round_text,
                                      "tool_calls": tool_calls})
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    out: dict = {}
                    async for event in _execute_with_permission(
                            fn.get("name", ""), args, step_events, out):
                        yield event
                    step_messages.append({"role": "tool", "content": out["output"],
                                          "tool_name": fn.get("name", "")})
                    step_outputs.append(f"[{fn.get('name', '')}] {out['output'][:2500]}")
        except ollama_client.OllamaError as e:
            yield {"type": "error", "message": str(e)}
            return
        finally:
            tool_events.extend(step_events)

        # What later steps see: the step's own report plus what its tools
        # returned (search results, file paths...), so facts carry forward.
        summary = "\n".join([step_text.strip(), *step_outputs]).strip()[:6000] or "(no output)"
        step_summaries.append(summary)
        transcript += f"\n\n**Step {index + 1}: {step}**\n{step_text.strip()}"
        yield {"type": "step", "index": index, "total": len(steps),
               "title": step, "status": "done"}

    final = f"Plan complete — {len(steps)} steps.{transcript}"
    saved = db.add_message(conversation_id, "assistant", final,
                           meta={"agent": "planner", "tools": tool_events,
                                 "plan": steps})
    yield {"type": "done", "content": final, "message_id": saved["id"]}
    audit.log("plan_finished", steps=len(steps))


async def _execute_with_permission(name: str, args: dict, tool_events: list[dict],
                                   out: dict) -> AsyncIterator[dict]:
    """Yields UI events as they happen (crucially, confirm_request is yielded
    BEFORE blocking on the user's answer). Final tool output lands in out."""
    # Loop guard: weaker models sometimes re-call the same tool instead of
    # answering. Return the earlier result and push them to conclude.
    for prior in tool_events:
        if prior["name"] == name and prior["arguments"] == args:
            out["output"] = (
                "STOP — you already called this tool this turn and its result is "
                "above. Do NOT call any more tools. Write your final answer for "
                "the user now, based on the results you already have.")
            yield {"type": "tool_result", "name": name,
                   "result": "(skipped duplicate call)", "denied": False}
            return

    t = tools.registry.get(name)
    denied = False
    denied_label = "Denied by user"
    channel = channels.current.get()
    undo_slot, undo_token = activity.begin()   # tools leave their undo recipe here

    if t is None:
        output = f"Error: unknown tool '{name}'"
    elif t.risk == "dangerous" and channel is not None and not channel.allow_dangerous:
        # A lost or borrowed phone must not be a remote shell. The user can
        # opt in under Settings → Phone; confirmations still apply then.
        denied, denied_label = True, "Blocked from phone"
        output = (f"'{name}' is blocked when the user messages from their phone "
                  "(they can allow dangerous tools under Settings → Phone on the "
                  "Mac). Tell them it needs to be done at the Mac.")
        audit.log("tool_blocked_remote", tool=name, channel=channel.name)
    elif getattr(channel, "auto_approve", False) and name in guard.CONTROL_TOOLS:
        # Nobody is watching a routine: it never takes over the screen.
        denied, denied_label = True, "Not allowed in routines"
        output = (f"'{name}' controls the screen, which routines never do. Say what the "
                  "user should do instead.")
    elif t.needs_confirmation() and getattr(channel, "auto_approve", False):
        # A routine the user set up: nobody is there to ask. Confirm-level
        # tools (read mail, calendar, screen…) run; anything that always needs
        # the user (sending email) or is dangerous does not.
        if t.risk == "confirm" and not t.always_ask:
            yield {"type": "tool_start", "name": name, "arguments": args}
            output = await tools.execute(name, args)
        else:
            denied, denied_label = True, "Not allowed in routines"
            output = (f"'{name}' needs the user's own approval, so routines can't use it. "
                      "Say what you would have done instead.")
    elif t.needs_confirmation():
        pc = confirmations.create(name, args, t.risk)
        yield {"type": "confirm_request", "id": pc.id, "tool": name,
               "arguments": args, "risk": t.risk, "always_ask": t.always_ask}
        approved = await confirmations.wait(pc.id)
        if approved:
            yield {"type": "tool_start", "name": name, "arguments": args}
            output = await tools.execute(name, args)
        else:
            denied = True
            output = ("The user DENIED permission to run this tool. Do not retry it; "
                      "acknowledge and continue.")
    else:
        yield {"type": "tool_start", "name": name, "arguments": args}
        output = await tools.execute(name, args)

    yield {"type": "tool_result", "name": name,
           "result": denied_label if denied else output[:1000], "denied": denied}
    tool_events.append({"name": name, "arguments": args, "result": output[:2000]})
    if not denied:
        source = channel.name if channel is not None else "app"
        activity.record(name, args, output, source,
                        None if _failed(output) else undo_slot.get("undo"))
    activity.end(undo_token)
    out["output"] = output

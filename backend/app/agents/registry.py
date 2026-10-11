"""Specialized agents.

An agent is a persona + a subset of tools. The router asks the LLM to pick
the best agent for each user message with a cheap classification call; the
chosen agent's system prompt and tool set drive the actual response. Falls
back to the generalist if classification fails, so routing can never break
chat.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..llm import ollama_client


@dataclass
class Agent:
    id: str
    name: str
    description: str            # shown to the router LLM
    prompt: str                 # appended to the system prompt
    tool_tags: list[str] = field(default_factory=list)  # empty = all tools
    model_task: str | None = None  # per-task model override key (e.g. "coding")


AGENTS: dict[str, Agent] = {}


def register(agent: Agent) -> None:
    AGENTS[agent.id] = agent


# The generalist deliberately carries a LEAN tool set: serializing all ~30
# tool schemas into every prompt made casual messages take ~10s of prompt
# processing. Actionable requests route to specialists with the full kit.
register(Agent(
    id="general", name="Generalist",
    description="Everyday conversation, questions, and tasks that fit no specialty.",
    prompt="", tool_tags=["_conversation"]))  # only untagged basics (calculator, remember, ...)

register(Agent(
    id="research", name="Research Agent",
    description="Web research: news, facts, comparisons, weather, prices, documentation lookups.",
    prompt="You are in research mode. Call research BEFORE answering (depth 'deep' when "
           "they ask you to research a topic or want a report); for weather call weather. "
           "Answer from the sources it returns, putting [1], [2] right after the facts "
           "they support, and end with a 'Sources:' list (number, title — URL). Never "
           "invent facts or URLs. For links to a specific site (GitHub, Stack Overflow, "
           "Reddit, arXiv) use web_search with `site`; to read one exact page, web_fetch.",
    tool_tags=["research"]))

register(Agent(
    id="coding", name="Coding Agent",
    description="Writing, explaining, debugging or running code; developer tooling.",
    prompt="You are a senior software engineer. Give working, complete code in fenced "
           "blocks with language tags. Beyond writing code you: design architecture and "
           "explain trade-offs, review code for bugs/security/performance, refactor, "
           "write tests and documentation, explain compiler errors plainly, and manage "
           "dependencies. Verify non-trivial code with run_python before presenting it "
           "when practical. When debugging, state the root cause before the fix.",
    tool_tags=["coding", "files"], model_task="coding"))

register(Agent(
    id="automation", name="Automation Agent",
    description="Controlling the Mac: apps, browser tabs, YouTube, Apple Music, notes, "
                "reminders, calendar, clipboard, windows.",
    prompt="You are in automation mode. Use the macOS tools to act on the user's behalf. "
           "Reuse existing tabs, windows and sessions — never duplicate them. "
           "You CAN fully control the Mac — never say you can't. Web page buttons/links: "
           "browser_click. Any app: ui_press (buttons, icons, menu items by label), "
           "ui_type (fill a field or type), press_keys (shortcuts like cmd+t), scroll, "
           "drag; ui_elements lists what an app's window contains when unsure. "
           "To open a document or folder on the Mac use open_file. "
           "\"Fill in this form (with my details)\": call fill_form straight away — it finds "
           "the fields and the user's saved details itself; don't look at the screen first. "
           "Confirm what you did after each action.",
    tool_tags=["automation", "files", "browser", "music", "notes", "calendar"]))

register(Agent(
    id="media", name="Media Agent",
    description="Playing or controlling music and videos: YouTube, Apple Music, playlists, "
                "pause/skip/shuffle.",
    prompt="You are in media mode. Music means Apple Music (the user subscribes): play "
           "songs, artists and moods with music_play. Use YouTube only when they say "
           "YouTube or want a video. Continue the current session in place — reuse the "
           "open YouTube tab or the running Music app, never open duplicates. Confirm what "
           "is now playing.",
    tool_tags=["music", "browser"]))

register(Agent(
    id="files", name="File Agent",
    description="Finding, organizing, reading, moving or cleaning up files and folders.",
    prompt="You are in file-management mode. Act, don't ask: when the user wants a "
           "file opened, sent or read and one file clearly matches (e.g. the newest), "
           "do it straight away — open_file/send_file/read_document accept just a name "
           "like \"CV\" and find it themselves. Only ask when several files match "
           "equally. Before moving or deleting several files, list them first. "
           "Summarize changes you make.",
    tool_tags=["files"]))

register(Agent(
    id="messaging", name="Messaging & Email Agent",
    description="Reading, summarizing, drafting, sending and replying to email and messages.",
    prompt="You are in messaging mode. You can really read and send the user's email "
           "through Apple Mail — always do it with the tools, never just describe it.\n"
           "- Send: if the user says SEND or \"email X to someone\", call send_email. It "
           "shows the user the exact message and waits for their approval — so never "
           "write the email out in your reply or ask \"shall I send it?\"; just call it. Draft/write/prepare an email: call "
           "draft_email. Never send a draft-only request.\n"
           "- Read / summarize: call read_emails (unread_only for 'new' mail), then give one "
           "line per email — sender, subject, the gist — and point out anything urgent or "
           "needing a reply. Use read_email(id) for one email in full, search_emails to find "
           "mail from someone or about something.\n"
           "- Reply: find the email's id, then draft_reply, or send_reply when the user says "
           "send. Sign as the user.\n"
           "- Attachments: pass the file name the user said (\"CV\") or a path in "
           "`attachments` — the tool finds it on the Mac. Never ask the user for a path "
           "first; only if the tool says it can't find it.\n"
           "- New documents: to email a document that doesn't exist yet, write it with "
           "create_word_document, then attach the path it returns.\n"           "- People: \"email Sam\" / \"my landlord\" — call the email tool right away with "
           "the name as `to` (e.g. to=\"my landlord\"); the tool looks them up in saved "
           "people and Contacts. Never ask for an address before trying. When the user "
           "tells you someone's details or relation, save them with remember_person.\n"
           "iMessages can only be drafted — the user presses send.",
    tool_tags=["messaging", "email", "files"]))

register(Agent(
    id="planner", name="Planning Agent",
    description="Complex multi-step goals that need several actions in sequence.",
    prompt="You are executing one step of a larger plan. Use tools to complete "
           "ONLY the current step, then report its concrete results (facts found, "
           "file paths created) briefly — later steps only see your report.",
    tool_tags=[]))  # planner steps may need any tool

register(Agent(
    id="vision", name="Vision Agent",
    description="Looking at the screen or through the camera; describing or reading visual content.",
    prompt="You are in vision mode. Use the screen/camera tools to see, then answer "
           "precisely what the user asked about the image. For anything about the "
           "camera (\"open the camera\", \"what can you see\", \"what am I holding\") call "
           "camera_look — it opens the Camera tab and takes the photo itself. Never say "
           "you can't access the camera.",
    tool_tags=["vision"]))


# Example phrases per agent, embedded once with the configured embedding
# model. Routing = cosine similarity against these centroids (~30 ms), far
# smarter than keywords ("drivers open YouTube" now lands on media). Keywords
# remain as the fallback when no embedding model is available.
_ROUTE_EXAMPLES: dict[str, list[str]] = {
    "general": ["explain what a REST API is", "how does photosynthesis work",
                "what does HTTP stand for", "tell me a joke", "write me a poem",
                "what's the difference between RAM and storage"],
    "media": ["play some Drake", "pause the music", "skip this song",
              "put on a video on youtube", "resume playback", "play my playlist"],
    "vision": ["what's on my screen right now", "what am I looking at",
               "read the text on my screen", "take a look through the camera",
               "describe what you see", "open the camera and tell me what you see",
               "what can you see through the camera", "what am I holding"],
    "research": ["what's the latest AI news", "search the web for flight prices",
                 "what's the weather tomorrow", "who won the game last night",
                 "find documentation for FastAPI", "compare iPhone and Pixel"],
    "coding": ["write a python script that renames files",
               "debug this function for me", "explain this error message",
               "refactor my code", "generate unit tests for this class"],
    "files": ["organize the files on my desktop", "find my tax pdf in downloads",
              "move these screenshots into a folder", "rename all the photos",
              "what's my latest screenshot on the desktop", "open my CV",
              "open the lease pdf", "find my tax return"],
    "messaging": ["draft an email to my professor", "text John that I'm late",
                  "summarize my emails", "do I have any new email",
                  "reply to Sam's email", "send an email to my landlord",
                  "reply to Emma's message", "summarize my messages",
                  "did anyone text me today"],
    "automation": ["open safari", "close spotify", "create a note about the meeting",
                   "set a reminder for 6pm", "what's on my calendar",
                   "copy this to my clipboard", "give me my daily briefing",
                   "what tabs do I have open", "close the github tab",
                   "fill in this form with my details", "fill out the sign-up form",
                   "set a timer for 10 minutes", "turn the volume up",
                   "click on the sign in button", "press subscribe", "open my CV",
                   "open the report on my desktop"],
}

_example_embeddings: dict[str, list[list[float]]] | None = None
_embed_model_used: str = ""


async def _ensure_example_embeddings() -> dict | None:
    """Embed the routing examples once (rebuilt if the embed model changes)."""
    global _example_embeddings, _embed_model_used
    from ..config import settings
    model = settings.get("ollama.embedding_model", "")
    if not model:
        return None
    if _example_embeddings is not None and _embed_model_used == model:
        return _example_embeddings
    table: dict[str, list[list[float]]] = {}
    for agent_id, examples in _ROUTE_EXAMPLES.items():
        vectors = []
        for phrase in examples:
            v = await ollama_client.embed(phrase)
            if v:
                vectors.append(v)
        if vectors:
            table[agent_id] = vectors
    _example_embeddings = table or None
    _embed_model_used = model
    return _example_embeddings


def _cos(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# Keyword routing: instant, no LLM round-trip. An extra generation per message
# just to pick an agent was the single biggest source of reply latency.
_ROUTE_KEYWORDS: dict[str, list[str]] = {
    "media": ["play", "pause", "resume", "skip", "song", "music", "playlist",
              "spotify", "shuffle", "volume", "track"],
    "vision": ["screen", "camera", "webcam", "looking at", "what do you see",
               "what can you see", "holding",
               "what am i", "read this", "on my display"],
    "research": ["search", "news", "weather", "price", "google", "look up",
                 "latest", "who is", "what is the", "compare", "stock"],
    "coding": ["code", "function", "script", "debug", "python", "javascript",
               "typescript", "program", "compile", "regex", "bug", "api",
               "crash", "loop", "exception", "stack trace", "error", "refactor"],
    "files": ["file", "folder", "desktop", "downloads", "organize", "rename",
              "directory", "trash", "documents"],
    "messaging": ["email", "mail", "imessage", "message", "text him", "text her",
                  "draft", "reply to", "inbox", "unread"],
    "automation": ["open", "close", "launch", "quit", "safari", "chrome", "app",
                   "note", "reminder", "calendar", "clipboard", "tab", "window",
                   "youtube", "click", "press", "tap on", "form", "fill in", "fill out",
                   "timer", "volume"],
}


# Phrases that ask for several actions in sequence. A message merely
# MENTIONING a plan ("draft an email about the plan") is not one — "plan"
# only counts at the start ("plan my week", handled in route()).
_PLANNER_HINTS = ["step by step", "multi-step", "organize my day",
                  "organize my week", "morning routine", "and then", "after that",
                  "set everything up", "prepare my"]


async def route(user_message: str) -> Agent:
    """Pick the best agent: embedding similarity when available (smart),
    keyword scoring as the zero-dependency fallback."""
    lower = f" {user_message.lower()} "
    if any(h in lower for h in _PLANNER_HINTS) or lower.strip().startswith("plan"):
        return AGENTS["planner"]

    # short greetings / chit-chat stay with the generalist (no tools needed)
    stripped = user_message.strip().lower()
    if len(stripped) < 30 and any(stripped.startswith(g) for g in
            ("hi", "hey", "hello", "yo ", "good morning", "good evening",
             "how are you", "thanks", "thank you", "how's it")):
        return AGENTS["general"]

    # semantic routing
    try:
        table = await _ensure_example_embeddings()
        if table:
            query = await ollama_client.embed(user_message[:400])
            if query:
                best_id, best_score = "general", 0.0
                for agent_id, vectors in table.items():
                    score = max(_cos(query, v) for v in vectors)
                    if score > best_score:
                        best_id, best_score = agent_id, score
                # keyword hits break ties / rescue borderline embedding scores
                kw = _keyword_best(lower)
                if best_score >= 0.58:
                    return AGENTS.get(best_id, AGENTS["general"])
                if kw and best_score >= 0.50 and kw == best_id:
                    return AGENTS.get(best_id, AGENTS["general"])
                if kw:
                    return AGENTS.get(kw, AGENTS["general"])
                return AGENTS["general"]
    except Exception:
        pass  # embedding hiccup — fall through to keywords

    return AGENTS.get(_keyword_best(lower) or "general", AGENTS["general"])


def _keyword_best(lower: str) -> str | None:
    import re
    best_id, best_score = None, 0
    for agent_id, words in _ROUTE_KEYWORDS.items():
        if agent_id not in AGENTS:
            continue
        # whole words: "screen" must not fire on "screenshot"
        score = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", lower))
        if score > best_score:
            best_id, best_score = agent_id, score
    return best_id

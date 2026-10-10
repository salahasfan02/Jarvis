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

import datetime
import json
from typing import AsyncIterator

from .. import channels, db
from ..agents import registry as agents
from ..automation import context as app_context
from ..config import settings
from ..gaps import registry as gaps
from ..llm import ollama_client
from ..memory import store as memory_store
from ..security import audit
from ..security.permissions import confirmations
from ..tools import base as tools

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


def _static_system_prompt(agent: agents.Agent) -> str:
    """The big prompt (persona + rules; the tool schemas follow it in the
    template). It must contain NOTHING that changes between messages, so
    Ollama's prefix cache survives and prompt processing is nearly free."""
    name = settings.get("assistant.name", "Jarvis")
    persona = settings.get("assistant.persona", "").format(name=name)
    parts = [persona]
    if agent.prompt:
        parts.append(agent.prompt)
    parts.append(SMART_WINDOW_RULES)
    parts.append(
        "When a tool would help, call it instead of guessing. Some tool calls "
        "require the user's confirmation; if one is denied, respect that and "
        "explain what you would have done. A second system note carries the "
        "current time and what the user is doing — use it silently; never "
        "recite it.")
    return "\n\n".join(parts)


def _dynamic_block(memories: list[dict], ctx: dict) -> str:
    """Small, changing facts — kept OUT of the big static prompt so the cache
    prefix survives. Placed at the top of the conversation and explicitly
    marked internal so the model never echoes it back to the user."""
    parts = ["Current date/time: "
             + datetime.datetime.now().strftime("%A, %B %d %Y, %H:%M")]
    ctx_summary = app_context.summary_for_prompt(ctx)
    if ctx_summary:
        parts.append("What the user is doing right now:\n" + ctx_summary)
    if memories:
        facts = "\n".join(f"- {m['content']}" for m in memories)
        parts.append("Relevant things you remember about the user:\n" + facts)
    channel = channels.current.get()
    if channel is not None:
        parts.append(
            f"The user is messaging you from their PHONE via {channel.name}, away "
            "from this Mac. Keep replies short and phone-friendly. When they ask "
            "for a file from this Mac, find it (search_files / list_directory) and "
            "deliver it with send_file. When they ask for a document or report, "
            "write it with create_word_document, then send_file the path it returns.")
    parts.append(
        "This block is INTERNAL background awareness. Never quote, list, or "
        "repeat it, and never volunteer these details unprompted (no announcing "
        "the time or what apps are open). Mention a detail only when it is "
        "directly relevant, phrased naturally in your own words — e.g. 'I can "
        "see you're in Messages' or 'your music is paused — want me to resume "
        "it?'.")
    return "\n\n".join(parts)


def _tools_for(agent: agents.Agent) -> list[tools.Tool]:
    """The routed agent's tools, plus the remote kit on phone turns. An agent
    with no tags already sees every tool, so it is left unfiltered."""
    tags = agent.tool_tags
    if tags and channels.current.get() is not None:
        tags = [*tags, *channels.REMOTE_TOOL_TAGS]
    return tools.registry.for_agent(tags)


def _history_to_llm(history: list[dict]) -> list[dict]:
    msgs = []
    for m in history:
        if m["role"] in ("user", "assistant"):
            msgs.append({"role": m["role"], "content": m["content"]})
    return msgs


async def run_chat(conversation_id: str, user_content: str) -> AsyncIterator[dict]:
    db.add_message(conversation_id, "user", user_content)
    history = db.get_messages(conversation_id)

    memories = []
    try:
        memories = await memory_store.recall(user_content)
    except Exception:
        pass
    if memories:
        yield {"type": "memory",
               "recalled": [{"id": m["id"], "content": m["content"]} for m in memories]}

    # Code-mode conversations always use the coding agent (unified workspace).
    conv = db.get_conversation(conversation_id) or {}
    if conv.get("mode") == "code":
        agent = agents.AGENTS["coding"]
    else:
        agent = await agents.route(user_content)
    yield {"type": "agent", "agent": {"id": agent.id, "name": agent.name}}

    try:
        ctx = await app_context.snapshot_nowait()
    except Exception:
        ctx = {}

    if agent.id == "planner":
        async for event in _run_plan(conversation_id, user_content, agent, ctx, memories):
            yield event
        return

    history_msgs = _history_to_llm(history)
    dyn = _dynamic_block(memories, ctx)
    # Dynamic context sits at the TOP (its natural system position — models
    # echo mid-conversation system messages) while the huge static prompt +
    # tool schemas before it stay byte-identical for Ollama's prefix cache.
    llm_messages: list[dict] = [
        {"role": "system", "content": _static_system_prompt(agent)},
        {"role": "system", "content": dyn},
        *history_msgs,
    ]
    # Uploaded files ride along for the whole conversation (stable between
    # uploads, so it sits before the changing dynamic block for cacheability).
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

    use_tools = settings.get("tools.enabled", True)
    tool_list = _tools_for(agent) if use_tools else []
    tool_schemas = [t.to_ollama() for t in tool_list] or None

    full_response = ""
    tool_events: list[dict] = []
    max_rounds = settings.get("tools.max_iterations", 6)

    try:
        for round_no in range(max_rounds + 1):
            # Last round: no tools, force the model to answer with what it has.
            schemas = tool_schemas if round_no < max_rounds else None
            round_text = ""
            tool_calls: list[dict] = []

            async for chunk in ollama_client.chat_stream(
                    llm_messages, model=ollama_client.model_for(agent.model_task),
                    tools=schemas):
                msg = chunk.get("message", {})
                if msg.get("content"):
                    round_text += msg["content"]
                    full_response += msg["content"]
                    yield {"type": "token", "content": msg["content"]}
                for tc in msg.get("tool_calls") or []:
                    tool_calls.append(tc)
                if chunk.get("done"):
                    break

            if not tool_calls:
                break

            llm_messages.append({"role": "assistant", "content": round_text,
                                 "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                out: dict = {}
                async for event in _execute_with_permission(name, args, tool_events, out):
                    yield event
                llm_messages.append({"role": "tool", "content": out["output"],
                                     "tool_name": name})
    except ollama_client.OllamaError as e:
        yield {"type": "error", "message": str(e)}
        return
    except Exception as e:
        audit.log("chat_error", error=str(e))
        yield {"type": "error", "message": f"Unexpected error: {e}"}
        return

    saved = db.add_message(conversation_id, "assistant", full_response,
                           meta={"agent": agent.id, "tools": tool_events})
    yield {"type": "done", "content": full_response, "message_id": saved["id"]}

    # Self-improvement: analyze this turn for capability gaps (non-blocking).
    gaps.schedule_analysis(user_content, full_response, tool_events)
    # Auto-memory: quietly learn durable facts the user shared (toggleable).
    memory_store.schedule_auto_capture(user_content)

    # Auto-title new conversations from the first exchange.
    conv_msgs = db.get_messages(conversation_id)
    if len([m for m in conv_msgs if m["role"] == "user"]) == 1:
        try:
            title = await ollama_client.chat_once([
                {"role": "user",
                 "content": "Write a title of at most 5 words for this conversation. "
                            "Reply with only the title, no quotes.\n\nUser: "
                            + user_content[:500]}],
                model=ollama_client.model_for("utility"))
            title = title.strip().strip('"')[:60]
            if title:
                db.rename_conversation(conversation_id, title=title)
                yield {"type": "title", "title": title}
        except Exception:
            pass


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

    for index, step in enumerate(steps):
        yield {"type": "step", "index": index, "total": len(steps),
               "title": step, "status": "running"}
        # Later steps build on earlier ones ("write the findings into a Word
        # doc"), so hand over real content, not a one-line teaser.
        prior = "\n\n".join(f"Step {i + 1} result:\n{s}"
                            for i, s in enumerate(step_summaries))[-8000:] or "(first step)"
        step_messages: list[dict] = [
            {"role": "system", "content": _static_system_prompt(agent)},
            {"role": "system", "content": _dynamic_block(memories, ctx)},
            {"role": "user", "content":
                f"OVERALL GOAL: {goal}\n\nPROGRESS SO FAR:\n{prior}\n\n"
                f"CURRENT STEP ({index + 1}/{len(steps)}): {step}\n"
                f"Complete only this step now."},
        ]
        schemas = [t.to_ollama() for t in tool_list] or None
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
                        yield {"type": "token", "content": msg["content"]}
                    for tc in msg.get("tool_calls") or []:
                        tool_calls.append(tc)
                    if chunk.get("done"):
                        break
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
    elif t.needs_confirmation():
        pc = confirmations.create(name, args, t.risk)
        yield {"type": "confirm_request", "id": pc.id, "tool": name,
               "arguments": args, "risk": t.risk}
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
    tool_events.append({"name": name, "arguments": args, "result": output[:500]})
    out["output"] = output

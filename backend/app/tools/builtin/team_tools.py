"""Hand a task to an agent team from chat, voice or the phone: "ask my startup
team to build a landing page for my bakery".

A team works for minutes, so it runs in the background (the Agent teams tab
shows it live). When it's done its answer is added to the chat it was asked
in, announced in the app, and sent to the phone if that's where it came from.
"""
from __future__ import annotations

import functools
import re

from ... import channels, db, ui_bridge
from ..base import tool


def _plain(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[#*_`>|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


async def _report(channel, conversation_id: str | None, run) -> None:
    from ...teams import engine
    name = run.team["name"]
    if run.status == "done":
        title, text = f"{name} finished", run.final
    elif run.status == "stopped":
        title, text = f"{name} was stopped", "It was stopped before it finished."
    else:
        title, text = f"{name} couldn't finish", run.error or "Something went wrong."
    body = f"**{title}** — “{run.task[:200]}”\n\n{text}"
    if run.preview:
        body += f"\n\nLive preview: {engine._origin()}{run.preview}"
    if conversation_id and db.get_conversation(conversation_id):
        db.add_message(conversation_id, "assistant", body, meta={"agent": "team"})
    if channel is not None and channel.name == "Telegram" and hasattr(channel, "send_text"):
        await channel.send_text(body)
    await ui_bridge.announce(title, _plain(text)[:280], speak=False,
                             conversation_id=conversation_id)


@tool(
    name="run_agent_team",
    description="Hand a task to one of the user's own agents or agent teams (made in the "
                "Agents tab, e.g. an IT team or a startup team, or a single agent like a "
                "writer): a team's lead works out what's needed, briefs the right agents "
                "and brings their work together. Use it whenever they say to use, ask or "
                "tell one of their agents or teams. It runs in the background and reports "
                "back here when done. task = everything the user said about it; team = the "
                "agent's or team's name (optional when they have one).",
    parameters={
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "what the team should do, in full"},
            "team": {"type": "string", "description": "which agent or team (optional)"},
        },
        "required": ["task"],
    },
    risk="confirm",          # minutes of the model's time: the user says yes first
)
async def run_agent_team(task: str, team: str = "") -> str:
    from ...teams import engine, store
    chosen = store.find(team)
    if isinstance(chosen, str):
        return chosen
    run = engine.start(chosen, task)
    if isinstance(run, str):
        return run
    run.on_done.append(functools.partial(_report, channels.current.get(),
                                         channels.conversation.get()))
    if store.is_single(chosen):
        return (f"{chosen['name']} is on it. It works in the background — follow along in "
                "Agents; the result will come back here when it's done.")
    lead = run.agent(run.team["lead"])["name"]
    return (f"Handed it to {chosen['name']}: {lead} is briefing the team now. It runs in the "
            "background — follow along in Agents; the result will come back here when "
            "it's done.")

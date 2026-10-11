"""Desktop chats are unchanged by the phone channel: no remote-only tools,
and dangerous tools still go through the normal confirmation dialog."""
import asyncio

from app import db
from app.chat import service
from app.llm import ollama_client
from app.security.permissions import confirmations


def test_desktop_turns_keep_their_tools_and_confirmations(monkeypatch):
    offered = []

    async def chat_stream(messages, model=None, tools=None):
        offered.append([t["function"]["name"] for t in tools or []])
        if len(offered) == 1:
            yield {"message": {"content": "", "tool_calls": [
                {"function": {"name": "run_command", "arguments": {"command": "ls"}}}]},
                "done": True}
        else:
            yield {"message": {"content": "ok"}, "done": True}

    monkeypatch.setattr(ollama_client, "chat_stream", chat_stream)
    conv = db.create_conversation()

    async def main():
        events = []
        async for event in service.run_chat(conv["id"], "research the news then run ls"):
            events.append(event)
            if event["type"] == "confirm_request":
                confirmations.resolve(event["id"], False)  # user clicks Deny
        return events

    events = asyncio.run(main())
    kinds = [e["type"] for e in events]
    assert "confirm_request" in kinds          # asked, not blocked
    assert "create_word_document" in offered[0]
    assert events[-1]["type"] in ("done", "title")

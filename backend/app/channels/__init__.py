"""Remote channels: talk to Jarvis from outside the Mac (Telegram today).

A channel turns an incoming message into a normal chat turn — same agents,
tools, memory and permission checks as the desktop UI — and delivers the
reply back. While a turn runs, `current` holds the channel session, so tools
like send_file know where "send it to me" goes and the chat loop can apply
remote-only rules (e.g. no dangerous tools from the phone by default).
"""
from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

# Extra tool tags every remote turn gets on top of the routed agent's own
# tools: whatever agent the router picks, "find X and send it to me" and
# "research Y into a Word doc" must work from the phone.
REMOTE_TOOL_TAGS = ["remote", "files", "research"]


class ChannelSession:
    """One remote conversation (e.g. a Telegram chat) for the duration of a turn."""

    name = "remote"            # shown to the model: "via <name>"
    allow_dangerous = False    # may dangerous tools run (with confirmation)?
    max_file_bytes = 50 * 1024 * 1024

    async def send_file(self, path: Path, caption: str = "") -> str:
        raise NotImplementedError

    async def send_text(self, text: str) -> str:
        raise NotImplementedError


current: ContextVar[ChannelSession | None] = ContextVar("jarvis_channel", default=None)
# The conversation the running turn belongs to ("send me the whole chat").
conversation: ContextVar[str | None] = ContextVar("jarvis_conversation", default=None)

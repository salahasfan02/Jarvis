"""Tool framework.

A Tool declares a JSON-schema for its parameters (sent to the LLM for native
tool calling) and a risk level that drives the permission system:

  safe      -> runs immediately
  confirm   -> requires explicit user confirmation in the UI before running
  dangerous -> always requires confirmation; "always allow" is not offered

User overrides in settings.permissions can relax "confirm" to "always" or
block a tool entirely with "never". Dangerous tools can never be relaxed.
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..config import settings
from ..security import audit


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]              # JSON schema {"type":"object",...}
    handler: Callable[..., Awaitable[str] | str]
    risk: str = "safe"                       # safe | confirm | dangerous
    agent_tags: list[str] = field(default_factory=list)

    def to_ollama(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def needs_confirmation(self) -> bool:
        if self.risk == "safe":
            return False
        if self.risk == "dangerous":
            return True
        override = settings.get(f"permissions.{self.name}")
        return override != "always"

    def is_blocked(self) -> bool:
        return settings.get(f"permissions.{self.name}") == "never"

    async def run(self, **kwargs) -> str:
        if inspect.iscoroutinefunction(self.handler):
            result = await self.handler(**kwargs)
        else:
            # Sync handlers (subprocess, AppleScript) run in a worker thread so a
            # slow one can't freeze the event loop — the phone bot, the Stop
            # button and the dashboard keep working, and the timeout can fire.
            # A sync handler that needs the loop must be declared `async def`.
            result = await asyncio.to_thread(self.handler, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        return str(result)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def for_agent(self, tags: list[str] | None = None) -> list[Tool]:
        tools = [t for t in self._tools.values() if not t.is_blocked()]
        if tags:
            tools = [t for t in tools if not t.agent_tags
                     or any(tag in t.agent_tags for tag in tags)]
        return tools


registry = ToolRegistry()

# Names of tools currently executing — surfaced live on the dashboard.
running_now: dict[str, float] = {}


def tool(name: str, description: str, parameters: dict[str, Any],
         risk: str = "safe", agent_tags: list[str] | None = None):
    """Decorator used by built-in tools and plugins alike."""
    def wrap(fn):
        registry.register(Tool(name=name, description=description,
                               parameters=parameters, handler=fn, risk=risk,
                               agent_tags=agent_tags or []))
        return fn
    return wrap


async def execute(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool by name, recording the outcome in the audit log."""
    t = registry.get(name)
    if t is None:
        return f"Error: unknown tool '{name}'"
    if t.is_blocked():
        audit.log("tool_blocked", tool=name, arguments=arguments)
        return f"Error: tool '{name}' is disabled in permissions settings"
    audit.log("tool_start", tool=name, arguments=arguments)
    import time
    running_now[name] = time.time()
    try:
        result = await asyncio.wait_for(t.run(**arguments), timeout=120)
        audit.log("tool_ok", tool=name, result_preview=result[:300])
        return result
    except asyncio.TimeoutError:
        audit.log("tool_error", tool=name, error="timeout")
        return f"Error: tool '{name}' timed out"
    except Exception as e:  # tools must never crash the chat loop
        audit.log("tool_error", tool=name, error=str(e))
        return f"Error running {name}: {e}"
    finally:
        running_now.pop(name, None)

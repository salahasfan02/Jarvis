"""Run the user's macOS Shortcuts: HomeKit scenes, Focus modes, app actions —
anything they've built in the Shortcuts app becomes something Jarvis can do."""
from __future__ import annotations

import asyncio
import difflib
import subprocess
import tempfile
from pathlib import Path

from ..base import tool


def _names() -> list[str]:
    try:
        r = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def _match(name: str, names: list[str]) -> tuple[str | None, list[str]]:
    want = name.strip().lower()
    exact = [n for n in names if n.lower() == want]
    if exact:
        return exact[0], []
    contains = [n for n in names if want and want in n.lower()]
    if len(contains) == 1:
        return contains[0], []
    close = difflib.get_close_matches(want, [n.lower() for n in names], n=5, cutoff=0.6)
    options = contains or [n for n in names if n.lower() in close]
    if len(options) == 1:
        return options[0], []
    return None, options


@tool(
    name="list_shortcuts",
    description="List the user's macOS Shortcuts (from the Shortcuts app).",
    parameters={"type": "object", "properties": {}},
    agent_tags=["automation"],
)
async def list_shortcuts() -> str:
    names = await asyncio.to_thread(_names)
    if not names:
        return "No Shortcuts found (the user can create some in the Shortcuts app)."
    return f"{len(names)} shortcuts:\n" + "\n".join(f"- {n}" for n in names)


@tool(
    name="run_shortcut",
    description="Run one of the user's macOS Shortcuts by name — e.g. HomeKit scenes "
                "(\"Movie time\", \"Lights off\"), Focus modes, or any action they built in "
                "the Shortcuts app. Optional text input; returns the shortcut's output.",
    parameters={"type": "object", "properties": {
        "name": {"type": "string", "description": "the shortcut's name (close is fine)"},
        "input": {"type": "string", "description": "optional text to pass in"},
    }, "required": ["name"]},
    risk="confirm",
    agent_tags=["automation"],
)
async def run_shortcut(name: str, input: str = "") -> str:  # noqa: A002 — the model's word
    names = await asyncio.to_thread(_names)
    if not names:
        return "No Shortcuts found — the user can create them in the Shortcuts app."
    match, options = _match(name, names)
    if match is None:
        if options:
            return f"Several shortcuts could be '{name}': {', '.join(options)} — ask which."
        return f"No shortcut called '{name}'. Available: {', '.join(names[:30])}"

    def run() -> str:
        with tempfile.TemporaryDirectory() as tmp:
            cmd = ["shortcuts", "run", match, "--output-path", str(Path(tmp) / "out")]
            if input:
                src = Path(tmp) / "input.txt"
                src.write_text(input)
                cmd += ["--input-path", str(src)]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=110)
            except subprocess.TimeoutExpired:
                return f"Failed: “{match}” didn't finish within 2 minutes."
            if r.returncode != 0:
                return f"Failed: “{match}”: {(r.stderr or r.stdout).strip()[:300]}"
            out = Path(tmp) / "out"
            text = ""
            if out.exists():
                try:
                    text = out.read_text(errors="replace").strip()[:3000]
                except OSError:
                    text = ""
            return f"Ran “{match}”." + (f" Output:\n{text}" if text else "")
    return await asyncio.to_thread(run)

"""Terminal, screen and camera tools."""
from __future__ import annotations

import ast
import asyncio
import base64
import datetime
import math
import operator
import subprocess
import tempfile
from pathlib import Path

from ...config import settings
from ..base import tool


@tool(
    name="run_command",
    description="Run a shell command in the user's terminal environment and return its "
                "output. Use for developer tasks the user asked for.",
    parameters={
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    risk="dangerous",
    agent_tags=["coding", "automation"],
)
def run_command(command: str) -> str:
    result = subprocess.run(command, shell=True, capture_output=True, text=True,
                            timeout=60, cwd=str(Path.home()))
    out = (result.stdout + result.stderr).strip()
    return f"exit code {result.returncode}\n{out[:8000]}" if out else f"exit code {result.returncode}"


@tool(
    name="current_datetime",
    description="Get the current local date and time.",
    parameters={"type": "object", "properties": {}},
)
def current_datetime() -> str:
    return datetime.datetime.now().strftime("%A, %B %d %Y, %H:%M:%S")


@tool(
    name="calculator",
    description="Evaluate a mathematical expression, e.g. '2**10 + 5' or 'round(17.5 * 0.0825, 2)'.",
    parameters={
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    },
)
def calculator(expression: str) -> str:
    try:
        return str(safe_eval(expression))
    except (ValueError, TypeError, ZeroDivisionError, OverflowError, SyntaxError) as e:
        return f"Could not evaluate: {e}"


_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {n: f for n in dir(math) if not n.startswith("_") and callable(f := getattr(math, n))}
_FUNCS.update(abs=abs, round=round, min=min, max=max, sum=sum)
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}
_HEAVY = {"factorial", "comb", "perm"}  # cheap to ask for, can take hours to compute


def safe_eval(expression: str):
    """Arithmetic only. The old eval() with empty builtins was escapable
    (().__class__.__base__.__subclasses__() reaches os.popen), and this tool
    runs without asking — any web page or document the model read could have
    used it to run shell commands. Now only numbers, operators and math
    functions are understood; everything else is refused."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10_000:
                raise ValueError("exponent too large")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCS and not node.keywords):
            args = [ev(a) for a in node.args]
            if node.func.id in _HEAVY and any(abs(a) > 10_000 for a in args):
                raise ValueError("number too large")
            return _FUNCS[node.func.id](*args)
        if isinstance(node, (ast.List, ast.Tuple)):  # sum([1, 2]), max(3, 4)
            return [ev(e) for e in node.elts]
        raise ValueError("only numbers, arithmetic and math functions are allowed")

    if len(expression) > 500:
        raise ValueError("expression too long")
    return ev(ast.parse(expression, mode="eval"))


async def _describe_image(path: Path, question: str) -> str:
    """Send an image to the configured multimodal model."""
    from ...llm import ollama_client
    vision_model = settings.get("ollama.vision_model", "")
    if not vision_model:
        return ("Image captured at " + str(path) + ", but no vision model is configured. "
                "Set one in Settings (e.g. pull 'llava' or 'llama3.2-vision').")
    img_b64 = base64.b64encode(path.read_bytes()).decode()
    text = await ollama_client.chat_once(
        [{"role": "user", "content": question, "images": [img_b64]}],
        model=vision_model)
    return text or "The vision model returned no description."


@tool(
    name="screen_look",
    description="Capture the user's screen and describe what's on it, or answer a "
                "question about it. Requires Screen Recording permission for the app.",
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string",
                                    "description": "what to look for; default: describe the screen"}},
    },
    risk="confirm",
    agent_tags=["vision"],
)
async def screen_look(question: str = "Describe what is on this screen.") -> str:
    path = Path(tempfile.mkstemp(suffix=".png")[1])
    proc = await asyncio.create_subprocess_exec("screencapture", "-x", str(path))
    await proc.wait()
    if not path.exists() or path.stat().st_size == 0:
        return "Screen capture failed — check Screen Recording permission in System Settings."
    try:
        return await _describe_image(path, question)
    finally:
        path.unlink(missing_ok=True)


@tool(
    name="screen_read",
    description="Read the EXACT text on the user's screen using Apple's OCR (same "
                "engine as Live Text). Use when the user wants text read, copied, "
                "summarized or checked precisely. For describing images/layout, "
                "use screen_look instead.",
    parameters={"type": "object", "properties": {}},
    risk="confirm",
    agent_tags=["vision"],
)
async def screen_read() -> str:
    from ...vision import ocr
    path = Path(tempfile.mkstemp(suffix=".png")[1])
    proc = await asyncio.create_subprocess_exec("screencapture", "-x", str(path))
    await proc.wait()
    if not path.exists() or path.stat().st_size == 0:
        return "Screen capture failed — check Screen Recording permission in System Settings."
    try:
        text = await ocr.ocr_file(path)
        return text[:8000] if text.strip() else "No text was recognized on the screen."
    except Exception as e:
        return f"OCR failed: {e}"
    finally:
        path.unlink(missing_ok=True)


@tool(
    name="camera_look",
    description="Take a photo with the webcam and describe what the camera sees, or "
                "answer a question about it. Requires the 'imagesnap' utility "
                "(brew install imagesnap) and camera permission.",
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string",
                                    "description": "what to look for; default: describe the view"}},
    },
    risk="confirm",
    agent_tags=["vision"],
)
async def camera_look(question: str = "Describe what you see.") -> str:
    path = Path(tempfile.mkstemp(suffix=".jpg")[1])
    try:
        proc = await asyncio.create_subprocess_exec(
            "imagesnap", "-w", "1.5", str(path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
    except FileNotFoundError:
        return "Camera capture needs the 'imagesnap' utility. Install it with: brew install imagesnap"
    if not path.exists() or path.stat().st_size == 0:
        return "Camera capture failed — check camera permission."
    try:
        return await _describe_image(path, question)
    finally:
        path.unlink(missing_ok=True)


@tool(
    name="search_documents",
    description="Search the user's ingested documents (PDFs, notes, files added to the "
                "knowledge base) and return the most relevant passages. Use whenever a "
                "question might be answered by the user's own files.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)
async def search_documents(query: str) -> str:
    from ...knowledge import store as knowledge
    results = await knowledge.search(query)
    if not results:
        return ("No matching passages. The knowledge base may be empty — the user can "
                "add documents in the Memory page.")
    return "\n\n".join(
        f"[{r['document']}] (relevance {r['score']})\n{r['content'][:800]}"
        for r in results)


@tool(
    name="run_python",
    description="Execute a short Python script in a SANDBOX (no network, file writes "
                "confined to a temp folder, 20s timeout) and return stdout/stderr. "
                "Use for calculations, data transforms, or verifying code you wrote.",
    parameters={
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
    },
    risk="confirm",
    agent_tags=["coding"],
)
async def run_python(code: str) -> str:
    from ...sandbox import runner
    result = await runner.run(code, "python")
    if result.get("error"):
        return f"Error: {result['error']}"
    out = f"exit code {result['exit_code']}"
    if result["stdout"]:
        out += f"\nstdout:\n{result['stdout']}"
    if result["stderr"]:
        out += f"\nstderr:\n{result['stderr']}"
    return out


@tool(
    name="create_skill",
    description="Permanently teach yourself a NEW ability by installing a plugin. Write "
                "complete Python code using EXACTLY this framework:\n"
                "from app.tools.base import tool\n"
                "@tool(name='tool_name', description='when to use it', "
                "parameters={'type':'object','properties':{...},'required':[...]}, "
                "risk='safe'|'confirm'|'dangerous')\n"
                "def tool_name(...) -> str: ...\n"
                "Handlers may be async. Use subprocess+osascript for Mac apps, httpx for "
                "web APIs. The user must approve installation; the new tools work "
                "immediately afterwards.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "short skill name, e.g. 'volume_control'"},
            "code": {"type": "string", "description": "the complete plugin.py source"},
        },
        "required": ["name", "code"],
    },
    risk="dangerous",   # always requires the user's explicit approval
)
def create_skill(name: str, code: str) -> str:
    from ...plugins import loader
    try:
        result = loader.install_skill(name, code)
    except ValueError as e:
        return f"Skill rejected: {e}. Fix the code and call create_skill again."
    tools_txt = ", ".join(result["new_tools"]) or "(no new tools registered!)"
    return (f"Skill '{result['skill']}' installed at {result['path']}. "
            f"New tools available right now: {tools_txt}")


@tool(
    name="project_remember",
    description="Save a durable fact, decision or progress note to the ACTIVE project's "
                "memory (shown in your context as ACTIVE PROJECT). Use whenever something "
                "worth remembering about the project happens.",
    parameters={
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "description": "the project's name"},
            "note": {"type": "string", "description": "one self-contained fact or decision"},
        },
        "required": ["project_name", "note"],
    },
)
def project_remember(project_name: str, note: str) -> str:
    from ... import db
    project = db.find_project_by_name(project_name)
    if not project:
        names = ", ".join(p["name"] for p in db.list_projects()) or "(no projects exist)"
        return f"No project named '{project_name}'. Existing projects: {names}"
    db.append_project_note(project["id"], note)
    return f"Saved to project '{project['name']}': {note}"


@tool(
    name="daily_briefing",
    description="Gather the user's daily briefing data: current weather and today's "
                "forecast, today's calendar events, and reminders. Use when the user asks "
                "for their briefing, their day, or what's coming up today. Present the "
                "result as a warm, concise morning-briefing narrative.",
    parameters={"type": "object", "properties": {}},
    risk="confirm",
)
async def daily_briefing() -> str:
    import subprocess

    import httpx
    parts = [f"Now: {datetime.datetime.now().strftime('%A, %B %d %Y, %H:%M')}"]

    # weather (wttr.in geolocates by IP; no API key, local-friendly)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://wttr.in/?format=j1")
            w = r.json()
            cur = w["current_condition"][0]
            today = w["weather"][0]
            area = w.get("nearest_area", [{}])[0]
            city = area.get("areaName", [{}])[0].get("value", "your area")
            parts.append(
                f"Weather in {city}: {cur['weatherDesc'][0]['value']}, "
                f"{cur['temp_C']}°C (feels {cur['FeelsLikeC']}°C). "
                f"Today: {today['mintempC']}–{today['maxtempC']}°C, "
                f"sunrise {today['astronomy'][0]['sunrise']}, "
                f"sunset {today['astronomy'][0]['sunset']}.")
    except Exception as e:
        parts.append(f"Weather unavailable ({e}).")

    # today's calendar
    def osa(script: str) -> str:
        try:
            res = subprocess.run(["osascript", "-e", script],
                                 capture_output=True, text=True, timeout=60)
            return res.stdout.strip()
        except Exception:
            return ""

    from .calendars import events_text  # EventKit: fast, includes repeating events
    events = await asyncio.to_thread(events_text, 0, 1)
    parts.append("Today's calendar:\n" + events)

    reminders = await asyncio.to_thread(osa, '''
    set output to ""
    tell application "Reminders"
        set rs to (every reminder whose completed is false)
        repeat with r in rs
            set output to output & "- " & (name of r) & "\\n"
        end repeat
    end tell
    return output''')
    if reminders:
        lines = reminders.splitlines()[:10]
        parts.append("Open reminders:\n" + "\n".join(lines))

    return "\n\n".join(parts)


@tool(
    name="watch_screen",
    description="Watch the user's screen in the background and notify them when a "
                "condition becomes true — e.g. 'the download finishes', 'the build "
                "goes green', 'the render completes'. Returns immediately; a macOS "
                "notification fires when it triggers.",
    parameters={
        "type": "object",
        "properties": {
            "condition": {"type": "string", "description": "what to watch for, in plain words"},
            "interval_seconds": {"type": "integer", "description": "how often to check (default 15)"},
        },
        "required": ["condition"],
    },
    risk="confirm",
    agent_tags=["vision"],
)
async def watch_screen(condition: str, interval_seconds: int = 15) -> str:  # schedules a task
    from ...vision import watcher
    w = watcher.start(condition, interval_seconds)
    return (f"Watching your screen (check #{w.id}) every {w.interval}s for: "
            f"“{condition}”. I'll notify you when it happens. Say 'stop watching' "
            f"to cancel.")


@tool(
    name="stop_watching",
    description="Stop screen watches started with watch_screen.",
    parameters={"type": "object", "properties": {}},
    agent_tags=["vision"],
)
async def stop_watching() -> str:  # cancels tasks (loop-only)
    from ...vision import watcher
    n = watcher.stop()
    return f"Stopped {n} screen watch(es)." if n else "No active screen watches."


@tool(
    name="remember_screen",
    description="Look at the screen RIGHT NOW, summarize what the user is doing, and "
                "save it to long-term memory. Use for 'remember what's on my screen' or "
                "'note what I'm working on'.",
    parameters={"type": "object", "properties": {}},
    risk="confirm",
    agent_tags=["vision"],
)
async def remember_screen() -> str:
    from ...vision import watcher
    from ...memory import store
    text = await watcher._capture_text()
    if len(text.strip()) < 20:
        return "The screen looks empty or I couldn't read it (check Screen Recording permission)."
    summary = await __import__("app.llm.ollama_client", fromlist=["chat_once"]).chat_once([
        {"role": "system", "content":
            "Summarize what the user is doing from their screen text in one concise "
            "sentence starting with 'The user'."},
        {"role": "user", "content": text[:3500]},
    ])
    summary = (summary or "").strip().strip('"')
    if not summary:
        return "Couldn't summarize the screen."
    import time as _t
    await store.save(f"[{_t.strftime('%Y-%m-%d %H:%M')}] {summary}", "activity")
    return f"Saved to memory: {summary}"


@tool(
    name="start_screen_memory",
    description="Start WATCHING the screen in the background: every few minutes Jarvis "
                "captures the screen, summarizes what the user is doing, and saves it to "
                "memory (category 'activity'). Use for 'watch my screen and remember what "
                "I do' / 'keep a log of my activity'. Runs until stopped.",
    parameters={
        "type": "object",
        "properties": {"interval_minutes": {"type": "integer",
                       "description": "how often to capture (default 5)"}},
    },
    risk="confirm",
    agent_tags=["vision"],
)
async def start_screen_memory(interval_minutes: int = 5) -> str:  # schedules a task
    from ...vision import journal
    st = journal.start(int(max(1, interval_minutes)) * 60)
    return (f"Now watching your screen every {st['interval'] // 60} min and saving what "
            f"you're doing to memory. Say 'stop watching my screen' to stop.")


@tool(
    name="stop_screen_memory",
    description="Stop the background screen-memory watcher started with start_screen_memory.",
    parameters={"type": "object", "properties": {}},
    agent_tags=["vision"],
)
async def stop_screen_memory() -> str:  # cancels a task (loop-only)
    from ...vision import journal
    st = journal.stop()
    return f"Stopped watching your screen. Saved {st['saved']} activity notes this session."


@tool(
    name="remember",
    description="Save a fact to long-term memory so it persists across conversations. "
                "Use when the user shares preferences, projects, contacts, goals, or "
                "says 'remember that...'.",
    parameters={
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "a single self-contained fact"},
            "category": {"type": "string",
                         "description": "preference | project | contact | goal | general"},
        },
        "required": ["fact"],
    },
)
async def remember(fact: str, category: str = "general") -> str:
    from ...memory import store
    await store.save(fact, category)
    return f"Remembered: {fact}"

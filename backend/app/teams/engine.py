"""Running an agent team: the user talks to the lead; work flows along the links.

    lead ── has teammates? It plans: which of them, in what order, and a
     │      detailed brief for each (structured output, so it's always readable)
     ├──▶ teammate with no teammates: does it — its role, its skills, the brief
     ├──▶ teammate with teammates: plans for ITS teammates the same way
     └──  brings what came back together into one answer for the user

Teammates work one at a time, in the plan's order, and each sees what the
earlier ones produced (the frontend gets the backend's API). One run at a
time: a local model serves one request well, not five at once.

Skills are safe by construction, so a run never stops to ask: web research,
and files in the run's own workspace (~/.jarvis/projects/teams/<run>/), which
the backend serves at /projects/… — a page saved there is live at once,
which is how the frontend agent deploys. Nothing else on the Mac is touched.

Every step is an event (agent_status, handoff, agent_token, agent_tool,
file, final, done …): the canvas follows a run live, and can rejoin one
that's in progress — follow() replays what happened so far first.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.parse
import uuid
from pathlib import Path

from ..chat import service as chat_service
from ..config import JARVIS_HOME
from ..llm import ollama_client
from ..security import audit
from ..tools import base as tools
from . import store

PROJECTS = JARVIS_HOME / "projects"
MAX_DEPTH = 4            # lead -> teammate -> their teammate …
MAX_ROUNDS = 5           # tool rounds per agent turn
MAX_FILES = 200
MAX_FILE_CHARS = 400_000
REPORT_BUDGET = 16_000   # characters of teammates' reports a lead reads to combine them
EARLIER_BUDGET = 6_000   # ...and a teammate reads of the work done before it
CONTEXT_BUDGET = 26_000  # an agent's whole conversation, so the model's context holds it
RESEARCH_TOOLS = ("research", "web_search", "web_fetch")
KEEP_FINISHED = 10       # finished runs kept in memory (all are in the database)

RUNS: dict[str, "Run"] = {}
_active: "Run | None" = None


def _origin() -> str:
    return f"http://127.0.0.1:{os.environ.get('JARVIS_PORT', 8765)}"


class Run:
    def __init__(self, team: dict, task: str, workspace: Path) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.team = team
        self.task = task
        self.workspace = workspace
        self.web = "/projects/" + workspace.relative_to(PROJECTS).as_posix() + "/"
        self.events: list[dict] = []
        self.status = "running"
        self.final = ""
        self.error = ""
        self.preview = ""
        self.files: list[dict] = []
        self.agents: dict[str, dict] = {}
        self.handoffs: list[dict] = []
        self.created_at = time.time()
        self.finished_at: float | None = None
        self.task_handle: asyncio.Task | None = None
        self.on_done: list = []            # async callbacks(run), e.g. the chat tool's report
        self._wake = asyncio.Event()

    def agent(self, agent_id: str) -> dict:
        return next(a for a in self.team["agents"] if a["id"] == agent_id)

    def emit(self, event: dict) -> None:
        self.events.append(event)
        wake, self._wake = self._wake, asyncio.Event()
        wake.set()

    def state(self, agent_id: str) -> dict:
        return self.agents.setdefault(agent_id, {
            "status": "idle", "detail": "", "brief": "", "from": "", "plan": "",
            "output": "", "tools": []})

    def set_status(self, agent_id: str, status: str, detail: str = "") -> None:
        st = self.state(agent_id)
        st["status"], st["detail"] = status, detail
        self.emit({"type": "agent_status", "agent": agent_id, "status": status, "detail": detail})

    def detail(self) -> dict:
        return {"id": self.id, "team_id": self.team["id"], "team": self.team["name"],
                "task": self.task, "status": self.status, "final": self.final,
                "error": self.error, "agents": self.agents, "files": self.files,
                "preview": self.preview, "handoffs": self.handoffs, "web": self.web,
                "created_at": self.created_at, "finished_at": self.finished_at,
                "names": {a["id"]: a["name"] for a in self.team["agents"]}}


# ---- starting, stopping, following -----------------------------------------------------

def active() -> Run | None:
    return _active if _active is not None and _active.status == "running" else None


def start(team: dict, task: str) -> Run | str:
    """Start `team` on `task` in the background; the Run, or why not."""
    global _active
    task = (task or "").strip()
    if not task:
        return "Tell the team what to do first."
    team = store.expand(team)             # linked agents and teams become real ones
    if team.get("lead") not in {a["id"] for a in team.get("agents") or []}:
        return "This team has no agents yet — add one on the canvas first."
    if (busy := active()) is not None:
        return f"{busy.team['name']} is still working — stop it or wait for it to finish."
    run = Run(team, task, _new_workspace(team))
    RUNS[run.id] = run
    finished = [r for r in RUNS.values() if r.status != "running"]
    for old in sorted(finished, key=lambda r: r.created_at)[:-KEEP_FINISHED]:
        RUNS.pop(old.id, None)
    store.add_run(run.id, team["id"], task, str(run.workspace))
    audit.log("team_run_started", team=team["name"], task=task[:200])
    _active = run
    run.task_handle = asyncio.create_task(_execute(run))
    return run


def stop(run_id: str) -> bool:
    run = RUNS.get(run_id)
    if run is None or run.status != "running" or run.task_handle is None:
        return False
    run.task_handle.cancel()
    return True


def get(run_id: str) -> dict | None:
    """A run's details: live ones from memory, older ones from the database."""
    if (run := RUNS.get(run_id)) is not None:
        return run.detail()
    return store.get_run(run_id)


async def follow(run: Run):
    """What the run has done so far (streamed text merged), then each new
    event as it happens, until it ends."""
    sent, first = 0, True
    while True:
        wake = run._wake
        pending = run.events[sent:]
        sent += len(pending)
        for event in (_compact(pending) if first else pending):
            yield event
        first = False
        if run.status != "running" and sent >= len(run.events):
            return
        if sent < len(run.events):
            continue
        try:
            await asyncio.wait_for(wake.wait(), timeout=20)
        except asyncio.TimeoutError:
            yield {"type": "ping"}


def _compact(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in events:
        if (e["type"] == "agent_token" and out and out[-1]["type"] == "agent_token"
                and out[-1]["agent"] == e["agent"]):
            out[-1] = {**out[-1], "content": out[-1]["content"] + e["content"]}
        else:
            out.append(e)
    return out


def _new_workspace(team: dict) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", team["name"].lower()).strip("-")[:40] or "team"
    base = PROJECTS / "teams" / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    path, n = base, 2
    while path.exists():
        path, n = Path(f"{base}-{n}"), n + 1
    path.mkdir(parents=True)
    return path


async def _execute(run: Run) -> None:
    global _active
    lead = run.team["lead"]
    run.emit({"type": "run", "run_id": run.id, "team_id": run.team["id"], "task": run.task,
              "web": run.web, "created_at": run.created_at, "names": _names(run)})
    status = "done"
    try:
        run.final = await _turn(run, lead, run.task, "", 0, (lead,), "")
    except asyncio.CancelledError:
        status = "stopped"
    except Exception as e:  # a run must end cleanly, whatever happened
        status, run.error = "failed", str(e) or e.__class__.__name__
        audit.log("team_run_error", team=run.team["name"], error=run.error[:300])
    for agent_id, st in run.agents.items():
        if st["status"] in ("planning", "waiting", "working"):
            run.set_status(agent_id, status if status == "stopped" else "error",
                           "Stopped" if status == "stopped" else "")
    run.files = _files(run)
    run.preview = _preview(run.files)
    run.finished_at = time.time()
    store.finish_run(run.id, status, run.final, {
        "agents": run.agents, "files": run.files, "preview": run.preview, "error": run.error,
        "handoffs": run.handoffs, "web": run.web, "team": run.team["name"],
        "names": _names(run)})
    audit.log("team_run_finished", team=run.team["name"], status=status,
              seconds=round(run.finished_at - run.created_at))
    if status == "done":
        run.emit({"type": "final", "content": run.final, "files": run.files,
                  "preview": run.preview})
    elif status == "failed":
        run.emit({"type": "error", "message": run.error})
    run.status = status
    if _active is run:
        _active = None
    run.emit({"type": "done", "status": status, "finished_at": run.finished_at})
    for callback in run.on_done:
        try:
            await callback(run)
        except Exception as e:
            audit.log("team_run_callback_error", error=str(e)[:300])


def _names(run: Run) -> dict[str, str]:
    """Every agent's name, including those inside linked teams ("card.agent")."""
    return {a["id"]: a["name"] for a in run.team["agents"]}


# ---- one agent's turn ------------------------------------------------------------------

def _teammates(team: dict, agent_id: str, path: tuple[str, ...]) -> list[dict]:
    """Who `agent_id` can hand work to — never back up its own chain."""
    by_id = {a["id"]: a for a in team["agents"]}
    return [by_id[link["to"]] for link in team["links"]
            if link["from"] == agent_id and link["to"] not in path and link["to"] in by_id]


async def _turn(run: Run, agent_id: str, brief: str, sender: str, depth: int,
                path: tuple[str, ...], earlier: str) -> str:
    """`agent_id` handles `brief` (from `sender`; '' = the user) and returns its result."""
    agent = run.agent(agent_id)
    st = run.state(agent_id)
    st.update({"brief": brief, "from": sender or "You", "output": "", "plan": "", "tools": []})
    kids = _teammates(run.team, agent_id, path) if depth < MAX_DEPTH else []
    try:
        plan: list[tuple[dict, str]] = []
        if kids:
            run.set_status(agent_id, "planning", "Working out who does what")
            plan = await _plan(run, agent, brief, sender, kids)
        if plan:
            reports: list[tuple[dict, str]] = []
            for kid, kid_brief in plan:
                run.handoffs.append({"from": agent_id, "to": kid["id"], "brief": kid_brief})
                run.emit({"type": "handoff", "from": agent_id, "to": kid["id"], "brief": kid_brief})
                run.set_status(agent_id, "waiting", f"Waiting for {kid['name']}")
                out = await _turn(run, kid["id"], kid_brief, agent["name"], depth + 1,
                                  (*path, kid["id"]), _earlier(reports))
                reports.append((kid, out))
                run.emit({"type": "report", "from": kid["id"], "to": agent_id})
            run.set_status(agent_id, "working", "Putting it all together")
            result = await _combine(run, agent, brief, sender, reports)
        else:
            run.set_status(agent_id, "working", "")
            result = await _work(run, agent, brief, sender, earlier)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if depth == 0:
            raise
        # One teammate failing shouldn't sink the run: its lead hears why.
        result = f"({agent['name']} couldn't finish: {e})"
        st["output"] = result
        run.emit({"type": "agent_output", "agent": agent_id, "content": result})
        run.set_status(agent_id, "error", str(e)[:200])
        return result
    st["output"] = result
    run.emit({"type": "agent_output", "agent": agent_id, "content": result})
    run.set_status(agent_id, "done", "")
    return result


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " …(cut short)"


def _skill_note(agent: dict) -> str:
    notes = {"research": "researches the web",
             "files": "saves files to the team's workspace, where web pages go live"}
    found = [notes[s] for s in agent.get("skills") or [] if s in notes]
    return f" ({'; '.join(found)})" if found else ""


def _earlier(reports: list[tuple[dict, str]]) -> str:
    if not reports:
        return ""
    share = max(1200, EARLIER_BUDGET // len(reports))
    return "\n\n".join(f"### {kid['name']}\n{_clip(out, share)}" for kid, out in reports)


def _plan_schema(names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "requirements": {"type": "string"},
            "assignments": {"type": "array", "items": {
                "type": "object",
                "properties": {"agent": {"type": "string", "enum": names},
                               "brief": {"type": "string"}},
                "required": ["agent", "brief"]}},
        },
        "required": ["requirements", "assignments"],
    }


async def _plan(run: Run, agent: dict, brief: str, sender: str,
                kids: list[dict]) -> list[tuple[dict, str]]:
    """Which teammates, in what order, each with a detailed brief. An empty
    plan means the agent should answer itself (it's just a question)."""
    team = "\n".join(f"- {k['name']}: {_clip(k['role'] or 'no instructions yet', 400)}"
                     f"{_skill_note(k)}" for k in kids)
    source = "the user" if not sender else f"{sender}, who leads you"
    system = (
        f"You are {agent['name']}, leading a team of AI agents.\n"
        f"Your role: {agent['role'] or 'Coordinate your team.'}\n\n"
        f"Teammates you can hand work to:\n{team}\n\n"
        f"The task below comes from {source}. Work out what it really needs. Then write a "
        "brief for each teammate whose part is needed — only those, in the order they "
        "should work: anyone whose work others build on goes first. A teammate sees ONLY "
        "its brief and what earlier teammates produced, so each brief must stand on its "
        "own: the goal, every detail that matters for its part (names, audience, features, "
        "style, constraints), exactly what to deliver, and how it fits with the others' "
        "parts. Be specific and detailed.\n"
        "If it's just conversation, or something you can answer yourself, give no "
        "assignments.\n"
        "Reply in JSON: requirements (your short analysis of what's needed) and "
        "assignments (agent, brief).")
    raw = ""
    async for chunk in ollama_client.chat_stream(
            [{"role": "system", "content": system}, {"role": "user", "content": brief}],
            model=agent.get("model") or None, format=_plan_schema([k["name"] for k in kids])):
        raw += (chunk.get("message") or {}).get("content") or ""
        if chunk.get("done"):
            break
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except ValueError:
        # Unreadable plan: everyone gets the task as it was given.
        audit.log("team_plan_unreadable", agent=agent["name"], raw=raw[:200])
        return [(k, brief) for k in kids]
    by_name = {k["name"].lower(): k for k in kids}
    plan: list[tuple[dict, str]] = []
    for item in data.get("assignments") or []:
        if not isinstance(item, dict):
            continue
        kid = by_name.get(str(item.get("agent", "")).strip().lower())
        text = str(item.get("brief", "")).strip()
        if kid is None or not text:
            continue
        at = next((i for i, (k, _) in enumerate(plan) if k["id"] == kid["id"]), None)
        if at is None:
            plan.append((kid, text))
        else:                     # one brief per teammate
            plan[at] = (kid, plan[at][1] + "\n\n" + text)
    st = run.state(agent["id"])
    st["plan"] = str(data.get("requirements") or "").strip()
    run.emit({"type": "agent_plan", "agent": agent["id"], "content": st["plan"],
              "assignments": [k["id"] for k, _ in plan]})
    return plan


async def _stream(run: Run, agent: dict, messages: list[dict],
                  schemas: list[dict] | None) -> tuple[str, list[dict]]:
    text, calls = "", []
    async for chunk in ollama_client.chat_stream(messages, model=agent.get("model") or None,
                                                 tools=schemas):
        msg = chunk.get("message") or {}
        if piece := msg.get("content"):
            text += piece
            run.emit({"type": "agent_token", "agent": agent["id"], "content": piece})
        calls.extend(msg.get("tool_calls") or [])
        if chunk.get("done"):
            break
    return text, calls


def _work_prompt(run: Run, agent: dict, names: set[str]) -> str:
    parts = [f"You are {agent['name']}, an AI agent on a team.",
             f"Your role: {agent['role'] or 'Do the task you are given, thoroughly.'}"]
    if "research" in names:
        parts.append("You can research the web: research searches and reads the best pages "
                     "(answer from what it returns, put [1], [2] after the facts and list the "
                     "sources with their links); web_search and web_fetch look up and read "
                     "single pages.")
    if "save_file" in names:
        parts.append("You share a workspace with your team for this task: save_file writes a "
                     "file there (a path like \"index.html\" or \"backend/main.py\"), read_file "
                     "and list_files read what you and your teammates saved. Everything saved "
                     f"there is published at once — {_origin()}{run.web} serves index.html — "
                     "so saving a web page there deploys it. Pages there run sandboxed, with "
                     "no server behind them and no localStorage or cookies: a page must work "
                     "on its own, with its data in its own JavaScript.")
    if not names:
        parts.append("You have no tools: work from your own knowledge.")
    files = "save_file" in names
    parts.append("Do your part completely and concretely: produce the actual work — real "
                 "content, code, copy or findings — not a description of what you would do. "
                 "Don't ask questions: make sensible assumptions and say what they were."
                 + (" Save every file you make with save_file — complete files, never "
                    "snippets or placeholders." if files else "")
                 + " End with a short summary of what you delivered"
                 + (" and the files you saved." if files else "."))
    return "\n\n".join(parts)


def _trim(messages: list[dict]) -> None:
    """Keep an agent's conversation inside the model's context: the oldest
    tool results shrink first (the brief and the latest results stay)."""
    total = sum(len(str(m.get("content") or "")) for m in messages)
    for m in messages:
        if total <= CONTEXT_BUDGET:
            return
        if m["role"] == "tool" and len(m["content"]) > 400:
            total -= len(m["content"]) - 400
            m["content"] = m["content"][:400] + " …(older result cut short)"


async def _work(run: Run, agent: dict, brief: str, sender: str, earlier: str) -> str:
    kit = {t.name: t for t in _kit(run, agent)}
    schemas = [t.to_ollama() for t in kit.values()] or None
    task = [f"Your brief from {sender}:\n{brief}" if sender else brief]
    if earlier:
        task.append("What your teammates produced before you (build on it):\n\n" + earlier)
    if sender and brief.strip() != run.task.strip():
        task.append(f"The user's original request, for context: {_clip(run.task, 1500)}")
    messages = [{"role": "system", "content": _work_prompt(run, agent, set(kit))},
                {"role": "user", "content": "\n\n".join(task)}]
    written = ""
    for round_no in range(MAX_ROUNDS + 1):
        use = schemas if round_no < MAX_ROUNDS else None   # last round: answer with what it has
        text, calls = await _stream(run, agent, messages, use)
        if not calls and use and (recovered := chat_service.text_tool_call(text, list(kit.values()))):
            # It wrote the tool call out as text: make it a real one.
            calls, text = [recovered], ""
            run.emit({"type": "agent_reset", "agent": agent["id"], "content": written})
        written += text
        if not calls:
            break
        messages.append({"role": "assistant", "content": text, "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            name = str(fn.get("name", ""))
            output = await _use(run, agent, kit, name, args if isinstance(args, dict) else {})
            messages.append({"role": "tool", "tool_name": name, "content": output[:5000]})
        _trim(messages)
    return written.strip() or "(It didn't write anything.)"


async def _combine(run: Run, agent: dict, brief: str, sender: str,
                   reports: list[tuple[dict, str]]) -> str:
    share = max(1500, REPORT_BUDGET // max(1, len(reports)))
    body = "\n\n".join(f"### {kid['name']}\n{_clip(out, share)}" for kid, out in reports)
    files = _files(run)
    if files:
        body += "\n\nFiles in the team's workspace: " + ", ".join(f["path"] for f in files[:40])
        if preview := _preview(files):
            body += f". The site is live at {_origin()}{preview}"
    system = (
        f"You are {agent['name']}, leading a team of AI agents.\n"
        f"Your role: {agent['role'] or 'Coordinate your team.'}\n\n"
        "You handed parts of the task to your teammates and they have reported back. Now "
        f"write the answer for {sender or 'the user'}: bring their work together into one "
        "clear, well-organised result. Keep everything that matters — the actual specifics "
        "(code, file names, links, numbers, copy, findings and their sources); don't just "
        "list who did what. If a part failed or is missing, say so plainly.")
    text, _ = await _stream(run, agent, [
        {"role": "system", "content": system},
        {"role": "user", "content": f"The task: {brief}\n\nReports from your team:\n\n{body}"}],
        None)
    return text.strip() or body


# ---- skills: the tools a teammate gets ---------------------------------------------------

def _kit(run: Run, agent: dict) -> list[tools.Tool]:
    kit: list[tools.Tool] = []
    skills = agent.get("skills") or []
    if "research" in skills:
        kit += [t for name in RESEARCH_TOOLS
                if (t := tools.registry.get(name)) is not None and not t.is_blocked()]
    if "files" in skills:
        kit += _workspace_tools(run, agent)
    return kit


def _doing(name: str, args: dict) -> str:
    what = str(args.get("question") or args.get("query") or args.get("url")
               or args.get("path") or "")[:60]
    label = {"research": "Researching", "web_search": "Searching the web for",
             "web_fetch": "Reading", "save_file": "Saving", "read_file": "Reading",
             "list_files": "Looking at the workspace"}.get(name, name.replace("_", " "))
    return f"{label} {what}".strip()


async def _use(run: Run, agent: dict, kit: dict[str, tools.Tool], name: str, args: dict) -> str:
    entry = {"tool": name, "args": {k: str(v)[:200] for k, v in args.items() if k != "content"}}
    run.state(agent["id"])["tools"].append(entry)
    run.emit({"type": "agent_tool", "agent": agent["id"], "tool": name, "args": entry["args"],
              "status": "running"})
    run.set_status(agent["id"], "working", _doing(name, args))
    t = kit.get(name)
    if t is None:
        output = f"Error: there's no tool called {name}. Yours are: {', '.join(kit) or 'none'}."
    elif name in RESEARCH_TOOLS:
        output = await tools.execute(name, args)       # the shared, audited path
    else:
        try:
            output = await t.run(**args)
        except TypeError as e:
            output = f"Error: wrong arguments for {name}: {e}"
        except Exception as e:
            output = f"Error: {e}"
    entry["result"] = output[:300]
    run.emit({"type": "agent_tool", "agent": agent["id"], "tool": name, "status": "done",
              "result": output[:300]})
    return output


def inside(root: Path, rel: str) -> Path | None:
    """`rel` inside the workspace `root`, or None — nothing outside it, ever."""
    rel = str(rel or "").strip().replace("\\", "/").lstrip("/")
    rel = re.sub(r"^(?:\./)+", "", rel)
    rel = re.sub(r"^workspace/", "", rel)
    if not rel or rel.endswith("/"):
        return None
    base = root.resolve()
    target = (base / rel).resolve()
    return target if target != base and target.is_relative_to(base) else None


def _size(n: int) -> str:
    return f"{n} bytes" if n < 1024 else f"{n / 1024:.1f} KB"


def _workspace_tools(run: Run, agent: dict) -> list[tools.Tool]:
    root = run.workspace

    def files_now() -> list[Path]:
        return sorted(p for p in root.rglob("*") if p.is_file())

    def write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    async def save_file(path: str = "", content: str = "") -> str:
        target = inside(root, path)
        if target is None:
            return "Error: give a path inside the workspace, like 'index.html' or 'backend/main.py'."
        if len(content) > MAX_FILE_CHARS:
            return f"Error: that file is too big (over {MAX_FILE_CHARS:,} characters)."
        if not target.exists() and len(await asyncio.to_thread(files_now)) >= MAX_FILES:
            return f"Error: the workspace is full ({MAX_FILES} files)."
        await asyncio.to_thread(write, target, content)
        rel = target.relative_to(root.resolve()).as_posix()
        url = run.web + urllib.parse.quote(rel)
        size = len(content.encode())
        run.emit({"type": "file", "agent": agent["id"], "path": rel, "url": url, "bytes": size})
        live = f" It's live at {_origin()}{url}" if rel.endswith((".html", ".htm")) else ""
        return f"Saved {rel} ({_size(size)}).{live}"

    async def read_file(path: str = "") -> str:
        target = inside(root, path)
        if target is None or not target.is_file():
            return f"Error: there's no {path or 'file'} in the workspace — list_files shows what's there."
        text = await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace")
        return text[:20000] + ("\n…(rest of the file cut short)" if len(text) > 20000 else "")

    async def list_files() -> str:
        found = await asyncio.to_thread(files_now)
        if not found:
            return "The workspace is empty so far."
        return "\n".join(f"{p.relative_to(root).as_posix()} ({_size(p.stat().st_size)})"
                         for p in found[:MAX_FILES])

    return [
        tools.Tool(
            name="save_file", handler=save_file,
            description="Save a file in the team's workspace (creates folders; overwrites a "
                        "file with the same path). Web pages saved here are live at once.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string", "description": "relative path, e.g. index.html or backend/main.py"},
                "content": {"type": "string", "description": "the complete file"}},
                "required": ["path", "content"]}),
        tools.Tool(
            name="read_file", handler=read_file,
            description="Read a file from the team's workspace (what you or a teammate saved).",
            parameters={"type": "object", "properties": {"path": {"type": "string"}},
                        "required": ["path"]}),
        tools.Tool(
            name="list_files", handler=list_files,
            description="List the files in the team's workspace.",
            parameters={"type": "object", "properties": {}}),
    ]


def _files(run: Run) -> list[dict]:
    root = run.workspace
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and len(out) < 300:
            rel = p.relative_to(root).as_posix()
            out.append({"path": rel, "url": run.web + urllib.parse.quote(rel),
                        "bytes": p.stat().st_size})
    return out


def _preview(files: list[dict]) -> str:
    """The page that shows what the team built: a top-level index.html, else
    the nearest one, else any web page."""
    pages = [f for f in files if f["path"].lower().endswith((".html", ".htm"))]
    index = sorted((f for f in pages if f["path"].lower().rsplit("/", 1)[-1] == "index.html"),
                   key=lambda f: f["path"].count("/"))
    return (index or pages or [{"url": ""}])[0]["url"]

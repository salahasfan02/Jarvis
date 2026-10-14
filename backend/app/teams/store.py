"""Agent teams: several agents the user wires together on a canvas.

A team is a small graph. Each agent has a name, a role (its instructions —
what it does), skills (which tools it may use) and a place on the canvas; a
link A -> B means "A can hand work to B". The user talks to one agent, the
lead, and it gets the right work to the right teammates (engine.py).

Each team is one JSON document, so the canvas can grow new fields without
migrations. Runs keep what every agent was asked and produced.
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
import uuid

from .. import db

SKILLS = ("research", "files")
ICONS = ("crown", "server", "layout", "megaphone", "search", "pen", "bot", "code", "chart",
         "palette", "brain", "shield")
MAX_AGENTS = 24
MAX_ROLE = 4000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_team_runs (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    final TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}',
    workspace TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_team_runs ON agent_team_runs(team_id, created_at);
"""
_ready = False


def _ensure() -> None:
    global _ready
    if not _ready:
        with db.connect() as conn:
            conn.executescript(_SCHEMA)
            # A run doesn't survive a restart: one still "running" was cut off.
            conn.execute("UPDATE agent_team_runs SET status='stopped', finished_at=? "
                         "WHERE status='running'", (time.time(),))
        _ready = True


# ---- templates ------------------------------------------------------------------------

TEMPLATES: dict[str, dict] = {
    "startup": {
        "name": "Startup team",
        "description": "Turn an idea into a product: the main agent briefs backend, "
                       "frontend, marketing and market-research agents.",
        "lead": "main",
        "agents": [
            {"id": "main", "name": "Main agent", "icon": "crown", "color": "#f5b041",
             "x": 60, "y": 250, "skills": [],
             "role": "You are the one the user talks to. Work out exactly what they want and "
                     "everything it needs — the features, who it's for, constraints and style. "
                     "Then write a detailed prompt for each specialist whose part is needed and "
                     "hand it to them (market research first when the market matters, then "
                     "backend before frontend). When they report back, bring their work "
                     "together into one clear answer."},
            {"id": "research", "name": "Market research agent", "icon": "search",
             "color": "#3ecf8e", "x": 440, "y": 20, "skills": ["research", "files"],
             "role": "Market researcher. Research the market on the web: who the customers "
                     "are and what they need, the market's size and trends, the main "
                     "competitors (what they offer, what they charge, where they fall short) "
                     "and the gap this product can fill. Cite every fact with its source link. "
                     "Save the findings as market-research.md."},
            {"id": "backend", "name": "Backend agent", "icon": "server", "color": "#5aa9ff",
             "x": 440, "y": 175, "skills": ["files"],
             "role": "Senior backend engineer. From your brief, design and build the backend: "
                     "the data model, the API (every endpoint with its request and response), "
                     "the business logic and how to run it. Write real, complete code — Python "
                     "and FastAPI unless the brief says otherwise — and save every file (e.g. "
                     "backend/main.py, backend/requirements.txt, and backend/README.md with the "
                     "API reference the frontend will use)."},
            {"id": "frontend", "name": "Frontend agent", "icon": "layout", "color": "#c084fc",
             "x": 440, "y": 330, "skills": ["files"],
             "role": "Senior frontend engineer and designer. From your brief, design, build "
                     "and deploy the frontend: a polished, responsive, accessible web app in "
                     "plain HTML, CSS and JavaScript (no build step), with realistic content — "
                     "never placeholders. Save it with index.html at the top of the workspace: "
                     "that deploys it, live at once. The preview runs sandboxed with no server "
                     "and no storage, so the page must work on its own: keep its data in the "
                     "page's JavaScript (no localStorage or cookies), following the backend's "
                     "API design."},
            {"id": "marketing", "name": "Marketing agent", "icon": "megaphone",
             "color": "#ff6b9a", "x": 440, "y": 485, "skills": ["files"],
             "role": "Marketing strategist and copywriter. Come up with how to market it: "
                     "positioning and a tagline, who it's for, a launch plan with channels, "
                     "three campaign ideas, and ready-to-post copy (a launch post, an email, ad "
                     "headlines). Be specific to this product and its market. Save the plan as "
                     "marketing-plan.md."},
        ],
        "links": [{"from": "main", "to": "research"}, {"from": "main", "to": "backend"},
                  {"from": "main", "to": "frontend"}, {"from": "main", "to": "marketing"}],
    },
    "writing": {
        "name": "Research & writing",
        "description": "An editor who briefs a web researcher, then a writer.",
        "lead": "editor",
        "agents": [
            {"id": "editor", "name": "Editor", "icon": "crown", "color": "#f5b041",
             "x": 60, "y": 170, "skills": [],
             "role": "You talk with the user and own the finished piece. Work out the topic, "
                     "audience, angle and length they want. Brief the researcher on exactly "
                     "what to find, then brief the writer with the angle, the structure and the "
                     "findings to use. Make sure the result answers what the user asked."},
            {"id": "researcher", "name": "Researcher", "icon": "search", "color": "#3ecf8e",
             "x": 440, "y": 70, "skills": ["research", "files"],
             "role": "Research the topic thoroughly on the web: the key facts, numbers, expert "
                     "views and examples, each with its source link. Report the findings as "
                     "clear notes and save them as research-notes.md."},
            {"id": "writer", "name": "Writer", "icon": "pen", "color": "#5aa9ff",
             "x": 440, "y": 280, "skills": ["files"],
             "role": "Skilled writer. Using your brief and the research, write the piece in "
                     "full — engaging, accurate and well structured, with sources as links. "
                     "Save it as a Markdown file named after the piece."},
        ],
        "links": [{"from": "editor", "to": "researcher"}, {"from": "editor", "to": "writer"}],
    },
}
BLANK = {"name": "New team", "description": "", "lead": "lead",
         "agents": [{"id": "lead", "name": "Main agent", "icon": "crown", "color": "#f5b041",
                     "x": 80, "y": 160, "skills": [], "role": ""}],
         "links": []}


def templates() -> list[dict]:
    return [{"id": key, "name": t["name"], "description": t["description"],
             "agents": [a["name"] for a in t["agents"]]} for key, t in TEMPLATES.items()]


# ---- validation -----------------------------------------------------------------------

def _text(value, limit: int, lines: bool = False) -> str:
    s = str(value or "").replace("\r\n", "\n").strip()
    if not lines:
        s = re.sub(r"\s+", " ", s)
    return s[:limit]


def _num(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) else round(max(-100000.0, min(100000.0, v)), 1)


def unique_name(base: str, taken: set[str]) -> str:
    name, n = base, 2
    while name.lower() in taken:
        name, n = f"{base} {n}", n + 1
    return name


def normalize(data: dict) -> dict:
    """Whatever the canvas sends -> a valid team: agents with unique ids and
    names, links only between agents that exist, and a lead."""
    agents, ids, names = [], set(), set()
    for raw in (data.get("agents") or [])[:MAX_AGENTS]:
        if not isinstance(raw, dict):
            continue
        aid = re.sub(r"[^A-Za-z0-9_-]", "", str(raw.get("id") or ""))[:40]
        while not aid or aid in ids:
            aid = uuid.uuid4().hex[:8]
        name = unique_name(_text(raw.get("name"), 40) or "Agent", names)
        color = str(raw.get("color") or "")
        icon = str(raw.get("icon") or "")
        agents.append({
            "id": aid, "name": name,
            "role": _text(raw.get("role"), MAX_ROLE, lines=True),
            "skills": [s for s in SKILLS if s in (raw.get("skills") or [])],
            "model": _text(raw.get("model"), 120),
            "x": _num(raw.get("x")), "y": _num(raw.get("y")),
            "color": color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "",
            "icon": icon if icon in ICONS else "bot",
        })
        ids.add(aid)
        names.add(name.lower())
    links, seen = [], set()
    for raw in data.get("links") or []:
        if not isinstance(raw, dict):
            continue
        a, b = str(raw.get("from", "")), str(raw.get("to", ""))
        if a in ids and b in ids and a != b and (a, b) not in seen:
            links.append({"from": a, "to": b})
            seen.add((a, b))
    lead = str(data.get("lead") or "")
    if lead not in ids:
        incoming = {link["to"] for link in links}
        lead = next((a["id"] for a in agents if a["id"] not in incoming),
                    agents[0]["id"] if agents else "")
    return {"name": _text(data.get("name"), 60) or "New team",
            "description": _text(data.get("description"), 500),
            "lead": lead, "agents": agents, "links": links}


# ---- teams ----------------------------------------------------------------------------

def _team(row) -> dict:
    doc = json.loads(row["data"] or "{}")
    return {**normalize(doc), "id": row["id"], "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


def list_teams() -> list[dict]:
    _ensure()
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM agent_teams ORDER BY updated_at DESC").fetchall()
    return [_team(r) for r in rows]


def get(team_id: str) -> dict | None:
    _ensure()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM agent_teams WHERE id=?", (team_id,)).fetchone()
    return _team(row) if row else None


def create(name: str = "", template: str = "") -> dict:
    _ensure()
    doc = copy.deepcopy(TEMPLATES.get(template) or BLANK)
    if name.strip():
        doc["name"] = name
    doc = normalize(doc)
    taken = {t["name"].lower() for t in list_teams()}
    doc["name"] = unique_name(doc["name"], taken)
    now = time.time()
    team_id = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute("INSERT INTO agent_teams VALUES (?, ?, ?, ?, ?)",
                     (team_id, doc["name"], json.dumps(doc), now, now))
    return get(team_id) or {}


def save(team_id: str, data: dict) -> dict | None:
    _ensure()
    if get(team_id) is None:
        return None
    doc = normalize(data)
    with db.connect() as conn:
        conn.execute("UPDATE agent_teams SET name=?, data=?, updated_at=? WHERE id=?",
                     (doc["name"], json.dumps(doc), time.time(), team_id))
    return get(team_id)


def delete(team_id: str) -> bool:
    _ensure()
    with db.connect() as conn:
        conn.execute("DELETE FROM agent_team_runs WHERE team_id=?", (team_id,))
        return conn.execute("DELETE FROM agent_teams WHERE id=?", (team_id,)).rowcount > 0


def _key(name: str) -> str:
    """'My Research & Writing team' -> 'research and writing'."""
    s = re.sub(r"^(?:my|the|our)\s+", "", name.lower().replace("&", " and ").strip())
    s = re.sub(r"\s+(?:team|agents?|crew)\s*$", "", s)
    return re.sub(r"[^\w]+", " ", s).strip()


def find(name: str = "") -> dict | str:
    """The team the user means ("my startup team"), or why there isn't one."""
    teams = list_teams()
    if not teams:
        return ("There are no agent teams yet — the user can build one in the Agent teams "
                "tab (there's a ready-made Startup team).")
    want = _key(name or "")
    if not want:
        if len(teams) == 1:
            return teams[0]
        return "Which team? There are: " + ", ".join(t["name"] for t in teams) + "."
    for test in (lambda k: k == want, lambda k: want in k or k in want):
        hits = [t for t in teams if _key(t["name"]) and test(_key(t["name"]))]
        if len(hits) == 1:
            return hits[0]
    return (f"There's no team called {name}. The teams are: "
            + ", ".join(t["name"] for t in teams) + ".")


# ---- runs ------------------------------------------------------------------------------

def add_run(run_id: str, team_id: str, task: str, workspace: str) -> None:
    _ensure()
    with db.connect() as conn:
        conn.execute("INSERT INTO agent_team_runs (id, team_id, task, status, workspace, "
                     "created_at) VALUES (?, ?, ?, 'running', ?, ?)",
                     (run_id, team_id, task, workspace, time.time()))


def finish_run(run_id: str, status: str, final: str, data: dict) -> None:
    _ensure()
    with db.connect() as conn:
        conn.execute("UPDATE agent_team_runs SET status=?, final=?, data=?, finished_at=? "
                     "WHERE id=?", (status, final, json.dumps(data), time.time(), run_id))


def _run(row, full: bool) -> dict:
    out = {k: row[k] for k in ("id", "team_id", "task", "status", "created_at", "finished_at")}
    if full:
        out.update(json.loads(row["data"] or "{}"))
        out["final"] = row["final"]
        out["workspace"] = row["workspace"]
    return out


def runs(team_id: str, limit: int = 20) -> list[dict]:
    _ensure()
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM agent_team_runs WHERE team_id=? "
                            "ORDER BY created_at DESC LIMIT ?", (team_id, limit)).fetchall()
    return [_run(r, full=False) for r in rows]


def get_run(run_id: str) -> dict | None:
    _ensure()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM agent_team_runs WHERE id=?", (run_id,)).fetchone()
    return _run(row, full=True) if row else None


def delete_run(run_id: str) -> bool:
    _ensure()
    with db.connect() as conn:
        return conn.execute("DELETE FROM agent_team_runs WHERE id=? AND status!='running'",
                            (run_id,)).rowcount > 0

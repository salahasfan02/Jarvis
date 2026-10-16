"""Agent teams: the user talks to the lead; it briefs the right teammates in
order, each does its part (later ones see earlier work), and the lead brings
it together. Files land in the run's own workspace, live at /projects/…"""
import asyncio
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import channels, db, ui_bridge
from app import main as app_main
from app.llm import ollama_client
from app.teams import engine, store
from app.tools.builtin import team_tools

PAGE = "<!doctype html><title>Streaky</title><h1>Build habits that stick</h1>"


class TeamLLM:
    """Plays every agent: a lead returns its plan (JSON); a teammate writes, or
    calls a tool first; a lead combining reports says so."""

    def __init__(self, plans=None, work=None):
        self.plans = plans or {}
        self.work = work or {}
        self.calls: list[dict] = []
        self.gate: asyncio.Event | None = None     # set to hold every reply until it opens

    async def chat_stream(self, messages, model=None, tools=None, format=None):
        if self.gate is not None:
            await self.gate.wait()
        system = messages[0]["content"]
        agent = re.match(r"You are (.+?), ", system).group(1)
        kind = "plan" if format else "combine" if "reported back" in system else "work"
        self.calls.append({"agent": agent, "kind": kind, "messages": messages, "model": model,
                           "tools": [t["function"]["name"] for t in tools or []]})
        if kind == "plan":
            plan = self.plans.get(agent, {"requirements": "", "assignments": []})
            yield {"message": {"content": plan if isinstance(plan, str) else json.dumps(plan)},
                   "done": True}
            return
        step = self.work.get(agent, lambda msgs: f"{agent} delivered its part.")(messages) \
            if kind == "work" else f"Here's everything, put together by {agent}."
        if isinstance(step, Exception):
            raise step
        if isinstance(step, tuple):
            yield {"message": {"content": "", "tool_calls": [
                {"function": {"name": step[0], "arguments": step[1]}}]}, "done": True}
            return
        for word in step.split(" "):
            yield {"message": {"content": word + " "}, "done": False}
        yield {"message": {"content": ""}, "done": True}

    def of(self, agent: str, kind: str = "work") -> list[dict]:
        return [c for c in self.calls if c["agent"] == agent and c["kind"] == kind]


@pytest.fixture(autouse=True)
def _fresh_engine():
    yield
    engine.RUNS.clear()
    engine._active = None


@pytest.fixture
def llm(monkeypatch):
    fake = TeamLLM()
    monkeypatch.setattr(ollama_client, "chat_stream", fake.chat_stream)
    return fake


STARTUP_PLAN = {"Main agent": {
    "requirements": "A habit-tracking app called Streaky: market check, API, site, launch plan.",
    "assignments": [
        {"agent": "Market research agent", "brief": "Research habit-tracker apps: competitors and prices."},
        {"agent": "Backend agent", "brief": "Build a FastAPI backend for habits and streaks."},
        {"agent": "Frontend agent", "brief": "Build and deploy the Streaky web app."},
        {"agent": "Marketing agent", "brief": "Write Streaky's launch plan."},
    ]}}


def _frontend(messages):
    if not any(m["role"] == "tool" for m in messages):
        return ("save_file", {"path": "index.html", "content": PAGE})
    return "Built and deployed the Streaky page."


def _run(team: dict, task: str) -> engine.Run:
    async def main():
        run = engine.start(team, task)
        assert isinstance(run, engine.Run), run
        await run.task_handle
        return run
    return asyncio.run(main())


def test_templates_and_what_the_canvas_may_send():
    team = store.create(template="startup")
    assert team["lead"] == "main" and len(team["agents"]) == 5 and len(team["links"]) == 4
    assert {a["name"] for a in team["agents"]} >= {"Main agent", "Backend agent", "Frontend agent",
                                                   "Marketing agent", "Market research agent"}
    assert store.create(template="startup")["name"] == "Startup team 2"     # names stay distinct
    messy = store.normalize({
        "name": "  ", "lead": "ghost",
        "agents": [{"id": "a", "name": "Writer", "skills": ["files", "shell"], "color": "red",
                    "icon": "skull", "x": "12.34", "y": float("nan")},
                   {"id": "a", "name": "writer"}, "nonsense"],
        "links": [{"from": "a", "to": "a"}, {"from": "a", "to": "ghost"}]})
    assert messy["name"] == "New team"
    first, second = messy["agents"]
    assert first["skills"] == ["files"] and first["color"] == "" and first["icon"] == "bot"
    assert (first["x"], first["y"]) == (12.3, 0.0)
    assert second["id"] != "a" and second["name"] == "writer 2"
    assert messy["links"] == [] and messy["lead"] == "a"


def test_the_lead_briefs_the_team_in_order_and_brings_it_together(llm):
    llm.plans = STARTUP_PLAN
    llm.work = {"Frontend agent": _frontend,
                "Backend agent": lambda m: "API: GET /habits, POST /habits/{id}/check."}
    team = store.create(template="startup")
    run = _run(team, "Build a habit-tracking app called Streaky")

    assert run.status == "done"
    order = [e["to"] for e in run.events if e["type"] == "handoff"]
    assert order == ["research", "backend", "frontend", "marketing"]
    # each teammate got its own brief, the user's request for context, and its tools
    research = llm.of("Market research agent")[0]
    assert "Research habit-tracker apps" in research["messages"][1]["content"]
    assert "Build a habit-tracking app called Streaky" in research["messages"][1]["content"]
    assert {"research", "save_file"} <= set(research["tools"])
    # later teammates build on earlier work: the frontend sees the backend's API
    frontend = llm.of("Frontend agent")[0]["messages"][1]["content"]
    assert "### Backend agent" in frontend and "GET /habits" in frontend
    # the page it saved is live in the run's workspace
    assert (run.workspace / "index.html").read_text() == PAGE
    assert run.preview == run.web + "index.html" and run.web.startswith("/projects/teams/startup-team")
    assert any(e["type"] == "file" and e["path"] == "index.html" for e in run.events)
    # the lead combined the reports into the answer
    combine = llm.of("Main agent", "combine")[0]["messages"][1]["content"]
    assert "### Frontend agent" in combine and "index.html" in combine
    assert run.final == "Here's everything, put together by Main agent."
    final = next(e for e in run.events if e["type"] == "final")
    assert final["preview"] == run.preview and final["files"][0]["path"] == "index.html"
    assert run.events[-1] == {"type": "done", "status": "done", "finished_at": run.finished_at}
    # saved for the history list
    saved = store.get_run(run.id)
    assert saved["status"] == "done" and saved["final"] == run.final
    assert saved["agents"]["frontend"]["output"].startswith("Built and deployed")
    assert saved["handoffs"][0]["brief"].startswith("Research habit-tracker")
    assert store.runs(team["id"])[0]["id"] == run.id


def test_a_plain_question_is_answered_by_the_lead_itself(llm):
    team = store.create(template="startup")
    run = _run(team, "hi, who are you?")
    assert not [e for e in run.events if e["type"] == "handoff"]
    assert run.final == "Main agent delivered its part."


def test_an_unreadable_plan_gives_everyone_the_task(llm):
    llm.plans = {"Editor": "this is not json"}
    team = store.create(template="writing")
    run = _run(team, "An article about tidal energy")
    briefs = [e["brief"] for e in run.events if e["type"] == "handoff"]
    assert briefs == ["An article about tidal energy"] * 2


def test_one_failing_teammate_doesnt_sink_the_run(llm):
    llm.plans = STARTUP_PLAN
    llm.work = {"Backend agent": lambda m: ollama_client.OllamaError("model not found"),
                "Frontend agent": _frontend}
    run = _run(store.create(template="startup"), "Build Streaky")
    assert run.status == "done"
    assert run.agents["backend"]["status"] == "error"
    assert "couldn't finish: model not found" in run.agents["backend"]["output"]
    assert run.agents["marketing"]["status"] == "done"


def test_the_lead_failing_fails_the_run(llm):
    llm.plans = STARTUP_PLAN
    llm.work = {"Main agent": lambda m: ollama_client.OllamaError("Ollama isn't running")}
    team = store.create(template="startup")
    team["links"] = []
    run = _run(store.save(team["id"], team), "anything")
    assert run.status == "failed" and "Ollama isn't running" in run.error
    assert store.get_run(run.id)["status"] == "failed"


def test_links_back_up_the_chain_are_never_followed(llm):
    team = store.save(store.create()["id"], {
        "name": "Loop", "lead": "a",
        "agents": [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Beta"}],
        "links": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]})
    llm.plans = {"Alpha": {"requirements": "", "assignments": [{"agent": "Beta", "brief": "do it"}]}}
    run = _run(team, "go")
    assert run.status == "done" and [c["kind"] for c in llm.of("Beta", "plan")] == []


def test_the_workspace_is_a_sandbox(llm, tmp_path):
    assert engine.inside(tmp_path, "site/index.html") == (tmp_path / "site/index.html").resolve()
    assert engine.inside(tmp_path, "/etc/passwd") == (tmp_path / "etc/passwd").resolve()
    for bad in ("../outside.txt", "site/../../outside.txt", "", "folder/"):
        assert engine.inside(tmp_path, bad) is None, bad
    llm.plans = {}
    llm.work = {"Main agent": lambda m: ("save_file", {"path": "../../escape.txt", "content": "x"})
                if not any(x["role"] == "tool" for x in m) else "tried"}
    team = store.create()
    team["agents"][0]["skills"] = ["files"]
    run = _run(store.save(team["id"], team), "write a file")
    assert not (run.workspace.parent / "escape.txt").exists()
    assert "inside the workspace" in run.agents["lead"]["tools"][0]["result"]


def test_agents_only_get_the_tools_their_skills_allow(llm):
    team = store.create()
    run = _run(team, "plan my week")
    assert llm.calls[-1]["tools"] == []      # no skills: no tools at all
    assert run.status == "done"


def test_one_run_at_a_time_and_stopping(llm):
    llm.gate = asyncio.Event()
    team = store.create(template="startup")

    async def main():
        run = engine.start(team, "Build Streaky")
        await asyncio.sleep(0.01)
        assert "still working" in engine.start(store.create(template="writing"), "an article")
        assert engine.stop(run.id)
        await run.task_handle
        return run
    run = asyncio.run(main())
    assert run.status == "stopped" and engine.active() is None
    assert run.events[-1]["status"] == "stopped"
    assert store.get_run(run.id)["status"] == "stopped"


def test_following_a_run_replays_what_happened_with_the_text_merged(llm):
    llm.plans = STARTUP_PLAN

    async def main():
        run = engine.start(store.create(template="startup"), "Build Streaky")
        await run.task_handle
        return run, [e async for e in engine.follow(run)]
    run, seen = asyncio.run(main())
    tokens = [e for e in seen if e["type"] == "agent_token" and e["agent"] == "marketing"]
    assert len(tokens) == 1 and tokens[0]["content"].strip() == "Marketing agent delivered its part."
    assert seen[-1]["type"] == "done" and len(seen) < len(run.events)


# --- the API --------------------------------------------------------------------------------------

def test_teams_api_and_a_live_run(llm):
    from fastapi import FastAPI
    from app.api.teams import router
    llm.plans = STARTUP_PLAN
    llm.work = {"Frontend agent": _frontend}
    api = FastAPI()               # the teams routes alone: no start-up work in the test
    api.include_router(router)
    # One event loop for every request (a run carries on between them, as in the app).
    with TestClient(api, base_url="http://127.0.0.1:8765") as client:
        assert {t["id"] for t in client.get("/api/teams/templates").json()} == {"startup", "writing", "it"}
        team = client.post("/api/teams", json={"template": "startup"}).json()
        team["agents"][1]["role"] = "Research the market, citing sources."
        saved = client.put(f"/api/teams/{team['id']}", json=team).json()
        assert saved["agents"][1]["role"] == "Research the market, citing sources."
        assert any(t["id"] == team["id"] for t in client.get("/api/teams").json())
        assert "error" in client.post(f"/api/teams/{team['id']}/runs", json={"task": " "}).json()

        run = client.post(f"/api/teams/{team['id']}/runs", json={"task": "Build Streaky"}).json()
        with client.stream("GET", f"/api/teams/runs/{run['id']}/stream") as stream:
            events = [json.loads(line) for line in stream.iter_lines() if line.strip()]
        assert events[0]["type"] == "run"
        assert events[-1]["type"] == "done" and events[-1]["status"] == "done"
        assert [e["to"] for e in events if e["type"] == "handoff"][0] == "research"

        detail = client.get(f"/api/teams/runs/{run['id']}").json()
        assert detail["status"] == "done" and detail["preview"].endswith("/index.html")
        assert client.get(f"/api/teams/{team['id']}/runs").json()[0]["id"] == run["id"]
        assert client.get("/api/teams/runs/nope").status_code == 404
        assert client.delete(f"/api/teams/runs/{run['id']}").json() == {"ok": True}
        assert client.delete(f"/api/teams/{team['id']}").json() == {"ok": True}
        assert client.get(f"/api/teams/{team['id']}").status_code == 404
    # What the frontend agent deployed is served — sandboxed, like every preview.
    app_client = TestClient(app_main.app, base_url="http://127.0.0.1:8765")
    page = app_client.get(detail["preview"])
    assert page.text == PAGE and "sandbox" in page.headers["content-security-policy"]


# --- asking from chat ------------------------------------------------------------------------------

def test_asking_jarvis_hands_it_to_the_team_and_the_answer_comes_back(llm, monkeypatch):
    for t in store.list_teams():
        store.delete(t["id"])
    llm.plans = STARTUP_PLAN
    llm.work = {"Frontend agent": _frontend}
    announced = []

    async def announce(title, text, speak=True, action=None, conversation_id=None):
        announced.append((title, conversation_id))
    monkeypatch.setattr(ui_bridge, "announce", announce)
    conv = db.create_conversation()["id"]

    async def main():
        assert "no agents or teams yet" in await team_tools.run_agent_team("anything")
        store.create(template="startup")
        channels.conversation.set(conv)
        said = await team_tools.run_agent_team("build a habit app called Streaky")
        run = engine.active()
        await run.task_handle
        return said, run
    said, run = asyncio.run(main())
    assert said.startswith("Handed it to Startup team: Main agent is briefing the team now.")
    last = db.get_messages(conv)[-1]
    assert last["meta"] == {"agent": "team"} and "**Startup team finished**" in last["content"]
    assert run.final in last["content"] and "Live preview: http://127.0.0.1:" in last["content"]
    assert announced == [("Startup team finished", conv)]


def test_which_team_is_meant():
    for t in store.list_teams():
        store.delete(t["id"])
    startup, writing = store.create(template="startup"), store.create(template="writing")
    assert store.find("my startup team")["id"] == startup["id"]
    assert store.find("research and writing")["id"] == writing["id"]
    assert store.find("research")["id"] == writing["id"]
    assert store.find("").startswith("Which one?")
    assert store.find("marketing crew").startswith("There's no agent or team called")


def test_the_it_team_has_a_lead_and_its_specialists():
    from app.teams import store
    t = store.TEMPLATES["it"]
    ids = {a["id"] for a in t["agents"]}
    assert t["lead"] == "itlead" and len(ids) == 11
    assert {l["to"] for l in t["links"]} == ids - {"itlead"}
    assert all(l["from"] == "itlead" for l in t["links"])
    assert all(set(a["skills"]) <= set(store.SKILLS) and a["role"] for a in t["agents"])



# ---- single agents, teams inside teams, and asking for one by name ------------------------

def _clear():
    for t in store.list_teams():
        store.delete(t["id"])


def test_a_single_agent_is_a_team_of_one_that_does_the_work_itself(llm):
    _clear()
    writer = store.create(name="Writer", template="agent")
    assert store.is_single(writer) and writer["agents"][0]["name"] == "Writer"
    assert writer["agents"][0]["skills"] == ["research", "files"]
    run = _run(writer, "Write a haiku about rain")
    assert run.status == "done" and llm.of("Writer") and not llm.of("Writer", "plan")
    assert store.find("my writer agent")["id"] == writer["id"]
    assert store.find(writer["id"])["id"] == writer["id"]


def test_a_team_can_take_in_another_team_and_it_stays_linked(llm):
    _clear()
    writing = store.create(template="writing")
    boss = store.save(store.create()["id"], {
        "name": "Company", "lead": "boss",
        "agents": [{"id": "boss", "name": "Boss", "role": "Run the company."},
                   {"id": "w", "name": "Writers", "ref": writing["id"]}],
        "links": [{"from": "boss", "to": "w"}]})
    assert boss["agents"][1]["ref"] == writing["id"]
    # An edit to the original shows up in the team that took it in.
    store.save(writing["id"], {**writing, "description": "Now with a sharper editor."})
    full = store.expand(store.get(boss["id"]))
    names = {a["id"]: a["name"] for a in full["agents"]}
    assert names == {"boss": "Boss", "w.editor": "Writers", "w.researcher": "Researcher",
                     "w.writer": "Writer"}
    assert {"from": "boss", "to": "w.editor"} in full["links"]
    assert {"from": "w.editor", "to": "w.writer"} in full["links"]
    llm.plans = {"Boss": {"requirements": "a blog post", "assignments": [
                     {"agent": "Writers", "brief": "Write the launch blog post."}]},
                 "Writers": {"requirements": "post", "assignments": [
                     {"agent": "Researcher", "brief": "Find facts."},
                     {"agent": "Writer", "brief": "Write it."}]}}
    run = _run(store.get(boss["id"]), "Write our launch blog post")
    assert run.status == "done"
    assert llm.of("Researcher") and llm.of("Writer")              # the linked team did the work
    assert run.detail()["names"]["w.writer"] == "Writer"


def test_linked_teams_never_loop_and_a_missing_one_is_left_out():
    _clear()
    a, b = store.create(name="A"), store.create(name="B")
    store.save(a["id"], {**a, "agents": a["agents"] + [{"id": "b", "name": "B card", "ref": b["id"]}],
                         "links": [{"from": a["lead"], "to": "b"}]})
    store.save(b["id"], {**b, "agents": b["agents"] + [{"id": "a", "name": "A card", "ref": a["id"]}],
                         "links": [{"from": b["lead"], "to": "a"}]})
    full = store.expand(store.get(a["id"]))
    assert all(x["id"].count(".") <= 1 for x in full["agents"])   # B's card back to A is dropped
    store.delete(b["id"])
    gone = store.expand(store.get(a["id"]))
    assert [x["id"] for x in gone["agents"]] == [a["lead"]] and gone["links"] == []


def test_asking_for_a_team_by_name_goes_straight_to_it():
    from app.chat import quick, service
    _clear()
    it = store.create(template="it")
    action = quick.match("Ask the IT team to set up a new starter, Sam Jones, in Finance on "
                         "Monday and order a laptop")
    assert action.tool == "run_agent_team" and action.arguments["team"] == it["id"]
    assert action.arguments["task"].startswith("set up a new starter, Sam Jones")
    assert quick.match("use my it team to write a password policy").arguments["team"] == it["id"]
    assert quick.match("ask my mum to call me") is None             # not one of their teams
    writer = store.create(name="Writer", template="agent")
    assert quick.match("ask Writer to draft a welcome email").arguments == {
        "task": "draft a welcome email", "team": writer["id"]}
    assert quick.match("ask the writers group to meet") is None
    assert service._asked_for_team("ask the IT team to fix the wifi", it["id"])
    assert not service._asked_for_team("fix the wifi", it["id"])
    token = service._picked.set(it["id"])
    assert service._asked_for_team("fix the wifi", it["id"])        # picked in the app
    service._picked.reset(token)


def test_a_message_sent_to_a_picked_agent_goes_straight_to_it(llm):
    from app.chat import service
    _clear()
    writer = store.create(name="Writer", template="agent")
    conv = db.create_conversation()["id"]

    async def main():
        events = [e async for e in service.run_chat(conv, "Write a haiku about rain",
                                                    target=writer["id"])]
        run = engine.active()
        await run.task_handle
        return events, run
    events, run = asyncio.run(main())
    assert not any(e["type"] == "confirm_request" for e in events)     # picked = no "shall I?"
    assert any(e["type"] == "tool_start" and e["name"] == "run_agent_team" for e in events)
    assert run.team["id"] == writer["id"] and run.task == "Write a haiku about rain"
    done = next(e for e in events if e["type"] == "done")
    assert done["content"].startswith("Writer is on it.")


def test_a_call_typed_into_the_answer_is_made_real_and_never_shown(llm, tmp_path):
    _clear()
    writer = store.create(name="Writer", template="agent")
    llm.work = {"Writer": lambda msgs: (
        'Welcome to the team!\n\n```python\nsave_file("welcome.md", "Welcome to IT (we\'re glad)")\n```'
        if not any(m["role"] == "tool" for m in msgs) else "Saved welcome.md for you.")}
    run = _run(writer, "Write a welcome note and save it")
    assert run.status == "done" and [f["path"] for f in run.files] == ["welcome.md"]
    assert (run.workspace / "welcome.md").read_text() == "Welcome to IT (we're glad)"
    assert "save_file" not in run.final and run.final.startswith("Welcome to the team!")

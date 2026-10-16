import { describe, expect, it } from "vitest";
import {
  isSingle,
  addAgent, applyEvent, canLink, defaultLead, elapsed, emptyRun, fitView, fromSaved, linkMid, linkPath,
  NODE_H, NODE_W, reachable, removeAgent, runHeadline, spotForNew, Team, uniqueName,
} from "./teams";

const agent = (id: string, name: string, x = 0, y = 0) =>
  ({ id, name, role: "", skills: [], model: "", x, y, color: "", icon: "bot" });

const startup = (): Team => ({
  id: "t1", name: "Startup team", description: "", lead: "main",
  agents: [agent("main", "Main agent", 0, 200), agent("backend", "Backend agent", 400, 0),
           agent("frontend", "Frontend agent", 400, 200), agent("lonely", "Lonely agent", 400, 400)],
  links: [{ from: "main", to: "backend" }, { from: "main", to: "frontend" }],
});

describe("the team graph", () => {
  it("connects agents once, never to themselves", () => {
    const t = startup();
    expect(canLink(t, "main", "lonely")).toBe(true);
    expect(canLink(t, "main", "backend")).toBe(false);     // already connected
    expect(canLink(t, "main", "main")).toBe(false);
    expect(canLink(t, "main", "ghost")).toBe(false);
  });

  it("knows who the lead can reach", () => {
    expect([...reachable(startup())].sort()).toEqual(["backend", "frontend", "main"]);
  });

  it("adds agents with names of their own, and removes them with their links", () => {
    const { team, id } = addAgent(startup(), { x: 10.6, y: 20.2 }, { name: "Backend agent" });
    const added = team.agents.find((a) => a.id === id)!;
    expect(added.name).toBe("Backend agent 2");
    expect([added.x, added.y]).toEqual([11, 20]);
    expect(uniqueName(["New agent", "New agent 2"], "New agent")).toBe("New agent 3");
    const gone = removeAgent(startup(), "backend");
    expect(gone.agents.map((a) => a.id)).toEqual(["main", "frontend", "lonely"]);
    expect(gone.links).toEqual([{ from: "main", to: "frontend" }]);
  });

  it("picks a new lead when the lead is removed", () => {
    const t = removeAgent(startup(), "main");
    expect(t.lead).toBe(defaultLead(t));
    expect(t.lead).toBe("backend");
    const first = addAgent({ ...startup(), agents: [], links: [], lead: "" }, { x: 0, y: 0 });
    expect(first.team.lead).toBe(first.id);
  });

  it("finds room for a new agent", () => {
    const t = startup();
    const p = spotForNew(t, "main");
    expect(p.x).toBe(NODE_W + 120);
    expect(t.agents.some((a) => Math.abs(a.x - p.x) < NODE_W * 0.8 && Math.abs(a.y - p.y) < NODE_H * 0.8)).toBe(false);
  });
});

describe("the canvas", () => {
  it("draws links as curves from the right of one agent to the left of the next", () => {
    expect(linkPath({ x: 0, y: 0 }, { x: 200, y: 100 })).toBe("M 0 0 C 100 0, 100 100, 200 100");
    expect(linkMid({ x: 0, y: 0 }, { x: 200, y: 100 })).toEqual({ x: 100, y: 50 });
  });

  it("fits the whole team in view", () => {
    const v = fitView(startup().agents, 1000, 700);
    expect(v.zoom).toBeGreaterThan(0.35);
    expect(v.zoom).toBeLessThanOrEqual(1.1);
    const left = 0 * v.zoom + v.x, right = (400 + NODE_W) * v.zoom + v.x;
    expect(left).toBeGreaterThanOrEqual(0);
    expect(right).toBeLessThanOrEqual(1000);
    expect(Math.round(left)).toBe(Math.round(1000 - right));     // centred
  });
});

describe("following a run", () => {
  const events = [
    { type: "run", run_id: "r1", team_id: "t1", task: "Build Streaky", web: "/projects/teams/x/", created_at: 100 },
    { type: "agent_status", agent: "main", status: "planning", detail: "Working out who does what" },
    { type: "agent_plan", agent: "main", content: "Needs an API and a site", assignments: ["backend", "frontend"] },
    { type: "handoff", from: "main", to: "backend", brief: "Build the API" },
    { type: "agent_status", agent: "main", status: "waiting", detail: "Waiting for Backend agent" },
    { type: "agent_status", agent: "backend", status: "working", detail: "" },
    { type: "agent_token", agent: "backend", content: "GET " },
    { type: "agent_token", agent: "backend", content: "/habits" },
    { type: "agent_tool", agent: "backend", tool: "save_file", args: { path: "api.py" }, status: "running" },
    { type: "file", agent: "backend", path: "api.py", url: "/projects/teams/x/api.py", bytes: 120 },
    { type: "agent_tool", agent: "backend", tool: "save_file", status: "done", result: "Saved api.py" },
    { type: "agent_output", agent: "backend", content: "Saved the API." },
    { type: "agent_status", agent: "backend", status: "done", detail: "" },
    { type: "report", from: "backend", to: "main" },
  ];

  it("builds what each agent was asked and did", () => {
    const s = events.reduce(applyEvent, emptyRun());
    expect(s.id).toBe("r1");
    expect(s.agents.main.plan).toBe("Needs an API and a site");
    expect(s.agents.main.status).toBe("waiting");
    expect(s.agents.backend).toMatchObject({ status: "done", brief: "Build the API", from: "main", output: "Saved the API." });
    expect(s.agents.backend.tools).toEqual([{ tool: "save_file", args: { path: "api.py" }, status: "done", result: "Saved api.py" }]);
    expect(s.files).toEqual([{ path: "api.py", url: "/projects/teams/x/api.py", bytes: 120 }]);
    expect(s.active).toEqual({ from: "main", to: "backend", back: true });   // the report travels back
    expect(s.handoffs).toEqual([{ from: "main", to: "backend", brief: "Build the API" }]);
  });

  it("streams text, and a rewritten reply replaces it", () => {
    const s = events.slice(0, 8).reduce(applyEvent, emptyRun());
    expect(s.agents.backend.output).toBe("GET /habits");
    const reset = applyEvent(s, { type: "agent_reset", agent: "backend", content: "" });
    expect(reset.agents.backend.output).toBe("");
  });

  it("ends with the answer and the live preview", () => {
    let s = events.reduce(applyEvent, emptyRun());
    s = applyEvent(s, { type: "final", content: "Streaky is live.", files: s.files, preview: "/projects/teams/x/index.html" });
    s = applyEvent(s, { type: "done", status: "done", finished_at: 160 });
    expect(s).toMatchObject({ status: "done", final: "Streaky is live.", active: null, finishedAt: 160,
                              preview: "/projects/teams/x/index.html" });
    expect(elapsed(s.finishedAt! - s.createdAt)).toBe("1m 00s");
  });

  it("says who's doing what", () => {
    const team = startup();
    let s = events.slice(0, 2).reduce(applyEvent, emptyRun());
    expect(runHeadline(s, team)).toBe("Main agent is working out who does what…");
    s = applyEvent(applyEvent(s, events[5]),
                   { type: "agent_status", agent: "backend", status: "working", detail: "Saving api.py" });
    expect(runHeadline(s, team)).toBe("Backend agent: Saving api.py…");
    expect(runHeadline({ ...s, status: "failed", error: "Ollama is off" }, team)).toBe("Couldn't finish: Ollama is off");
  });

  it("reads a saved run the same way", () => {
    const s = fromSaved({
      id: "r1", team_id: "t1", task: "Build Streaky", status: "done", final: "Done.",
      agents: { backend: { status: "done", brief: "Build the API", from: "Main agent", output: "ok",
                           tools: [{ tool: "save_file", args: {}, result: "Saved" }] } },
      files: [], preview: "", handoffs: [{ from: "main", to: "backend", brief: "Build the API" }],
      created_at: 1, finished_at: 2 });
    expect(s.agents.backend.tools[0].status).toBe("done");
    expect(s.agents.backend.plan).toBe("");
    expect(s.active).toBeNull();
  });
});

describe("agents and linked teams", () => {
  it("knows a single agent from a team, and names agents inside linked teams", () => {
    const one = { id: "t", name: "Writer", description: "", lead: "a", links: [],
                  agents: [{ id: "a", name: "Writer", role: "", skills: [], model: "", x: 0, y: 0, color: "", icon: "pen" }] };
    expect(isSingle(one as any)).toBe(true);
    expect(isSingle({ ...one, agents: [{ ...one.agents[0], ref: "x".repeat(32) }] } as any)).toBe(false);
    const run = applyEvent(emptyRun(), { type: "run", run_id: "r", team_id: "t", task: "go",
                                          names: { "w.writer": "Writer" } });
    expect(run.names["w.writer"]).toBe("Writer");
  });
});

/** Agent teams: types, the run-event reducer and canvas geometry — all pure
 *  (see teams.test.ts). The API calls are in teamsApi.ts. */

export type Skill = "research" | "files";
export const SKILLS: { id: Skill; label: string; hint: string }[] = [
  { id: "research", label: "Web research", hint: "Searches the web and reads pages; cites its sources" },
  { id: "files", label: "Make files", hint: "Writes code, pages and documents to the team's workspace — a web page saved there goes live" },
];
export const ICONS = ["crown", "server", "layout", "megaphone", "search", "pen", "bot", "code",
                      "chart", "palette", "brain", "shield"] as const;
export const COLORS = ["#f5b041", "#5aa9ff", "#c084fc", "#ff6b9a", "#3ecf8e", "#4fd1c5", "#f87171", "#a3e635"];

export interface TeamAgent {
  id: string;
  name: string;
  role: string;
  skills: Skill[];
  model: string;
  x: number;
  y: number;
  color: string;
  icon: string;
}
export interface TeamLink { from: string; to: string }
export interface Team {
  id: string;
  name: string;
  description: string;
  lead: string;
  agents: TeamAgent[];
  links: TeamLink[];
  created_at?: number;
  updated_at?: number;
}
export interface TeamTemplate { id: string; name: string; description: string; agents: string[] }
export interface RunSummary {
  id: string; team_id: string; task: string; status: RunStatus; created_at: number;
  finished_at: number | null;
}

export type RunStatus = "running" | "done" | "failed" | "stopped";
export type AgentStatus = "idle" | "planning" | "waiting" | "working" | "done" | "error" | "stopped";
export interface AgentToolUse { tool: string; args?: Record<string, string>; status: "running" | "done"; result?: string }
export interface AgentRun {
  status: AgentStatus;
  detail: string;          // "Saving index.html", "Waiting for Backend agent"
  brief: string;           // what it was asked
  from: string;            // who asked ("You" for the lead)
  plan: string;            // a lead's analysis of what's needed
  output: string;          // what it produced (streams in)
  tools: AgentToolUse[];
}
export interface RunFile { path: string; url: string; bytes: number }
export interface RunState {
  id: string;
  teamId: string;
  task: string;
  status: RunStatus;
  agents: Record<string, AgentRun>;
  handoffs: { from: string; to: string; brief: string }[];
  active: { from: string; to: string; back?: boolean } | null;   // the link work is moving along
  files: RunFile[];
  preview: string;
  final: string;
  error: string;
  web: string;
  createdAt: number;
  finishedAt: number | null;
}

// ---- runs: events -> state ------------------------------------------------------------------

export function emptyRun(id = "", task = "", teamId = ""): RunState {
  return { id, teamId, task, status: "running", agents: {}, handoffs: [], active: null, files: [],
           preview: "", final: "", error: "", web: "", createdAt: Date.now() / 1000, finishedAt: null };
}

const blankAgent = (): AgentRun =>
  ({ status: "idle", detail: "", brief: "", from: "", plan: "", output: "", tools: [] });

function withAgent(s: RunState, id: string, patch: (a: AgentRun) => Partial<AgentRun>): RunState {
  const a = s.agents[id] ?? blankAgent();
  return { ...s, agents: { ...s.agents, [id]: { ...a, ...patch(a) } } };
}

/** One event from the backend applied to the run (see teams/engine.py). */
export function applyEvent(s: RunState, e: any): RunState {
  switch (e?.type) {
    case "run":
      return { ...s, id: e.run_id, teamId: e.team_id, task: e.task, web: e.web ?? "",
               createdAt: e.created_at ?? s.createdAt, status: "running" };
    case "agent_status":
      return withAgent(s, e.agent, () => ({ status: e.status, detail: e.detail ?? "" }));
    case "handoff":
      return {
        ...withAgent(s, e.to, () => ({ brief: e.brief, from: e.from, output: "", plan: "", tools: [] })),
        handoffs: [...s.handoffs, { from: e.from, to: e.to, brief: e.brief }],
        active: { from: e.from, to: e.to },
      };
    case "report":
      return { ...s, active: { from: e.to, to: e.from, back: true } };
    case "agent_plan":
      return withAgent(s, e.agent, () => ({ plan: e.content ?? "" }));
    case "agent_token":
      return withAgent(s, e.agent, (a) => ({ output: a.output + (e.content ?? "") }));
    case "agent_reset":
    case "agent_output":
      return withAgent(s, e.agent, () => ({ output: e.content ?? "" }));
    case "agent_tool":
      return withAgent(s, e.agent, (a) => {
        if (e.status === "running") return { tools: [...a.tools, { tool: e.tool, args: e.args, status: "running" }] };
        const i = a.tools.map((t) => t.tool === e.tool && t.status === "running").lastIndexOf(true);
        if (i < 0) return { tools: [...a.tools, { tool: e.tool, status: "done", result: e.result }] };
        const tools = a.tools.slice();
        tools[i] = { ...tools[i], status: "done", result: e.result };
        return { tools };
      });
    case "file": {
      const file = { path: e.path, url: e.url, bytes: e.bytes ?? 0 };
      const files = s.files.some((f) => f.path === e.path)
        ? s.files.map((f) => (f.path === e.path ? file : f)) : [...s.files, file];
      return { ...s, files };
    }
    case "final":
      return { ...s, final: e.content ?? "", files: e.files ?? s.files, preview: e.preview ?? "" };
    case "error":
      return { ...s, error: e.message ?? "Something went wrong." };
    case "done":
      return { ...s, status: e.status ?? "done", active: null, finishedAt: e.finished_at ?? Date.now() / 1000 };
    default:
      return s;
  }
}

/** A finished run as saved by the backend -> the same state a live one builds. */
export function fromSaved(d: any): RunState {
  const agents: Record<string, AgentRun> = {};
  for (const [id, a] of Object.entries<any>(d?.agents ?? {})) {
    agents[id] = { ...blankAgent(), ...a,
                   tools: (a.tools ?? []).map((t: any) => ({ ...t, status: "done" as const })) };
  }
  return {
    id: d.id, teamId: d.team_id, task: d.task ?? "", status: d.status ?? "done", agents,
    handoffs: d.handoffs ?? [], active: null, files: d.files ?? [], preview: d.preview ?? "",
    final: d.final ?? "", error: d.error ?? "", web: d.web ?? "",
    createdAt: d.created_at ?? 0, finishedAt: d.finished_at ?? null,
  };
}

/** The line under the composer: who's doing what right now. */
export function runHeadline(run: RunState, team: Team): string {
  const name = (id: string) => team.agents.find((a) => a.id === id)?.name ?? "An agent";
  if (run.status === "done") return "Done";
  if (run.status === "stopped") return "Stopped";
  if (run.status === "failed") return run.error ? `Couldn't finish: ${run.error}` : "Couldn't finish";
  const busy = Object.entries(run.agents).filter(([, a]) => ["planning", "working"].includes(a.status));
  const [id, a] = busy[busy.length - 1] ?? [];
  if (!id || !a) return "Starting…";
  if (a.status === "planning") return `${name(id)} is working out who does what…`;
  return a.detail ? `${name(id)}: ${a.detail}…` : `${name(id)} is working…`;
}

// ---- the graph -------------------------------------------------------------------------------

export function uniqueName(names: string[], base: string): string {
  const taken = new Set(names.map((n) => n.toLowerCase()));
  let name = base, n = 2;
  while (taken.has(name.toLowerCase())) name = `${base} ${n++}`;
  return name;
}

export function newId(): string {
  return Math.random().toString(16).slice(2, 10).padEnd(8, "0");
}

export function canLink(team: Team, from: string, to: string): boolean {
  const ids = new Set(team.agents.map((a) => a.id));
  return from !== to && ids.has(from) && ids.has(to)
    && !team.links.some((l) => l.from === from && l.to === to);
}

/** The agent the user talks to when the lead is gone: one nothing hands work to. */
export function defaultLead(team: Team): string {
  const incoming = new Set(team.links.map((l) => l.to));
  return (team.agents.find((a) => !incoming.has(a.id)) ?? team.agents[0])?.id ?? "";
}

export function addAgent(team: Team, at: { x: number; y: number }, partial: Partial<TeamAgent> = {}):
  { team: Team; id: string } {
  const id = newId();
  const { name = "New agent", ...rest } = partial;
  const agent: TeamAgent = {
    role: "", skills: [], model: "", icon: "bot", color: COLORS[team.agents.length % COLORS.length],
    ...rest,
    id, name: uniqueName(team.agents.map((a) => a.name), name),
    x: Math.round(at.x), y: Math.round(at.y),
  };
  const next = { ...team, agents: [...team.agents, agent] };
  return { team: next.lead ? next : { ...next, lead: id }, id };
}

export function removeAgent(team: Team, id: string): Team {
  const next = { ...team, agents: team.agents.filter((a) => a.id !== id),
                 links: team.links.filter((l) => l.from !== id && l.to !== id) };
  return next.lead === id ? { ...next, lead: defaultLead(next) } : next;
}

/** Agents the lead can reach along the links (the rest never get work). */
export function reachable(team: Team): Set<string> {
  const seen = new Set<string>(team.lead ? [team.lead] : []);
  const queue = [...seen];
  while (queue.length) {
    const id = queue.shift()!;
    for (const l of team.links) if (l.from === id && !seen.has(l.to)) { seen.add(l.to); queue.push(l.to); }
  }
  return seen;
}

// ---- canvas geometry -------------------------------------------------------------------------

export const NODE_W = 240;
export const NODE_H = 132;
export const PORT_Y = 30;   // ports sit beside the node's title row

export const portOut = (a: { x: number; y: number }) => ({ x: a.x + NODE_W, y: a.y + PORT_Y });
export const portIn = (a: { x: number; y: number }) => ({ x: a.x, y: a.y + PORT_Y });

/** A smooth S-curve from an output port to an input port. */
export function linkPath(p: { x: number; y: number }, q: { x: number; y: number }): string {
  const dx = Math.max(60, Math.abs(q.x - p.x) * 0.5);
  return `M ${p.x} ${p.y} C ${p.x + dx} ${p.y}, ${q.x - dx} ${q.y}, ${q.x} ${q.y}`;
}

/** The middle of that curve (where a link's delete button goes). */
export function linkMid(p: { x: number; y: number }, q: { x: number; y: number }) {
  const dx = Math.max(60, Math.abs(q.x - p.x) * 0.5);
  const xs = [p.x, p.x + dx, q.x - dx, q.x], ys = [p.y, p.y, q.y, q.y];
  const at = (v: number[]) => 0.125 * v[0] + 0.375 * v[1] + 0.375 * v[2] + 0.125 * v[3];
  return { x: at(xs), y: at(ys) };
}

/** Pan and zoom that show every agent in a w×h viewport. */
export function fitView(agents: { x: number; y: number }[], w: number, h: number, pad = 56):
  { x: number; y: number; zoom: number } {
  if (!agents.length || w <= 0 || h <= 0) return { x: pad, y: pad, zoom: 1 };
  const minX = Math.min(...agents.map((a) => a.x)), minY = Math.min(...agents.map((a) => a.y));
  const maxX = Math.max(...agents.map((a) => a.x)) + NODE_W;
  const maxY = Math.max(...agents.map((a) => a.y)) + NODE_H;
  const zoom = Math.max(0.35, Math.min(1.1, (w - 2 * pad) / (maxX - minX), (h - 2 * pad) / (maxY - minY)));
  return { x: (w - (maxX - minX) * zoom) / 2 - minX * zoom, y: (h - (maxY - minY) * zoom) / 2 - minY * zoom, zoom };
}

/** Where to put a new agent: right of the selected one, else below everyone. */
export function spotForNew(team: Team, near?: string): { x: number; y: number } {
  const base = team.agents.find((a) => a.id === near);
  const taken = (x: number, y: number) =>
    team.agents.some((a) => Math.abs(a.x - x) < NODE_W * 0.8 && Math.abs(a.y - y) < NODE_H * 0.8);
  let x = base ? base.x + NODE_W + 120 : (team.agents[0]?.x ?? 80);
  let y = base ? base.y : Math.max(40, ...team.agents.map((a) => a.y + NODE_H + 40));
  while (taken(x, y)) y += NODE_H + 30;
  return { x, y };
}

export function sizeLabel(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function elapsed(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

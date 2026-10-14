/** Agent teams API: teams, runs, and following a run live (see
 *  backend/app/api/teams.py). */
import { API } from "./api";
import type { RunSummary, Team, TeamTemplate } from "./teams";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}/teams${path}`, {
    headers: { "Content-Type": "application/json" }, ...init,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || (body && typeof body === "object" && "error" in body && body.error)) {
    throw new Error(body?.error || `${res.status}`);
  }
  return body as T;
}

export const teamsApi = {
  list: () => call<Team[]>(""),
  templates: () => call<TeamTemplate[]>("/templates"),
  create: (template = "", name = "") =>
    call<Team>("", { method: "POST", body: JSON.stringify({ template, name }) }),
  save: (team: Team) => call<Team>(`/${team.id}`, { method: "PUT", body: JSON.stringify(team) }),
  remove: (id: string) => call<{ ok: boolean }>(`/${id}`, { method: "DELETE" }),
  runs: (id: string) => call<RunSummary[]>(`/${id}/runs`),
  start: (id: string, task: string) =>
    call<any>(`/${id}/runs`, { method: "POST", body: JSON.stringify({ task }) }),
  run: (runId: string) => call<any>(`/runs/${runId}`),
  active: () => call<any>("/runs/active"),
  stop: (runId: string) => call<{ ok: boolean }>(`/runs/${runId}/stop`, { method: "POST" }),
  deleteRun: (runId: string) => call<{ ok: boolean }>(`/runs/${runId}`, { method: "DELETE" }),
};

/** Follow a live run: what happened so far, then each event as it happens. */
export async function followRun(runId: string, onEvent: (e: any) => void,
                                signal: AbortSignal): Promise<void> {
  const res = await fetch(`${API}/teams/runs/${runId}/stream`, { signal });
  if (!res.ok || !res.body) throw new Error(`The run isn't live (${res.status}).`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
  }
}

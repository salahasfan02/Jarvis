import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft, ArrowUp, Bot, Check, ChevronDown, Crown, ExternalLink, FileCode, History, Plus, Save, Square, Trash2,
  Workflow, X,
} from "lucide-react";
import { api, ORIGIN } from "../lib/api";
import { EmptyState, PageHeader, toast } from "../components/ui";
import { Answer } from "../components/ChatView";
import { AGENT_ICONS, Selection, TeamCanvas } from "../components/TeamCanvas";
import { timeAgo } from "../lib/format";
import {
  addAgent, AgentRun, applyEvent, canLink, COLORS, elapsed, emptyRun, fromSaved, ICONS, removeAgent,
  RunState, RunSummary, runHeadline, sizeLabel, SKILLS, Skill, spotForNew, Team, TeamAgent, TeamTemplate,
  uniqueName,
} from "../lib/teams";
import { followRun, teamsApi } from "../lib/teamsApi";

const STATUS_LABEL: Record<string, string> = {
  idle: "Waiting", planning: "Briefing the team", waiting: "Waiting for teammates", working: "Working",
  done: "Done", error: "Couldn't finish", stopped: "Stopped",
};
const RUN_LABEL: Record<string, string> = {
  running: "Working", done: "Done", failed: "Couldn't finish", stopped: "Stopped",
};

/** Agent teams: a canvas of agents the user builds and wires together. The
 *  user talks to one (the lead, with the crown); it briefs the agents it's
 *  connected to, they do their parts, and it brings the work together. */
export function TeamsPage() {
  const [teams, setTeams] = useState<Team[] | null>(null);
  const [templates, setTemplates] = useState<TeamTemplate[]>([]);
  const [teamId, setTeamId] = useState<string>(() => localStorage.getItem("jarvis.team") ?? "");
  const [browsing, setBrowsing] = useState(false);       // the list of teams instead of one team
  const [team, setTeam] = useState<Team | null>(null);
  const [selected, setSelected] = useState<Selection>(null);
  const [tab, setTab] = useState<"inspect" | "results">("inspect");
  const [run, setRun] = useState<RunState | null>(null);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [task, setTask] = useState("");
  const [models, setModels] = useState<{ names: string[]; active: string }>({ names: [], active: "" });
  const [menu, setMenu] = useState<"" | "new" | "history">("");
  const [armDelete, setArmDelete] = useState(false);
  const [, tick] = useState(0);

  // ---- loading ----
  useEffect(() => {
    teamsApi.list().then(setTeams).catch(() => setTeams([]));
    teamsApi.templates().then(setTemplates).catch(() => {});
    api.models().then((m) => setModels({ names: m.models.map((x) => x.name), active: m.active }))
      .catch(() => {});
  }, []);

  // ---- following a run (events arrive many per second: applied once per frame) ----
  const following = useRef<AbortController | null>(null);
  const queue = useRef<any[]>([]);
  const frame = useRef(0);
  const teamIdRef = useRef(teamId);
  teamIdRef.current = teamId;
  const runTeam = useRef(new Map<string, string>());   // run id -> its team, for the history list
  const flush = () => {
    frame.current = 0;
    const events = queue.current;
    queue.current = [];
    if (events.length) setRun((r) => events.reduce(applyEvent, r ?? emptyRun()));
  };
  const follow = useCallback((runId: string, retries = 3) => {
    following.current?.abort();
    const ctl = new AbortController();
    following.current = ctl;
    queue.current = [];
    setRun(emptyRun(runId));
    let last = "running";
    followRun(runId, (e) => {
      if (e.type === "ping") return;
      if (e.type === "done") last = e.status;
      queue.current.push(e);
      if (!frame.current) frame.current = requestAnimationFrame(flush);
    }, ctl.signal).catch(() => {}).finally(async () => {
      if (ctl.signal.aborted) return;
      flush();
      if (last === "running") {
        // Lost the connection mid-run: pick it up again, or show how it ended.
        const d = await teamsApi.run(runId).catch(() => null);
        if (d?.status === "running" && retries > 0) { setTimeout(() => follow(runId, retries - 1), 1000); return; }
        if (d) setRun(fromSaved(d));
      }
      const owner = runTeam.current.get(runId);
      if (owner && owner === teamIdRef.current) teamsApi.runs(owner).then(setHistory).catch(() => {});
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => () => { following.current?.abort(); cancelAnimationFrame(frame.current); }, []);

  // ---- the team on the canvas ----
  useEffect(() => {
    if (teams === null) return;
    const t = teams.find((x) => x.id === teamId) ?? teams[0] ?? null;
    if (t && t.id !== teamId) { setTeamId(t.id); return; }
    localStorage.setItem("jarvis.team", t?.id ?? "");
    following.current?.abort();
    setTeam(t);
    setSelected(null);
    setRun(null);
    setTab("inspect");
    setHistory([]);
    if (!t) return;
    teamsApi.runs(t.id).then(setHistory).catch(() => {});
    teamsApi.active().then((r) => {
      if (r?.id && r.team_id === t.id) {
        runTeam.current.set(r.id, t.id);
        follow(r.id);
        setTab("results");
      }
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId, teams === null]);

  // Edits show at once and are saved a moment later (the canvas never waits).
  // What's on screen stays as typed: the server tidies its own copy (trimmed,
  // names made unique), and pulling that back mid-sentence would eat spaces.
  // The header shows where that's at, and Save (or ⌘S) saves right now.
  const saveTimer = useRef<any>(null);
  const pending = useRef<Team | null>(null);
  const [saveState, setSaveState] = useState<"saved" | "unsaved" | "saving" | "failed">("saved");
  const save = useCallback(async (next: Team) => {
    pending.current = null;
    setSaveState("saving");
    try {
      await teamsApi.save(next);
      setSaveState(pending.current ? "unsaved" : "saved");
      return true;
    } catch {
      pending.current = pending.current ?? next;
      setSaveState("failed");
      toast("Couldn't save the team — press Save to try again", "error");
      return false;
    }
  }, []);
  const update = (next: Team, now = false) => {
    setTeam(next);
    setTeams((list) => list?.map((t) => (t.id === next.id ? next : t)) ?? list);
    clearTimeout(saveTimer.current);
    pending.current = next;
    setSaveState("unsaved");
    saveTimer.current = setTimeout(() => save(next), now ? 0 : 500);
  };
  const flushSave = async () => {
    if (!pending.current) return;
    clearTimeout(saveTimer.current);
    await save(pending.current);
  };
  const saveNow = async () => {
    clearTimeout(saveTimer.current);
    if (team && await save(pending.current ?? team)) toast(`Saved ${team.name}`);
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveNow(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => () => { if (pending.current) teamsApi.save(pending.current).catch(() => {}); }, []);

  useEffect(() => {
    if (run?.status !== "running") return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [run?.status]);

  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest(".tp-menu, .tp-menu-btn")) setMenu("");
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);

  // A different agent, connection or tab starts at the top of the side panel.
  const side = useRef<HTMLDivElement>(null);
  const shown = `${tab}:${selected?.kind ?? ""}:${selected?.kind === "agent" ? selected.id
    : selected?.kind === "link" ? `${selected.from}>${selected.to}` : ""}`;
  useEffect(() => { side.current?.scrollTo(0, 0); }, [shown]);

  // ---- teams ----
  const createTeam = async (template: string) => {
    setMenu("");
    try {
      const t = await teamsApi.create(template);
      setTeams((list) => [t, ...(list ?? [])]);
      setTeamId(t.id);
      setBrowsing(false);
      toast(`Created ${t.name}`);
    } catch {
      toast("Couldn't create the team", "error");
    }
  };
  const deleteTeam = async () => {
    if (!team) return;
    if (!armDelete) {
      setArmDelete(true);
      setTimeout(() => setArmDelete(false), 3000);
      return;
    }
    setArmDelete(false);
    await teamsApi.remove(team.id).catch(() => {});
    const rest = (teams ?? []).filter((t) => t.id !== team.id);
    setTeams(rest);
    setTeamId(rest[0]?.id ?? "");
    toast("Team deleted");
  };

  // ---- agents and links ----
  const running = run?.status === "running";
  const patchAgent = (id: string, patch: Partial<TeamAgent>) =>
    team && update({ ...team, agents: team.agents.map((a) => (a.id === id ? { ...a, ...patch } : a)) });
  const addAgentAt = (x: number, y: number) => {
    if (!team) return;
    if (team.agents.length >= 24) { toast("A team can have up to 24 agents", "error"); return; }
    const made = addAgent(team, { x, y });
    update(made.team, true);
    setSelected({ kind: "agent", id: made.id });
    setTab("inspect");
  };
  const link = (from: string, to: string) => {
    if (team && canLink(team, from, to)) update({ ...team, links: [...team.links, { from, to }] }, true);
  };
  const unlink = (from: string, to: string) =>
    team && update({ ...team, links: team.links.filter((l) => !(l.from === from && l.to === to)) }, true);
  const remove = (sel: Selection) => {
    if (!team || !sel) return;
    if (sel.kind === "link") { unlink(sel.from, sel.to); setSelected(null); return; }
    if (team.agents.length <= 1) { toast("A team needs at least one agent", "error"); return; }
    update(removeAgent(team, sel.id), true);
    setSelected(null);
  };
  const move = (id: string, x: number, y: number, done: boolean) => {
    if (!team) return;
    const next = { ...team, agents: team.agents.map((a) => (a.id === id ? { ...a, x, y } : a)) };
    if (done) update(next); else setTeam(next);
  };

  // ---- runs ----
  const start = async () => {
    const text = task.trim();
    if (!team || !text || running) return;
    await flushSave();
    try {
      const d = await teamsApi.start(team.id, text);
      runTeam.current.set(d.id, team.id);
      setTask("");
      setSelected(null);
      setTab("results");
      follow(d.id);
    } catch (e: any) {
      toast(e.message || "Couldn't start the team", "error");
    }
  };
  const stopRun = () => run && teamsApi.stop(run.id).catch(() => {});
  const openRun = async (r: RunSummary) => {
    setMenu("");
    try {
      const d = await teamsApi.run(r.id);
      runTeam.current.set(r.id, r.team_id);
      if (d.status === "running") follow(r.id);
      else { following.current?.abort(); setRun(fromSaved(d)); }
      setSelected(null);
      setTab("results");
    } catch {
      toast("Couldn't open that run", "error");
    }
  };
  const forgetRun = async (r: RunSummary) => {
    const res = await teamsApi.deleteRun(r.id).catch(() => ({ ok: false }));
    if (res.ok) {
      setHistory((h) => h.filter((x) => x.id !== r.id));
      if (run?.id === r.id) setRun(null);
    }
  };

  const nameOf = useMemo(() => {
    const names = new Map((team?.agents ?? []).map((a) => [a.id, a.name]));
    return (id: string) => names.get(id) ?? id;
  }, [team?.agents]);

  // ---- all teams (and a new one from a template) ----
  if (teams !== null && (teams.length === 0 || browsing)) {
    return (
      <div className="page">
        <div className="page-inner wide">
          <PageHeader title="Agent teams">
            Build a team of AI agents on a canvas: say what each one does and connect them. You talk
            to one agent — it works out what's needed, briefs the others and brings their work together.
          </PageHeader>
          {teams.length > 0 && (
            <>
              <h3 className="tp-list-title">Your teams</h3>
              <div className="tp-templates">
                {teams.map((t) => (
                  <button key={t.id} className={`tp-template ${t.id === teamId ? "current" : ""}`}
                          onClick={() => { setTeamId(t.id); setBrowsing(false); }}>
                    <span className="tile-icon"><Workflow /></span>
                    <h4>{t.name}</h4>
                    <p>{t.description || `${t.agents.length} agent${t.agents.length === 1 ? "" : "s"}`}</p>
                    <span className="tp-template-agents">
                      {t.agents.slice(0, 5).map((a) => <span key={a.id} className="chip">{a.name}</span>)}
                      {t.agents.length > 5 && <span className="chip">+{t.agents.length - 5}</span>}
                    </span>
                    {t.updated_at ? <span className="muted tp-updated">Edited {timeAgo(t.updated_at)}</span> : null}
                  </button>
                ))}
              </div>
              <h3 className="tp-list-title">Start a new team</h3>
            </>
          )}
          <div className="tp-templates">
            {templates.map((t) => (
              <button key={t.id} className="tp-template" onClick={() => createTeam(t.id)}>
                <span className="tile-icon"><Workflow /></span>
                <h4>{t.name}</h4>
                <p>{t.description}</p>
                <span className="tp-template-agents">
                  {t.agents.map((n) => <span key={n} className="chip">{n}</span>)}
                </span>
              </button>
            ))}
            <button className="tp-template blank" onClick={() => createTeam("")}>
              <span className="tile-icon"><Plus /></span>
              <h4>Start from scratch</h4>
              <p>One agent to begin with — add more and connect them on the canvas.</p>
            </button>
          </div>
        </div>
      </div>
    );
  }
  if (!team) return <div className="page"><div className="page-inner"><div className="sub">Loading…</div></div></div>;

  const lead = team.agents.find((a) => a.id === team.lead) ?? team.agents[0];
  const LeadIcon = AGENT_ICONS[lead?.icon ?? "bot"] ?? Bot;
  const agent = selected?.kind === "agent" ? team.agents.find((a) => a.id === selected.id) : undefined;
  const runSeconds = run ? (run.finishedAt ?? Date.now() / 1000) - run.createdAt : 0;

  return (
    <div className="teams-page">
      <div className="tp-head">
        <button className="btn sm ghost" title="All teams" aria-label="Back to all teams"
                onClick={async () => { await flushSave(); setSelected(null); setBrowsing(true); }}>
          <ArrowLeft /> All teams</button>
        <span className="tile-icon"><Workflow /></span>
        <div className="tp-team">
          <select className="tp-team-select" value={team.id} aria-label="Team"
                  onChange={(e) => setTeamId(e.target.value)}>
            {(teams ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <span className="sub">{team.agents.length} agent{team.agents.length === 1 ? "" : "s"} ·
            you talk to {lead?.name}</span>
        </div>
        <div className="grow" />
        <span className={`tp-save ${saveState}`} role="status" aria-live="polite">
          {saveState === "saved" ? <><Check /> Saved</>
            : saveState === "saving" ? <><span className="spinner" /> Saving…</>
            : saveState === "failed" ? <>Not saved</> : <>Unsaved changes</>}
        </span>
        <button className="btn sm" title="Save (⌘S)" onClick={saveNow}
                disabled={saveState === "saving"}><Save /> Save</button>
        <button className="btn sm" onClick={() => {
          const sel = selected?.kind === "agent" ? selected.id : undefined;
          const p = spotForNew(team, sel);
          addAgentAt(p.x, p.y);
        }}><Plus /> Add agent</button>
        <div className="tp-menu-wrap">
          <button className="btn sm tp-menu-btn" onClick={() => setMenu(menu === "history" ? "" : "history")}
                  aria-expanded={menu === "history"}><History /> Runs <ChevronDown /></button>
          {menu === "history" && (
            <div className="tp-menu" role="menu">
              {history.length === 0 && <div className="tp-menu-empty">No runs yet</div>}
              {history.map((r) => (
                <div key={r.id} className="tp-menu-item" role="menuitem" tabIndex={0}
                     onClick={() => openRun(r)} onKeyDown={(e) => e.key === "Enter" && openRun(r)}>
                  <span className={`tp-dot ${r.status}`} />
                  <span className="grow">{r.task}</span>
                  <span className="muted">{timeAgo(r.created_at)}</span>
                  {r.status !== "running" && (
                    <button className="ghost-icon" aria-label="Forget this run" title="Forget this run"
                            onClick={(e) => { e.stopPropagation(); forgetRun(r); }}><X /></button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="tp-menu-wrap">
          <button className="btn sm tp-menu-btn" onClick={() => setMenu(menu === "new" ? "" : "new")}
                  aria-expanded={menu === "new"}><Plus /> New team <ChevronDown /></button>
          {menu === "new" && (
            <div className="tp-menu" role="menu">
              {templates.map((t) => (
                <div key={t.id} className="tp-menu-item tall" role="menuitem" tabIndex={0}
                     onClick={() => createTeam(t.id)} onKeyDown={(e) => e.key === "Enter" && createTeam(t.id)}>
                  <span className="grow"><b>{t.name}</b><span className="sub">{t.description}</span></span>
                </div>
              ))}
              <div className="tp-menu-item tall" role="menuitem" tabIndex={0}
                   onClick={() => createTeam("")} onKeyDown={(e) => e.key === "Enter" && createTeam("")}>
                <span className="grow"><b>Blank team</b><span className="sub">One agent — build the rest yourself.</span></span>
              </div>
            </div>
          )}
        </div>
        <button className="icon-btn" title={armDelete ? "Click again to delete this team" : "Delete team"}
                aria-label={armDelete ? "Confirm delete team" : "Delete team"}
                style={armDelete ? { color: "var(--danger)" } : undefined} onClick={deleteTeam}><Trash2 /></button>
      </div>

      <div className="tp-body">
        <TeamCanvas team={team} run={run} selected={selected}
                    onSelect={(sel) => { setSelected(sel); if (sel) setTab("inspect"); }}
                    onMoveAgent={move} onLink={link} onAddAgent={addAgentAt} onDelete={remove} />

        <aside className="tp-side" aria-label="Details">
          <div className="seg tp-tabs" role="tablist">
            <button role="tab" aria-selected={tab === "inspect"} className={tab === "inspect" ? "active" : ""}
                    onClick={() => setTab("inspect")}>{agent ? "Agent" : selected?.kind === "link" ? "Connection" : "Team"}</button>
            <button role="tab" aria-selected={tab === "results"} className={tab === "results" ? "active" : ""}
                    onClick={() => setTab("results")}>
              Results {running && <span className="spinner" />}
            </button>
          </div>
          <div className="tp-side-body" ref={side}>
            {tab === "inspect" && agent && (
              <AgentInspector team={team} agent={agent} models={models} state={run?.agents[agent.id]}
                              nameOf={nameOf} onPatch={(p) => patchAgent(agent.id, p)}
                              onLead={() => update({ ...team, lead: agent.id })}
                              onLink={(to) => link(agent.id, to)} onUnlink={(to) => unlink(agent.id, to)}
                              onDelete={() => remove({ kind: "agent", id: agent.id })} />
            )}
            {tab === "inspect" && selected?.kind === "link" && (
              <div className="tp-inspector">
                <h3 className="tp-link-title">{nameOf(selected.from)} <span className="muted">→</span> {nameOf(selected.to)}</h3>
                <p className="sub">
                  {nameOf(selected.from)} can hand work to {nameOf(selected.to)}: it writes a detailed brief
                  for it, and {nameOf(selected.to)} reports back when it's done.
                </p>
                {run?.handoffs.filter((h) => h.from === selected.from && h.to === selected.to).slice(-1).map((h, i) => (
                  <div key={i} className="tp-brief"><span>Brief in the last run</span><p>{h.brief}</p></div>
                ))}
                <button className="btn danger sm" onClick={() => remove(selected)}><X /> Remove connection</button>
              </div>
            )}
            {tab === "inspect" && !selected && (
              <div className="tp-inspector">
                <label className="form-field">Team name
                  <input type="text" value={team.name} maxLength={60}
                         onChange={(e) => update({ ...team, name: e.target.value })}
                         onBlur={() => !team.name.trim() && update({ ...team, name: "New team" })} />
                </label>
                <label className="form-field">What it's for
                  <textarea rows={2} value={team.description} maxLength={500} placeholder="Optional"
                            onChange={(e) => update({ ...team, description: e.target.value })} />
                </label>
                <div className="tp-how">
                  <h4>How it works</h4>
                  <ol>
                    <li>You talk to <b>{lead?.name}</b> — the agent with the crown.</li>
                    <li>It works out what's needed and writes a detailed brief for each agent it's connected to.</li>
                    <li>They work one after another — each sees what the earlier ones made — and report back.</li>
                    <li>{lead?.name} brings it all together for you. Web pages they save go live straight away.</li>
                  </ol>
                </div>
                <div className="form-field">Agents
                  <div className="tp-agent-list">
                    {team.agents.map((a) => {
                      const Icon = AGENT_ICONS[a.icon] ?? Bot;
                      return (
                        <button key={a.id} className="tp-agent-row" onClick={() => setSelected({ kind: "agent", id: a.id })}>
                          <span className="tp-agent-icon" style={{ background: a.color || "var(--accent)" }}><Icon /></span>
                          <span className="grow">{a.name}</span>
                          {a.id === team.lead && <Crown className="icon-sm" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="sub">Double-click the canvas to add an agent. Drag from an agent's right-hand
                  dot to another agent to connect them; select a connection and press Delete to remove it.</div>
              </div>
            )}
            {tab === "results" && (
              <RunResults run={run} team={team} nameOf={nameOf} seconds={runSeconds} />
            )}
          </div>
        </aside>
      </div>

      <div className="tp-composer">
        <div className="tp-composer-box">
          <span className="tp-lead-badge" style={{ background: lead?.color || "var(--accent)" }}
                title={`${lead?.name} gets your request`}><LeadIcon /></span>
          <textarea rows={1} value={task} aria-label={`Message ${lead?.name}`}
                    placeholder={`Tell ${lead?.name ?? "the team"} what you need…`}
                    onChange={(e) => {
                      setTask(e.target.value);
                      e.target.style.height = "auto";
                      e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); start(); }
                    }} />
          {running ? (
            <button className="btn danger" onClick={stopRun}><Square /> Stop</button>
          ) : (
            <button className="btn primary" disabled={!task.trim()} onClick={start}>
              <ArrowUp /> Send
            </button>
          )}
        </div>
        <div className="tp-status-line">
          {run ? (
            <>
              {running && <span className="spinner" />}
              <span className={`tp-dot ${run.status}`} />
              <span className="grow">{runHeadline(run, team)}</span>
              <span className="muted">{elapsed(runSeconds)}</span>
              {run.preview && (
                <a href={`${ORIGIN}${run.preview}`} target="_blank" rel="noreferrer" className="inline-icon">
                  <ExternalLink className="icon-sm" /> Live preview
                </a>
              )}
            </>
          ) : (
            <span className="muted">Your request goes to {lead?.name}, who briefs the rest of the team —
              e.g. “build a landing page and a launch plan for my dog-walking app”. Agents can research
              the web and save files; nothing else on your Mac is touched.</span>
          )}
        </div>
      </div>
    </div>
  );
}

function AgentInspector(props: {
  team: Team;
  agent: TeamAgent;
  models: { names: string[]; active: string };
  state?: AgentRun;
  nameOf: (id: string) => string;
  onPatch: (p: Partial<TeamAgent>) => void;
  onLead: () => void;
  onLink: (to: string) => void;
  onUnlink: (to: string) => void;
  onDelete: () => void;
}) {
  const { team, agent, state } = props;
  const Icon = AGENT_ICONS[agent.icon] ?? Bot;
  const lead = team.lead === agent.id;
  const outgoing = team.links.filter((l) => l.from === agent.id);
  const incoming = team.links.filter((l) => l.to === agent.id);
  const candidates = team.agents.filter((a) => canLink(team, agent.id, a.id));
  const toggleSkill = (s: Skill, on: boolean) =>
    props.onPatch({ skills: on ? [...agent.skills, s] : agent.skills.filter((x) => x !== s) });
  return (
    <div className="tp-inspector">
      <div className="tp-agent-title">
        <span className="tp-agent-icon lg" style={{ background: agent.color || "var(--accent)" }}><Icon /></span>
        <input type="text" className="tp-name" value={agent.name} maxLength={40} aria-label="Agent name"
               onChange={(e) => props.onPatch({ name: e.target.value })}
               onBlur={() => {
                 // Names are how the lead tells its teammates apart: keep them filled in and distinct.
                 const others = team.agents.filter((a) => a.id !== agent.id).map((a) => a.name);
                 const name = uniqueName(others, agent.name.trim() || "New agent");
                 if (name !== agent.name) props.onPatch({ name });
               }} />
      </div>
      <label className="tp-toggle">
        <span className="switch">
          <input type="checkbox" checked={lead} disabled={lead} onChange={props.onLead} />
          <span />
        </span>
        <span><b>You talk to this agent</b><span className="sub">{lead
          ? "It gets your requests and briefs its team."
          : `Make it the one you talk to (now: ${props.nameOf(team.lead)}).`}</span></span>
      </label>
      <label className="form-field">What it does
        <textarea rows={7} value={agent.role} maxLength={4000}
                  placeholder={outgoing.length
                    ? "e.g. Work out what the user wants, write a detailed prompt for each specialist and hand it to the right one."
                    : "e.g. Senior backend engineer: design the data model and API, write the code and save every file."}
                  onChange={(e) => props.onPatch({ role: e.target.value })} />
      </label>
      <div className="form-field">Skills
        {SKILLS.map((s) => (
          <label key={s.id} className="tp-skill">
            <input type="checkbox" checked={agent.skills.includes(s.id)}
                   onChange={(e) => toggleSkill(s.id, e.target.checked)} />
            <span><b>{s.label}</b><span className="sub">{s.hint}</span></span>
          </label>
        ))}
      </div>
      <div className="form-field">Hands work to
        <div className="tp-links">
          {outgoing.map((l) => (
            <span key={l.to} className="chip">{props.nameOf(l.to)}
              <button className="chip-x" aria-label={`Disconnect ${props.nameOf(l.to)}`}
                      onClick={() => props.onUnlink(l.to)}><X className="icon-sm" /></button>
            </span>
          ))}
          {candidates.length > 0 && (
            <select value="" aria-label="Connect to" onChange={(e) => e.target.value && props.onLink(e.target.value)}>
              <option value="">+ Connect to…</option>
              {candidates.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
        </div>
        <span className="sub">{outgoing.length
          ? "It writes each of them a brief and combines what they send back."
          : "Nobody — it does the work itself."}
          {incoming.length > 0 && ` Gets work from ${incoming.map((l) => props.nameOf(l.from)).join(", ")}.`}</span>
      </div>
      <label className="form-field">Model
        <select value={agent.model} onChange={(e) => props.onPatch({ model: e.target.value })}>
          <option value="">Default{props.models.active ? ` (${props.models.active})` : ""}</option>
          {props.models.names.map((m) => <option key={m} value={m}>{m}</option>)}
          {agent.model && !props.models.names.includes(agent.model) && <option value={agent.model}>{agent.model} (not installed)</option>}
        </select>
      </label>
      <div className="form-field">Look
        <div className="tp-swatches">
          {COLORS.map((c) => (
            <button key={c} className={`tp-swatch ${agent.color === c ? "on" : ""}`} style={{ background: c }}
                    aria-label={`Colour ${c}`} aria-pressed={agent.color === c} onClick={() => props.onPatch({ color: c })} />
          ))}
        </div>
        <div className="tp-icons">
          {ICONS.map((name) => {
            const I = AGENT_ICONS[name] ?? Bot;
            return (
              <button key={name} className={`ghost-icon ${agent.icon === name ? "on" : ""}`} title={name}
                      aria-label={`Icon ${name}`} aria-pressed={agent.icon === name}
                      onClick={() => props.onPatch({ icon: name })}><I /></button>
            );
          })}
        </div>
      </div>
      {state && state.status !== "idle" && (
        <div className="tp-last">
          <div className="eyebrow">In this run · {STATUS_LABEL[state.status] ?? state.status}</div>
          {state.brief && <div className="tp-brief"><span>Brief from {state.from === "You" ? "you" : props.nameOf(state.from)}</span><p>{state.brief}</p></div>}
          {state.plan && <div className="tp-brief"><span>What's needed</span><p>{state.plan}</p></div>}
          {state.output && <Answer content={state.output} streaming={state.status === "working"} />}
        </div>
      )}
      <button className="btn danger sm tp-delete" onClick={props.onDelete}><Trash2 /> Delete agent</button>
    </div>
  );
}

function RunResults(props: { run: RunState | null; team: Team; nameOf: (id: string) => string; seconds: number }) {
  const { run, team } = props;
  if (!run) {
    return (
      <EmptyState icon={Workflow} title="Nothing run yet">
        Tell {props.nameOf(team.lead)} what you need below. You'll see each agent's brief and work here.
      </EmptyState>
    );
  }
  const order = [team.lead, ...run.handoffs.map((h) => h.to)].filter((id, i, all) => all.indexOf(id) === i);
  return (
    <div className="tp-results">
      <div className="tp-run-head">
        <div className="eyebrow">Your request</div>
        <div className="tp-task">{run.task || "…"}</div>
        <div className="tp-run-meta">
          <span className={`tp-dot ${run.status}`} /> {RUN_LABEL[run.status] ?? run.status}
          <span className="muted">· {elapsed(props.seconds)}</span>
          {run.files.length > 0 && <span className="muted">· {run.files.length} file{run.files.length === 1 ? "" : "s"}</span>}
        </div>
        {run.preview && (
          <a className="btn primary sm" href={`${ORIGIN}${run.preview}`} target="_blank" rel="noreferrer">
            <ExternalLink /> Open the live preview
          </a>
        )}
      </div>
      {run.error && <div className="tp-error">{run.error}</div>}
      {run.final && (
        <section>
          <h4>Answer from {props.nameOf(team.lead)}</h4>
          <Answer content={run.final} />
        </section>
      )}
      {run.files.length > 0 && (
        <section>
          <h4>Files</h4>
          <ul className="tp-files">
            {run.files.map((f) => (
              <li key={f.path}>
                <FileCode className="icon-sm" />
                <a href={`${ORIGIN}${f.url}`} target="_blank" rel="noreferrer">{f.path}</a>
                <span className="muted">{sizeLabel(f.bytes)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h4>What each agent did</h4>
        {order.map((id) => {
          const a = run.agents[id];
          if (!a) return null;
          const member = team.agents.find((x) => x.id === id);
          const Icon = AGENT_ICONS[member?.icon ?? "bot"] ?? Bot;
          const busy = a.status === "working" || a.status === "planning";
          return (
            <details key={id} className={`tp-agent-out st-${a.status}`} open={busy || undefined}>
              <summary>
                <span className="tp-agent-icon" style={{ background: member?.color || "var(--accent)" }}><Icon /></span>
                <span className="grow">{props.nameOf(id)}</span>
                {busy && <span className="spinner" />}
                <span className="muted">{STATUS_LABEL[a.status] ?? a.status}</span>
              </summary>
              {a.brief && id !== team.lead && (
                <div className="tp-brief"><span>Brief from {a.from === "You" ? "you" : props.nameOf(a.from)}</span><p>{a.brief}</p></div>
              )}
              {a.plan && <div className="tp-brief"><span>What's needed</span><p>{a.plan}</p></div>}
              {a.tools.length > 0 && (
                <ul className="tp-tools">
                  {a.tools.map((t, i) => (
                    <li key={i} className={t.status}>
                      {t.status === "running" ? <span className="spinner" /> : <span className="tp-dot done" />}
                      <span>{t.tool.replace(/_/g, " ")}</span>
                      <span className="muted">{Object.values(t.args ?? {}).join(" · ").slice(0, 80)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {a.output ? <Answer content={a.output} streaming={a.status === "working"} />
                : busy ? <div className="sub">{a.detail || "Working…"}</div> : null}
            </details>
          );
        })}
      </section>
    </div>
  );
}

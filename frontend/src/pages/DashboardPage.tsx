import { useEffect, useRef, useState } from "react";
import {
  Activity, AppWindow, ArrowUp, CloudSun, Cpu, Ear, Globe, Lightbulb, Mail, MessagesSquare, Mic, Monitor,
  Music, PanelRight, Square, TriangleAlert, X,
} from "lucide-react";
import { API, statsApi, SystemStats } from "../lib/api";
import { LightInfo, LightRow } from "../components/LightsPanel";
import { voiceBus } from "../lib/voice";
import { Core, CoreDesign, CoreMode } from "../components/Core";
import { Answer, ToolChipInfo } from "../components/ChatView";
import { describeAction, stepLabel } from "../lib/format";

/** An audit event in words: "Checked the weather", "Asked: Send an email". */
function activityLabel(e: { event: string; tool?: string }): string {
  const tool = e.tool ?? "";
  switch (e.event) {
    case "tool_start": return stepLabel(tool, false);
    case "tool_ok": return stepLabel(tool, true);
    case "tool_error": return `${stepLabel(tool, false)} — failed`;
    case "confirmation_requested": return `Asked: ${describeAction(tool, {}).title}`;
    case "confirmation_resolved": return `${describeAction(tool, {}).title} — answered`;
    default: return `${e.event.replace(/_/g, " ")} ${tool.replace(/_/g, " ")}`.trim();
  }
}

function Meter({ label, value, detail }: { label: string; value: number; detail?: string }) {
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <span>{detail ?? `${Math.round(value)}%`}</span>
      </div>
      <div className="progress-bar"><div style={{ width: `${Math.min(100, value)}%` }} /></div>
    </div>
  );
}

const QUICK = [
  { icon: CloudSun, text: "What's the weather today?" },
  { icon: Mail, text: "Summarise my unread emails" },
  { icon: Monitor, text: "What's on my screen?" },
  { icon: Globe, text: "What's new in AI this week?" },
];

/** The orb fills a good share of the window, but never crowds the controls. */
function useCoreSize() {
  const pick = () => Math.round(Math.max(200, Math.min(400, window.innerHeight * 0.4)));
  const [size, setSize] = useState(pick);
  useEffect(() => {
    const on = () => setSize(pick());
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return size;
}

export function DashboardPage(props: {
  busy: boolean;
  listening: boolean;
  assistantName: string;
  onCommand: (text: string) => void;
  onStop: () => void;
  onOpenChat: () => void;
  lastUser: string | null;
  reply: string | null;
  chips: ToolChipInfo[];
  interim: string;
  voiceState: "idle" | "listening" | "waiting-wake";
  wakeWord: string;
  wakeActive: boolean;
  voiceSupported: boolean;
  voiceEngine: "whisper" | "browser";
  onToggleWake: () => void;
  onPushToTalk: () => void;
  coreDesign: CoreDesign;
  onCycleDesign: () => void;
  setupProblems: number;
  onOpenSetup: () => void;
}) {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [ctx, setCtx] = useState<any>(null);
  const [speaking, setSpeaking] = useState(false);
  const [command, setCommand] = useState("");
  const [hudOpen, setHudOpen] = useState(false);
  const [lights, setLights] = useState<LightInfo[]>([]);
  const loadLights = () => fetch(`${API}/lights`).then((r) => r.json())
    .then((r) => setLights(r.configured ? r.lights : [])).catch(() => {});
  useEffect(() => {
    loadLights();
    const t = setInterval(loadLights, 20000);
    return () => clearInterval(t);
  }, []);
  const replyRef = useRef<HTMLDivElement>(null);
  const coreSize = useCoreSize();

  // keep the reply pinned to the latest words
  useEffect(() => {
    replyRef.current?.scrollTo({ top: replyRef.current.scrollHeight });
  }, [props.reply, props.chips.length, props.lastUser]);

  useEffect(() => {
    const onSpeak = (e: Event) => setSpeaking((e as CustomEvent).detail);
    voiceBus.addEventListener("speaking", onSpeak);
    return () => voiceBus.removeEventListener("speaking", onSpeak);
  }, []);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const s = await statsApi.stats();
        if (alive) setStats(s);
      } catch { if (alive) setStats(null); }
      try {
        const c = await statsApi.context();
        if (alive) setCtx(c);
      } catch { /* context off */ }
    };
    poll();
    const t = setInterval(poll, 4000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const mode: CoreMode = speaking ? "speaking" : props.busy ? "thinking"
    : props.listening ? "listening" : "idle";
  const statusText = { speaking: "Speaking", thinking: "Working", listening: "Listening", idle: "Online" }[mode];

  const submit = () => {
    if (!command.trim()) return;
    props.onCommand(command.trim());
    setCommand("");
  };

  const hint = props.interim ? props.interim
    : props.voiceState === "listening" ? "Listening…"
    : props.voiceState === "waiting-wake"
      ? (props.voiceEngine === "browser"
          ? `Say “${props.wakeWord}” — download Whisper in Settings → Voice for a more reliable wake word`
          : `Say “${props.wakeWord}” — I'm listening`)
    : props.voiceSupported ? <span className="inline-icon">Press <Ear className="icon-sm" /> to wake me with “{props.wakeWord}”</span>
    : null;

  const hasExchange = !!(props.lastUser || props.busy);

  return (
    <div className={`dashboard ${hudOpen ? "hud-open" : ""}`}>
      {props.setupProblems > 0 && (
        <button className="notice" onClick={props.onOpenSetup}>
          <TriangleAlert />
          {props.setupProblems} thing{props.setupProblems > 1 ? "s" : ""} to set up
          <span className="go">Fix →</span>
        </button>
      )}
      <button className="icon-btn hud-toggle" title="System status" aria-label="System status"
              onClick={() => setHudOpen((o) => !o)}><PanelRight /></button>

      <div className="dash-center" onMouseDown={() => hudOpen && setHudOpen(false)}>
        <div className="core-canvas">
          <Core mode={mode} design={props.coreDesign} onClick={props.onCycleDesign}
                size={hasExchange ? Math.round(coreSize * 0.62) : coreSize} />
        </div>
        <div className={`core-state ${mode}`}><span className="dot" />{statusText}</div>
        <div className={`core-sub ${stats && !stats.ollama_up ? "offline" : ""}`}>
          {stats?.ollama_up ? `${stats.active_model} · running locally`
            : stats ? "AI engine offline — open Ollama" : " "}
        </div>

        {hasExchange && (
          <div className="exchange">
            {props.lastUser && (
              <div className="exchange-you" dir="auto">
                <span className="who">You</span><span className="what" title={props.lastUser}>{props.lastUser}</span>
              </div>
            )}
            <div className="exchange-reply" ref={replyRef} dir="auto">
              {props.chips.length > 0 && (
                <div className="steps">
                  {props.chips.map((c, i) => (
                    <span key={i} className={`step ${c.status}`}>
                      {c.status === "running" ? <span className="spinner" style={{ width: 11, height: 11 }} /> : null}
                      {c.status === "pending" ? c.name : stepLabel(c.name, c.status !== "running")}
                    </span>
                  ))}
                </div>
              )}
              {props.reply ? <Answer content={props.reply} streaming={props.busy} />
                : props.busy ? <div className="typing" aria-label="Thinking"><span /><span /><span /></div> : null}
            </div>
            {!props.busy && props.reply && (
              <div className="exchange-actions">
                <button className="btn ghost sm" onClick={props.onOpenChat}><MessagesSquare /> Open in Chat</button>
              </div>
            )}
          </div>
        )}

        <form className="command" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          {props.voiceSupported && (
            <button type="button" className={`icon-btn ${props.voiceState === "listening" ? "recording" : ""}`}
                    title="Push to talk" aria-label="Push to talk" onClick={props.onPushToTalk}>
              <Mic />
            </button>
          )}
          <input placeholder={`Ask ${props.assistantName} anything…`} value={command}
                 aria-label="Command" onChange={(e) => setCommand(e.target.value)} />
          {props.voiceSupported && (
            <button type="button" className={`icon-btn ${props.wakeActive ? "wake-on" : ""}`}
                    title={props.wakeActive ? "Wake word on" : `Wake word (“${props.wakeWord}”)`}
                    aria-label="Wake word" aria-pressed={props.wakeActive} onClick={props.onToggleWake}>
              <Ear />
            </button>
          )}
          {props.busy ? (
            <button type="button" className="icon-btn" title="Stop" aria-label="Stop" onClick={props.onStop}><Square /></button>
          ) : (
            <button type="submit" className="icon-btn primary" title="Send" aria-label="Send"
                    disabled={!command.trim()}><ArrowUp /></button>
          )}
        </form>

        {!hasExchange && (
          <div className="quick-chips">
            {QUICK.map((q) => (
              <button key={q.text} onClick={() => props.onCommand(q.text)}><q.icon /> {q.text}</button>
            ))}
          </div>
        )}
        <div className="voice-hint">{hint}</div>
      </div>

      <aside className="dash-right" aria-label="System status">
        <button className="icon-btn hud-close" title="Close" aria-label="Close system status"
                onClick={() => setHudOpen(false)}><X /></button>
        <div className="hud-panel">
          <h4><Cpu /> System</h4>
          {stats ? (
            <>
              <Meter label="CPU" value={stats.cpu_percent} />
              <Meter label="Memory" value={stats.memory_percent}
                     detail={`${stats.memory_used_gb} / ${stats.memory_total_gb} GB`} />
              {stats.loaded_models.map((m) => (
                <Meter key={m.name} label={m.name} value={m.gpu_percent}
                       detail={`${m.size_gb} GB`} />
              ))}
              {stats.loaded_models.length === 0 && (
                <div className="hud-dim">No model loaded — it loads with the first message</div>
              )}
            </>
          ) : (
            <div className="hud-dim">Backend offline</div>
          )}
        </div>

        <div className="hud-panel">
          <h4><Activity /> Activity</h4>
          {stats?.running_tools.length ? (
            stats.running_tools.map((t) => (
              <div key={t} className="hud-row"><span className="spinner" /> <span className="t">{stepLabel(t, false)}</span></div>
            ))
          ) : (
            <div className="hud-dim">Idle</div>
          )}
          {(stats?.recent_activity ?? []).slice(0, 5).map((e, i) => (
            <div key={i} className="hud-row dim">
              <span className="t">{activityLabel(e)}</span>
            </div>
          ))}
        </div>

        {lights.length > 0 && (
          <div className="hud-panel">
            <h4><Lightbulb /> Lights</h4>
            {lights.map((l) => <LightRow key={l.id} light={l} onChanged={loadLights} compact />)}
          </div>
        )}

        <div className="hud-panel">
          <h4><AppWindow /> Context</h4>
          {ctx?.enabled ? (
            <>
              {ctx.degraded && <div className="hud-dim"><TriangleAlert className="icon-sm" /> {ctx.degraded}</div>}
              <div className="hud-row"><AppWindow /> <span className="t">{ctx.frontmost_app || "—"}</span></div>
              <div className="hud-row"><Globe /> <span className="t">{ctx.browser} · {ctx.tabs?.length ?? 0} tabs</span></div>
              {ctx.music?.running && ctx.music.track && (
                <div className="hud-row"><Music /> <span className="t">{ctx.music.track} — {ctx.music.artist}</span></div>
              )}
              {(ctx.tabs ?? []).slice(0, 4).map((t: any) => (
                <div key={t.index} className="hud-row dim"><span className="t">{t.title}</span></div>
              ))}
            </>
          ) : (
            <div className="hud-dim">Context awareness is off</div>
          )}
        </div>
      </aside>
    </div>
  );
}

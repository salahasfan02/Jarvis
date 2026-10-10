import { useEffect, useRef, useState } from "react";
import { Ear, Mic, Music, TriangleAlert } from "lucide-react";
import { statsApi, SystemStats } from "../lib/api";
import { voiceBus } from "../lib/voice";
import { Core, CoreDesign, CoreMode } from "../components/Core";

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

import { ToolChipInfo } from "../components/ChatView";

export function DashboardPage(props: {
  busy: boolean;
  listening: boolean;
  assistantName: string;
  onCommand: (text: string) => void;
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
}) {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [ctx, setCtx] = useState<any>(null);
  const [speaking, setSpeaking] = useState(false);
  const [command, setCommand] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const termRef = useRef<HTMLDivElement>(null);

  // keep the terminal pinned to the latest output
  useEffect(() => {
    termRef.current?.scrollTo({ top: termRef.current.scrollHeight });
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
  const statusText = { speaking: "SPEAKING", thinking: "PROCESSING",
    listening: "LISTENING", idle: "ONLINE" }[mode];

  return (
    <div className="dashboard">
      <div className="dash-center">
        <Core mode={mode} design={props.coreDesign} onClick={props.onCycleDesign} />
        <div className={`core-status ${mode}`}>{statusText}</div>
        <div className="core-sub">
          {stats?.ollama_up
            ? `${stats.active_model} · local · secure`
            : "AI engine offline — start Ollama"}
        </div>
        {(props.lastUser || props.busy) && (
          <div className="terminal" ref={termRef}>
            {props.lastUser && <div className="cmd">&gt; {props.lastUser}</div>}
            {props.chips.map((c, i) => (
              <div key={i} className="tool" style={c.status === "pending" ? { opacity: 0.5 } : undefined}>
                [{c.status === "running" ? "…" : c.status === "denied" ? "denied"
                  : c.status === "pending" ? " " : "ok"}] {c.name}
              </div>
            ))}
            {props.reply ? (
              <div className={`reply ${props.busy ? "cursor" : ""}`}>{props.reply}</div>
            ) : (
              props.busy && <div className="reply cursor" />
            )}
          </div>
        )}

        <form
          className="command-bar"
          onSubmit={(e) => {
            e.preventDefault();
            if (command.trim()) {
              props.onCommand(command.trim());
              setCommand("");
            }
          }}
        >
          {props.voiceSupported && (
            <button type="button"
                    className={`icon-btn ${props.voiceState === "listening" ? "recording" : ""}`}
                    title="Push to talk" onClick={props.onPushToTalk}>
              <Mic />
            </button>
          )}
          <input
            ref={inputRef}
            placeholder={`Give ${props.assistantName} a command…`}
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && command.trim()) {
                e.preventDefault();
                props.onCommand(command.trim());
                setCommand("");
              }
            }}
          />
          {props.voiceSupported && (
            <button type="button"
                    className={`icon-btn ${props.wakeActive ? "wake-on" : ""}`}
                    title={`Wake word ("${props.wakeWord}")`} onClick={props.onToggleWake}>
              <Ear />
            </button>
          )}
        </form>
        <div className="voice-hint">
          {/* The listener's own messages ("Click anywhere so I can hear you",
              errors) win in every state — they were hidden while waiting. */}
          {props.interim ? props.interim
            : props.voiceState === "listening" ? "Listening…"
            : props.voiceState === "waiting-wake"
              ? (props.voiceEngine === "browser"
                  ? `Say "${props.wakeWord}" — using the browser's recognizer; download Whisper in Settings → Voice for a reliable wake word`
                  : `Say "${props.wakeWord}" — I'm listening`)
            : props.voiceSupported && !props.wakeActive
              ? <span className="inline-icon">Wake word off — press <Ear className="icon-sm" /> to enable</span>
            : null}
        </div>
      </div>

      <div className="dash-right">
        <div className="hud-panel">
          <h4>System</h4>
          {stats ? (
            <>
              <Meter label="CPU" value={stats.cpu_percent} />
              <Meter label="Memory" value={stats.memory_percent}
                     detail={`${stats.memory_used_gb} / ${stats.memory_total_gb} GB`} />
              {stats.loaded_models.map((m) => (
                <Meter key={m.name} label={`Model · ${m.name}`} value={m.gpu_percent}
                       detail={`${m.size_gb} GB · ${m.gpu_percent}% GPU`} />
              ))}
              {stats.loaded_models.length === 0 && (
                <div className="hud-dim">no model loaded (loads on first message)</div>
              )}
            </>
          ) : (
            <div className="hud-dim">backend offline</div>
          )}
        </div>

        <div className="hud-panel">
          <h4>Tool activity</h4>
          {stats?.running_tools.length ? (
            stats.running_tools.map((t) => (
              <div key={t} className="hud-row"><span className="spinner" /> {t}</div>
            ))
          ) : (
            <div className="hud-dim">idle</div>
          )}
          {(stats?.recent_activity ?? []).slice(0, 5).map((e, i) => (
            <div key={i} className="hud-row dim">
              {e.event.replace(/_/g, " ")} {e.tool ?? ""}
            </div>
          ))}
        </div>

        <div className="hud-panel">
          <h4>Context</h4>
          {ctx?.enabled ? (
            <>
              {ctx.degraded && <div className="hud-dim"><TriangleAlert className="icon-sm" /> {ctx.degraded}</div>}
              <div className="hud-row">App: {ctx.frontmost_app || "—"}</div>
              <div className="hud-row">Browser: {ctx.browser} · {ctx.tabs?.length ?? 0} tabs</div>
              {ctx.music?.running && ctx.music.track && (
                <div className="hud-row">
                  <Music className="icon-sm" /> {ctx.music.state}: {ctx.music.track} — {ctx.music.artist}
                </div>
              )}
              {(ctx.tabs ?? []).slice(0, 4).map((t: any) => (
                <div key={t.index} className="hud-row dim">{t.title?.slice(0, 38)}</div>
              ))}
            </>
          ) : (
            <div className="hud-dim">context awareness off</div>
          )}
        </div>
      </div>
    </div>
  );
}

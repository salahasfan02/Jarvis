import { useEffect, useState } from "react";
import { Gauge } from "lucide-react";
import { API, api, OllamaModel, pullModel, statsApi } from "../lib/api";

function Row(props: { label: string; sub?: string; children: React.ReactNode }) {
  return (
    <div className="row">
      <div>
        <div className="label">{props.label}</div>
        {props.sub && <div className="sub">{props.sub}</div>}
      </div>
      {props.children}
    </div>
  );
}

function Toggle(props: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="switch">
      <input type="checkbox" checked={props.checked}
             onChange={(e) => props.onChange(e.target.checked)} />
      <span />
    </label>
  );
}

interface PhoneStatus {
  configured: boolean;
  enabled: boolean;
  running: boolean;
  connected: boolean;
  bot_username: string;
  error: string;
  pairing_code: string;
  pairing_expires_in: number;
  allowed_users: { id: number; name: string; username?: string }[];
  allow_dangerous: boolean;
  voice_replies: boolean;
}

/** Text Jarvis from your phone: connect a Telegram bot, pair accounts, set limits. */
function PhonePanel(props: { onPatch: (patch: any) => void }) {
  const [st, setSt] = useState<PhoneStatus | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = () =>
    fetch(`${API}/telegram/status`).then((r) => r.json()).then(setSt).catch(() => {});
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);  // pairing completes on the phone
    return () => clearInterval(t);
  }, []);

  const call = async (path: string, method = "POST", body?: unknown) => {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/telegram/${path}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const r = await res.json();
      if (r.token_error) setError(r.token_error);
      setSt(r);
      return r;
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const patch = (p: Partial<PhoneStatus>) => {
    props.onPatch({ telegram: p });
    setSt((s) => (s ? { ...s, ...p } : s));
    setTimeout(refresh, 1000);
  };

  if (!st) return null;
  const bot = st.bot_username ? `@${st.bot_username}` : "your bot";
  const state = st.connected ? `Connected as ${bot} — message it from your phone.`
    : st.error ? st.error
    : st.enabled ? "Connecting to Telegram…" : "Off — Jarvis isn't reading Telegram.";

  return (
    <div className="panel">
      <h3>Phone (Telegram)</h3>
      <div className="sub" style={{ marginBottom: 8 }}>
        Text or voice-message Jarvis from anywhere: “send me the PDF in my Downloads”,
        “research flights to Lisbon and send me a Word doc”. Messages and files travel
        through Telegram's servers; your Mac never opens a port to the internet.
      </div>

      {!st.configured ? (
        <Row label="1. Create your bot"
             sub="In Telegram, message @BotFather, send /newbot, choose a name, then paste the token it gives you.">
          <div style={{ display: "flex", gap: 8 }}>
            <input type="password" placeholder="123456789:AAH…" value={token}
                   onChange={(e) => setToken(e.target.value)} />
            <button className="btn primary" disabled={busy || !token.trim()}
                    onClick={() => call("token", "POST", { token }).then((r) => r?.configured && setToken(""))}>
              {busy ? "Checking…" : "Connect"}
            </button>
          </div>
        </Row>
      ) : (
        <Row label="Bot" sub={state}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Toggle checked={st.enabled} onChange={(v) => patch({ enabled: v })} />
            <button className="btn danger" disabled={busy}
                    onClick={() => confirm("Disconnect the Telegram bot from Jarvis?") && call("token", "DELETE")}>
              Disconnect
            </button>
          </div>
        </Row>
      )}
      {error && <div className="sub" style={{ color: "var(--danger)", padding: "4px 0" }}>{error}</div>}

      {st.configured && (
        <>
          <Row label={st.allowed_users.length ? "Paired accounts" : "2. Pair your phone"}
               sub={st.pairing_code
                 ? `Send this to ${bot} from your phone (valid ${Math.ceil(st.pairing_expires_in / 60)} min), or open the link if Telegram is on this Mac.`
                 : "Only paired Telegram accounts can talk to Jarvis — everyone else is ignored."}>
            {st.pairing_code ? (
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span className="pair-code">/pair {st.pairing_code}</span>
                {st.bot_username && (
                  <a className="btn" target="_blank" rel="noreferrer"
                     href={`https://t.me/${st.bot_username}?start=pair_${st.pairing_code}`}>
                    Open in Telegram
                  </a>
                )}
              </div>
            ) : (
              <button className="btn" disabled={busy} onClick={() => call("pairing")}>
                Pair a phone
              </button>
            )}
          </Row>
          {st.allowed_users.map((u) => (
            <Row key={u.id} label={u.name} sub={u.username ? `@${u.username} on Telegram` : `Telegram id ${u.id}`}>
              <button className="btn danger" disabled={busy}
                      onClick={() => call(`users/${u.id}`, "DELETE")}>Remove</button>
            </Row>
          ))}
          <Row label="Voice replies"
               sub="Answer your voice notes with a voice note in Jarvis's voice (needs the Kokoro voice downloaded).">
            <Toggle checked={st.voice_replies} onChange={(v) => patch({ voice_replies: v })} />
          </Row>
          <Row label="Allow dangerous tools from the phone"
               sub="Shell commands, AppleScript, deleting files, installing skills. Off: blocked from the phone entirely. On: allowed, but still asks you every time.">
            <Toggle checked={st.allow_dangerous} onChange={(v) => patch({ allow_dangerous: v })} />
          </Row>
        </>
      )}
    </div>
  );
}

export function SettingsPage(props: {
  settings: any;
  onPatch: (patch: any) => void;
}) {
  const s = props.settings;
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [pullName, setPullName] = useState("");
  const [pullStatus, setPullStatus] = useState<{ text: string; pct: number } | null>(null);
  const [tools, setTools] = useState<any[]>([]);
  const [engines, setEngines] = useState<any[]>([]);
  const [kokoroVoices, setKokoroVoices] = useState<{ id: string; name: string }[]>([]);
  const [downloadStatus, setDownloadStatus] = useState<string>("");

  const refreshEngines = () => statsApi.ttsEngines().then(setEngines).catch(() => {});
  const refreshModels = () => api.models().then((r) => setModels(r.models)).catch(() => {});
  useEffect(() => {
    refreshModels();
    refreshEngines();
    api.tools().then(setTools).catch(() => {});
    fetch(`${API}/tts/voices`).then((r) => r.json()).then(setKokoroVoices).catch(() => {});
  }, []);

  const kokoroReady = engines.find((e: any) => e.id === "kokoro")?.available === true;

  const [benchResults, setBenchResults] = useState<Record<string, string>>({});
  const [benching, setBenching] = useState<string>("");

  const runBenchmark = async (name: string) => {
    setBenching(name);
    try {
      const res = await fetch(`${API}/models/benchmark`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const r = await res.json();
      setBenchResults((b) => ({
        ...b,
        [name]: r.error ? `benchmark failed: ${r.error.slice(0, 50)}`
          : `${r.generate_tokens_per_s} tok/s generate · ${r.prompt_tokens_per_s} tok/s prompt` +
            (r.load_seconds > 0.5 ? ` · ${r.load_seconds}s load` : ""),
      }));
    } finally {
      setBenching("");
    }
  };

  const [screenMem, setScreenMem] = useState<any>(null);
  const refreshScreenMem = () =>
    fetch(`${API}/screen-memory`).then((r) => r.json()).then(setScreenMem).catch(() => {});
  useEffect(() => {
    refreshScreenMem();
    const t = setInterval(refreshScreenMem, 8000);
    return () => clearInterval(t);
  }, []);
  const toggleScreenMemory = (on: boolean) => {
    fetch(`${API}/screen-memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: on,
        interval_seconds: s?.screen_memory?.interval_seconds ?? 300 }),
    }).then((r) => r.json()).then(setScreenMem).catch(() => {});
  };

  const [sttStatus, setSttStatus] = useState<any>(null);
  const [sttDownload, setSttDownload] = useState<string>("");
  const refreshStt = () =>
    fetch(`${API}/stt/status`).then((r) => r.json()).then(setSttStatus).catch(() => {});
  useEffect(() => { refreshStt(); }, [s?.voice?.whisper_model]);

  const downloadWhisper = async () => {
    setSttDownload("starting…");
    try {
      const res = await fetch(`${API}/stt/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: s?.voice?.whisper_model ?? "base" }),
      });
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.error) setSttDownload(`failed: ${ev.error.slice(0, 60)}`);
          else if (ev.percent !== undefined) setSttDownload(`${ev.percent}% (${ev.mb} MB)`);
          if (ev.done) {
            setSttDownload("");
            refreshStt();
          }
        }
      }
    } catch (e: any) {
      setSttDownload(`failed: ${e.message}`);
    }
  };

  const downloadKokoro = async () => {
    setDownloadStatus("starting…");
    try {
      const res = await fetch(`${API}/tts/kokoro/download`, { method: "POST" });
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.error) setDownloadStatus(`failed: ${ev.error.slice(0, 60)}`);
          else if (ev.percent !== undefined)
            setDownloadStatus(`${ev.file} — ${ev.percent}% (${ev.mb} MB)`);
          else if (ev.status) setDownloadStatus(`${ev.file ?? ""} ${ev.status}`);
          if (ev.done) {
            setDownloadStatus("");
            refreshEngines();
          }
        }
      }
    } catch (e: any) {
      setDownloadStatus(`failed: ${e.message}`);
    }
  };

  if (!s) return <div className="page">Loading…</div>;

  const doPull = async () => {
    const name = pullName.trim();
    if (!name) return;
    setPullStatus({ text: "starting…", pct: 0 });
    try {
      await pullModel(name, (e) => {
        if (e.error) setPullStatus({ text: `error: ${e.error}`, pct: 0 });
        else {
          const pct = e.total ? Math.round((e.completed / e.total) * 100) : 0;
          setPullStatus({ text: `${e.status ?? ""} ${pct ? pct + "%" : ""}`, pct });
        }
      });
      setPullStatus({ text: "done", pct: 100 });
      setPullName("");
      refreshModels();
    } catch (e: any) {
      setPullStatus({ text: `failed: ${e.message}`, pct: 0 });
    }
  };

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Settings</h1>

        <div className="panel">
          <h3>AI model</h3>
          <Row label="Active model" sub="Used for all conversations; switch anytime.">
            <select
              value={s.ollama.model}
              onChange={(e) => props.onPatch({ ollama: { model: e.target.value } })}
            >
              {!models.some((m) => m.name.startsWith(s.ollama.model)) && (
                <option value={s.ollama.model}>{s.ollama.model}</option>
              )}
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name} {m.details?.parameter_size ? `(${m.details.parameter_size})` : ""}
                </option>
              ))}
            </select>
          </Row>
          <Row label="Vision model" sub="Multimodal model for camera/screen (e.g. llava). Empty = disabled.">
            <input type="text" value={s.ollama.vision_model}
                   placeholder="llava"
                   onChange={(e) => props.onPatch({ ollama: { vision_model: e.target.value } })} />
          </Row>
          <Row label="Embedding model" sub="For semantic memory recall (e.g. nomic-embed-text). Empty = keyword matching.">
            <input type="text" value={s.ollama.embedding_model}
                   placeholder="nomic-embed-text"
                   onChange={(e) => props.onPatch({ ollama: { embedding_model: e.target.value } })} />
          </Row>
          <Row label="Temperature" sub="0 = precise, 1 = creative">
            <input type="number" step={0.1} min={0} max={2} value={s.ollama.temperature}
                   onChange={(e) => props.onPatch({ ollama: { temperature: parseFloat(e.target.value) || 0 } })} />
          </Row>
          <Row label="Context length" sub="Tokens the model can see (higher = more RAM)">
            <input type="number" step={1024} value={s.ollama.num_ctx}
                   onChange={(e) => props.onPatch({ ollama: { num_ctx: parseInt(e.target.value) || 8192 } })} />
          </Row>
          <Row label="GPU layers" sub="-1 lets Ollama decide; 0 forces CPU">
            <input type="number" value={s.ollama.num_gpu}
                   onChange={(e) => props.onPatch({ ollama: { num_gpu: parseInt(e.target.value) } })} />
          </Row>
          <Row label="Keep model in memory" sub="e.g. 5m, 1h, -1 = forever">
            <input type="text" value={s.ollama.keep_alive}
                   onChange={(e) => props.onPatch({ ollama: { keep_alive: e.target.value } })} />
          </Row>
        </div>

        <div className="panel">
          <h3>Task models</h3>
          <div className="sub" style={{ marginBottom: 8 }}>
            Assign specialized models per task. Empty = use the main chat model.
            A small utility model makes titles and self-analysis near-instant.
          </div>
          {([["coding", "Coding", "Code Studio and the coding agent"],
             ["utility", "Utility", "Titles, gap analysis, background summaries"]] as const)
            .map(([key, label, sub]) => (
            <Row key={key} label={label} sub={sub}>
              <select value={s.ollama.task_models?.[key] ?? ""}
                      onChange={(e) => props.onPatch({ ollama: { task_models: { [key]: e.target.value } } })}>
                <option value="">Same as chat model</option>
                {models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
              </select>
            </Row>
          ))}
        </div>

        <div className="panel">
          <h3>Installed models</h3>
          {models.map((m) => (
            <Row key={m.name} label={m.name}
                 sub={benchResults[m.name]
                      ?? `${(m.size / 1e9).toFixed(1)} GB ${m.details?.quantization_level ?? ""}`}>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn" disabled={benching === m.name}
                        onClick={() => runBenchmark(m.name)}>
                  {benching === m.name ? "Benchmarking…" : <><Gauge /> Benchmark</>}
                </button>
                <button className="btn danger"
                        onClick={() => api.deleteModel(m.name).then(refreshModels)}>
                  Remove
                </button>
              </div>
            </Row>
          ))}
          <Row label="Download a model" sub="Any model from ollama.com/library">
            <div style={{ display: "flex", gap: 8, flexDirection: "column", alignItems: "flex-end" }}>
              <div style={{ display: "flex", gap: 8 }}>
                <input type="text" placeholder="e.g. qwen2.5, mistral, llava"
                       value={pullName} onChange={(e) => setPullName(e.target.value)} />
                <button className="btn primary" onClick={doPull}>Pull</button>
              </div>
              {pullStatus && (
                <div style={{ width: 280 }}>
                  <div className="pull-progress">{pullStatus.text}</div>
                  <div className="progress-bar"><div style={{ width: `${pullStatus.pct}%` }} /></div>
                </div>
              )}
            </div>
          </Row>
        </div>

        <div className="panel">
          <h3>Assistant</h3>
          <Row label="Name">
            <input type="text" value={s.assistant.name}
                   onChange={(e) => props.onPatch({ assistant: { name: e.target.value } })} />
          </Row>
          <Row label="Instant commands"
               sub="Simple commands like “open YouTube”, “open Safari”, “play lofi on YouTube” or “pause” run immediately without the AI model — well under a second instead of several.">
            <Toggle checked={s.assistant.instant_commands ?? true}
                    onChange={(v) => props.onPatch({ assistant: { instant_commands: v } })} />
          </Row>
          <Row label="Wake words" sub="Comma-separated">
            <input type="text" value={s.assistant.wake_words.join(", ")}
                   onChange={(e) => props.onPatch({
                     assistant: { wake_words: e.target.value.split(",").map((w: string) => w.trim()).filter(Boolean) },
                   })} />
          </Row>
        </div>

        <div className="panel">
          <h3>Voice</h3>
          <Row label="Voice input" sub="Microphone button & wake word">
            <Toggle checked={s.voice.enabled}
                    onChange={(v) => props.onPatch({ voice: { enabled: v } })} />
          </Row>
          <Row label="Speak responses" sub="Read answers aloud">
            <Toggle checked={s.voice.tts_enabled}
                    onChange={(v) => props.onPatch({ voice: { tts_enabled: v } })} />
          </Row>
          <Row label="Conversation mode"
               sub="After Jarvis speaks, automatically reopen the mic so you can reply without saying the wake word again (Core screen).">
            <Toggle checked={s.voice.conversation_mode ?? false}
                    onChange={(v) => props.onPatch({ voice: { conversation_mode: v } })} />
          </Row>
          <Row label="Voice engine"
               sub="Kokoro is a local neural engine with human-sounding voices (recommended). If it isn't ready, Jarvis falls back to the basic system voice.">
            <select value={s.voice.tts_engine ?? "kokoro"}
                    onChange={(e) => props.onPatch({ voice: { tts_engine: e.target.value } })}>
              {(engines.length ? engines : [{ id: "kokoro", name: "Kokoro (human, local)", available: false, reason: "backend offline" }])
                .map((e: any) => (
                  <option key={e.id} value={e.id}>
                    {e.name}{e.available ? "" : ` — ${e.reason}`}
                  </option>
                ))}
            </select>
          </Row>
          {(s.voice.tts_engine ?? "kokoro") === "kokoro" && (
            kokoroReady ? (
              <Row label="Jarvis voice" sub="Neural voices — all sound natural and human">
                <select value={s.voice.kokoro_voice ?? "bm_george"}
                        onChange={(e) => props.onPatch({ voice: { kokoro_voice: e.target.value } })}>
                  {kokoroVoices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
              </Row>
            ) : (
              <Row label="Voice model" sub="One-time download (~340 MB) from the Kokoro release on GitHub; stored locally in ~/.jarvis/models">
                <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
                  <button className="btn primary" disabled={!!downloadStatus && !downloadStatus.startsWith("failed")}
                          onClick={downloadKokoro}>
                    {downloadStatus ? downloadStatus : "Download human voices"}
                  </button>
                </div>
              </Row>
            )
          )}
          {s.voice.tts_engine === "piper" && (
            <Row label="Piper voice model" sub="Path to a .onnx voice, e.g. ~/piper/en_US-lessac-medium.onnx">
              <input type="text" value={s.voice.piper_voice_path ?? ""}
                     placeholder="/path/to/voice.onnx"
                     onChange={(e) => props.onPatch({ voice: { piper_voice_path: e.target.value } })} />
            </Row>
          )}
          <Row label="Speech rate">
            <input type="number" step={0.1} min={0.5} max={2} value={s.voice.tts_rate}
                   onChange={(e) => props.onPatch({ voice: { tts_rate: parseFloat(e.target.value) || 1 } })} />
          </Row>
          <Row label="Speech recognition"
               sub="Whisper runs 100% offline on your Mac and works in every browser. Browser mode needs Chrome and sends audio to Google.">
            <select value={s.voice.stt_engine ?? "whisper"}
                    onChange={(e) => props.onPatch({ voice: { stt_engine: e.target.value } })}>
              <option value="whisper">Whisper (offline, recommended)</option>
              <option value="browser">Browser (Chrome, online)</option>
            </select>
          </Row>
          {(s.voice.stt_engine ?? "whisper") === "whisper" && (
            <Row label="Whisper model"
                 sub={sttStatus?.available
                      ? `'${sttStatus.model}' ready — recognition is fully local`
                      : "tiny 75 MB (fastest) · base 145 MB (recommended) · small 484 MB (most accurate)"}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <select value={s.voice.whisper_model ?? "base"}
                        onChange={(e) => props.onPatch({ voice: { whisper_model: e.target.value } })}>
                  <option value="tiny">tiny</option>
                  <option value="base">base</option>
                  <option value="small">small</option>
                </select>
                {sttStatus && !sttStatus.available && (
                  <button className="btn primary" disabled={!!sttDownload && !sttDownload.startsWith("failed")}
                          onClick={downloadWhisper}>
                    {sttDownload || "Download"}
                  </button>
                )}
              </div>
            </Row>
          )}
          <Row label="Language" sub="Speech recognition language, e.g. en-US">
            <input type="text" value={s.voice.language}
                   onChange={(e) => props.onPatch({ voice: { language: e.target.value } })} />
          </Row>
        </div>

        <PhonePanel onPatch={props.onPatch} />

        <div className="panel">
          <h3>Memory</h3>
          <Row label="Long-term memory" sub="Recall saved facts in every conversation">
            <Toggle checked={s.memory.enabled}
                    onChange={(v) => props.onPatch({ memory: { enabled: v } })} />
          </Row>
          <Row label="Max recalled memories">
            <input type="number" min={1} max={20} value={s.memory.max_recalled}
                   onChange={(e) => props.onPatch({ memory: { max_recalled: parseInt(e.target.value) || 5 } })} />
          </Row>
          <Row label="Auto-capture memories"
               sub="Quietly learn durable facts you mention (preferences, projects, goals). Saved as 'auto' memories you can edit or delete.">
            <Toggle checked={s.memory.auto_capture ?? true}
                    onChange={(v) => props.onPatch({ memory: { auto_capture: v } })} />
          </Row>
          <Row label="Watch my screen"
               sub={screenMem?.running
                    ? `Watching — ${screenMem.saved} activity notes saved this session. Everything stays local; only one-line summaries are kept.`
                    : "Periodically capture the screen, summarize what you're doing, and save it to memory. Off by default — this watches your screen continuously."}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <select value={String(s.screen_memory?.interval_seconds ?? 300)}
                      onChange={(e) => props.onPatch({ screen_memory: { interval_seconds: parseInt(e.target.value) } })}>
                <option value="120">every 2 min</option>
                <option value="300">every 5 min</option>
                <option value="600">every 10 min</option>
                <option value="1800">every 30 min</option>
              </select>
              <Toggle checked={screenMem?.running ?? false}
                      onChange={(v) => toggleScreenMemory(v)} />
            </div>
          </Row>
        </div>

        <div className="panel">
          <h3>Tool permissions</h3>
          <Row label="Tools enabled" sub="Let the assistant use tools at all">
            <Toggle checked={s.tools.enabled}
                    onChange={(v) => props.onPatch({ tools: { enabled: v } })} />
          </Row>
          {tools.map((t) => (
            <Row key={t.name} label={t.name} sub={t.description.slice(0, 90)}>
              {t.risk === "dangerous" || t.always_ask ? (
                <span className="sub" style={{ color: "var(--danger)" }}>always asks</span>
              ) : (
                <select
                  value={t.permission}
                  onChange={(e) => props.onPatch({ permissions: { [t.name]: e.target.value === "default" ? (t.risk === "safe" ? "always" : "ask") : e.target.value } })}
                >
                  <option value="default">default ({t.risk === "safe" ? "allow" : "ask"})</option>
                  <option value="always">always allow</option>
                  <option value="ask">ask every time</option>
                  <option value="never">never (disabled)</option>
                </select>
              )}
            </Row>
          ))}
        </div>

        <div className="panel">
          <h3>Appearance</h3>
          <Row label="Theme" sub="Color scheme for the whole app">
            <select value={s.ui.theme}
                    onChange={(e) => props.onPatch({ ui: { theme: e.target.value } })}>
              <option value="hacker">Hacker green</option>
              <option value="dark">Dark blue</option>
              <option value="light">Light</option>
              <option value="cyberpunk">Cyberpunk</option>
              <option value="system">System (dark/light)</option>
            </select>
          </Row>
          <Row label="Core design" sub="The AI visualization in the center — you can also click the core itself to cycle designs">
            <select value={s.ui.core_design ?? "orb"}
                    onChange={(e) => props.onPatch({ ui: { core_design: e.target.value } })}>
              <option value="orb">Orb (particles)</option>
              <option value="reactor">Arc reactor</option>
              <option value="halo">Halo (minimal)</option>
              <option value="nebula">Nebula swarm</option>
            </select>
          </Row>
          <Row label="Accent color" sub="Overrides the theme's color everywhere — core, buttons, glow">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="color" value={s.ui.accent || "#00ff66"}
                     style={{ width: 44, height: 30, padding: 0, border: "1px solid var(--border)",
                              borderRadius: 6, background: "none", cursor: "pointer" }}
                     onChange={(e) => props.onPatch({ ui: { accent: e.target.value } })} />
              {s.ui.accent && (
                <button className="btn" onClick={() => props.onPatch({ ui: { accent: "" } })}>
                  Reset
                </button>
              )}
            </div>
          </Row>
          <Row label="Background" sub="Theme default, Matrix rain animation, or a custom color">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <select
                value={["matrix", "world"].includes(s.ui.background) ? s.ui.background
                       : s.ui.background ? "custom" : "default"}
                onChange={(e) => {
                  const v = e.target.value;
                  props.onPatch({ ui: { background:
                    v === "matrix" || v === "world" ? v
                    : v === "custom" ? "#010804" : "" } });
                }}>
                <option value="default">Theme default</option>
                <option value="matrix">Matrix rain</option>
                <option value="world">World map (data streams)</option>
                <option value="custom">Custom color</option>
              </select>
              {s.ui.background && !["matrix", "world"].includes(s.ui.background) && (
                <input type="color" value={s.ui.background}
                       style={{ width: 44, height: 30, padding: 0, border: "1px solid var(--border)",
                                borderRadius: 6, background: "none", cursor: "pointer" }}
                       onChange={(e) => props.onPatch({ ui: { background: e.target.value } })} />
              )}
            </div>
          </Row>
          <Row label="Glass effect" sub="Translucent panels with blur">
            <Toggle checked={s.ui.glass}
                    onChange={(v) => props.onPatch({ ui: { glass: v } })} />
          </Row>
        </div>
      </div>
    </div>
  );
}

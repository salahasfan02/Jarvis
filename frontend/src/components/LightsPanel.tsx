import { useEffect, useState } from "react";
import { Lightbulb, LightbulbOff, Plug, RefreshCw, Trash2 } from "lucide-react";
import { API } from "../lib/api";
import { toast } from "./ui";

export interface LightInfo {
  id: string;
  name: string;
  model: string;
  kind: string;
  reachable?: boolean;
  on?: boolean;
  brightness?: number;
  text?: string;
}

const SWATCHES: [string, string, string][] = [
  ["warm", "Warm white", "#ffb86b"], ["white", "White", "#fff4e0"], ["cool", "Cool white", "#d6e9ff"],
  ["red", "Red", "#ff4d4d"], ["orange", "Orange", "#ff9a3c"], ["green", "Green", "#3ed36a"],
  ["blue", "Blue", "#4d7cff"], ["purple", "Purple", "#a45cff"], ["pink", "Pink", "#ff7eb6"],
];

const post = (path: string, body: unknown) =>
  fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
                           body: JSON.stringify(body) }).then((r) => r.json());

export async function controlLight(name: string, body: Record<string, unknown>) {
  const res = await post("/lights/control", { light: name, ...body }).catch((e) => ({ error: String(e) }));
  if (res.error) toast(res.error, "error");
  return res;
}

/** One light: power, brightness and colour. */
export function LightRow({ light, onChanged, compact = false }: {
  light: LightInfo; onChanged: () => void; compact?: boolean;
}) {
  const [level, setLevel] = useState(light.brightness ?? 100);
  useEffect(() => setLevel(light.brightness ?? 100), [light.brightness]);
  const Icon = light.kind === "plug" ? Plug : light.on ? Lightbulb : LightbulbOff;
  return (
    <div className="light-row">
      <div className="light-head">
        <div className={`tile-icon ${light.on ? "" : "off"}`}><Icon /></div>
        <div className="grow">
          <div className="title">{light.name}</div>
          <div className="meta">{light.reachable === false ? "Not reachable" : light.text?.replace(/^[^:]*:\s*/, "") ?? light.model}</div>
        </div>
        <label className="switch" title={light.on ? "Turn off" : "Turn on"}>
          <input type="checkbox" checked={!!light.on} disabled={light.reachable === false}
                 aria-label={`${light.name} power`}
                 onChange={(e) => controlLight(light.name, { power: e.target.checked ? "on" : "off" }).then(onChanged)} />
          <span />
        </label>
      </div>
      {!compact && light.kind !== "plug" && light.reachable !== false && (
        <>
          <input type="range" min={1} max={100} value={level} className="light-level"
                 aria-label={`${light.name} brightness`}
                 onChange={(e) => setLevel(Number(e.target.value))}
                 onMouseUp={() => controlLight(light.name, { brightness: level }).then(onChanged)}
                 onKeyUp={() => controlLight(light.name, { brightness: level }).then(onChanged)}
                 onTouchEnd={() => controlLight(light.name, { brightness: level }).then(onChanged)} />
          <div className="swatches">
            {SWATCHES.map(([value, label, color]) => (
              <button key={value} className="swatch" title={label} aria-label={label}
                      style={{ background: color }}
                      onClick={() => controlLight(light.name, { color: value }).then(onChanged)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Settings → Smart lights: connect a Tapo account, then control each light. */
export function LightsPanel() {
  const [state, setState] = useState<{ configured: boolean; lights: LightInfo[] } | null>(null);
  const [adding, setAdding] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => fetch(`${API}/lights`).then((r) => r.json()).then(setState)
    .catch(() => setState({ configured: false, lights: [] }));
  useEffect(() => { load(); }, []);

  const connect = async () => {
    setBusy(true);
    setError("");
    const res = await post("/lights/connect", { email, password }).catch((e) => ({ error: String(e) }));
    setPassword("");                       // never kept, even in the page
    setBusy(false);
    if (res.error) { setError(res.error); return; }
    setAdding(false);
    toast(`Connected ${res.lights.length} light${res.lights.length === 1 ? "" : "s"}`);
    load();
  };

  const showForm = !state?.configured || adding;
  return (
    <div className="panel" id="s-lights">
      <div className="panel-head">
        <h3>Smart lights</h3>
        {state?.configured && !adding && (
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn sm ghost" onClick={() => setAdding(true)}><RefreshCw /> Find lights again</button>
            <button className="btn sm danger" onClick={() => {
              if (!confirm("Forget your lights? You can connect them again any time.")) return;
              fetch(`${API}/lights`, { method: "DELETE" }).then(() => { toast("Lights forgotten"); load(); });
            }}><Trash2 /> Forget</button>
          </div>
        )}
      </div>
      <p className="desc">
        Tapo and Kasa lights on your Wi-Fi. Jarvis talks to them directly, so Alexa keeps working
        too. Try “lights off”, “dim the lights” or “make the bedroom light blue”.
      </p>
      {state === null && <div className="sub">Checking…</div>}
      {state && showForm && (
        <div className="lights-connect">
          <div className="form-grid">
            <label className="form-field">Tapo account email
              <input className="field" type="email" autoComplete="username" value={email}
                     onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="form-field">Tapo password
              <input className="field" type="password" autoComplete="current-password" value={password}
                     onChange={(e) => setPassword(e.target.value)}
                     onKeyDown={(e) => e.key === "Enter" && email && password && connect()} />
            </label>
          </div>
          <p className="sub" style={{ marginTop: 8 }}>
            Used once to connect to your lights and not saved — Jarvis keeps only a key for each
            light, which can't sign in to your Tapo account.
          </p>
          {error && <div className="sub" style={{ color: "var(--danger)", marginTop: 6 }}>{error}</div>}
          <div className="form-actions">
            {adding && <button className="btn ghost" onClick={() => { setAdding(false); setError(""); }}>Cancel</button>}
            <button className="btn primary" disabled={!email || !password || busy} onClick={connect}>
              {busy ? <><span className="spinner" /> Looking for your lights…</> : "Connect"}
            </button>
          </div>
        </div>
      )}
      {state?.configured && !adding && state.lights.map((l) => (
        <LightRow key={l.id} light={l} onChanged={load} />
      ))}
    </div>
  );
}

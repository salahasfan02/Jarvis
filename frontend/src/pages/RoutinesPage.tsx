import { useEffect, useState } from "react";
import { AlarmClock, Pause, Play, Trash2, Zap } from "lucide-react";
import { API } from "../lib/api";

interface Routine {
  id: string;
  name: string;
  summary: string;
  action: string;
  deliver: string;
  enabled: boolean;
  last_fired: number;
}

const DELIVER: Record<string, string> = {
  auto: "phone if connected, else this Mac", telegram: "Telegram",
  notification: "notification", speak: "spoken by Jarvis",
};

/** Things Jarvis does on its own: schedules and triggers. Created by asking
 *  ("every weekday at 8 send me my briefing"); managed here. */
export function RoutinesPage() {
  const [items, setItems] = useState<Routine[] | null>(null);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<{ name: string; text: string } | null>(null);

  const load = () => fetch(`${API}/routines`).then((r) => r.json()).then(setItems).catch(() => setItems([]));
  useEffect(() => { load(); }, []);

  const toggle = async (r: Routine) => {
    await fetch(`${API}/routines/${r.id}`, { method: "PUT", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify({ enabled: !r.enabled }) });
    load();
  };
  const remove = async (r: Routine) => {
    if (!confirm(`Delete “${r.name}”?`)) return;
    await fetch(`${API}/routines/${r.id}`, { method: "DELETE" });
    load();
  };
  const runNow = async (r: Routine) => {
    setBusy(r.id);
    try {
      const res = await fetch(`${API}/routines/${r.id}/run`, { method: "POST" }).then((x) => x.json());
      setResult({ name: r.name, text: res.result ?? res.error ?? "" });
    } finally {
      setBusy("");
      load();
    }
  };

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Routines</h1>
        <div className="sub" style={{ marginTop: -8 }}>
          Things Jarvis does on its own. Just ask — <i>“every weekday at 8 send me my briefing
          on Telegram”</i>, <i>“tell me when an email from my landlord arrives”</i>,
          <i> “remind me 10 minutes before meetings”</i>.
        </div>

        {items && items.length === 0 && (
          <div className="panel" style={{ textAlign: "center", color: "var(--text-dim)", padding: 32 }}>
            <AlarmClock className="empty-icon" />
            <div style={{ marginTop: 8 }}>No routines yet — ask Jarvis to set one up.</div>
          </div>
        )}

        {items?.map((r) => (
          <div key={r.id} className="panel" style={{ display: "flex", gap: 12, alignItems: "center",
                                                      opacity: r.enabled ? 1 : 0.55 }}>
            <AlarmClock style={{ flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>{r.name}{!r.enabled && " (paused)"}</div>
              <div className="sub">
                {r.summary}{r.action ? <> → {r.action}</> : null} · {DELIVER[r.deliver] ?? r.deliver}
                {r.last_fired ? <> · last ran {new Date(r.last_fired * 1000).toLocaleString()}</> : null}
              </div>
            </div>
            <button className="icon-btn" title="Run now" disabled={busy === r.id} onClick={() => runNow(r)}>
              <Zap />
            </button>
            <button className="icon-btn" title={r.enabled ? "Pause" : "Resume"} onClick={() => toggle(r)}>
              {r.enabled ? <Pause /> : <Play />}
            </button>
            <button className="icon-btn" title="Delete" onClick={() => remove(r)}><Trash2 /></button>
          </div>
        ))}

        {result && (
          <div className="panel" style={{ whiteSpace: "pre-wrap", fontSize: 14 }}>
            <div className="sub" style={{ marginBottom: 6 }}>{result.name} — just now</div>
            {result.text}
          </div>
        )}
      </div>
    </div>
  );
}

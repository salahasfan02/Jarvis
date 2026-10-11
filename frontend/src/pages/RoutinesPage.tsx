import { useEffect, useState } from "react";
import { AlarmClock, Pause, Pencil, Play, Plus, Trash2, Zap } from "lucide-react";
import { API } from "../lib/api";
import { EmptyState, PageHeader, toast } from "../components/ui";
import { timeAgo } from "../lib/format";

interface Routine {
  id: string;
  name: string;
  trigger: { type: string; at?: string; days?: string[]; minutes?: number; from?: string;
             subject?: string; minutes_before?: number };
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

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

interface Form {
  id?: string; name: string; trigger: string; at: string; days: string[];
  every_minutes: string; email_from: string; email_subject: string; minutes_before: string;
  action: string; deliver: string;
}
const EMPTY: Form = { name: "", trigger: "daily", at: "08:00", days: [], every_minutes: "30",
  email_from: "", email_subject: "", minutes_before: "10", action: "", deliver: "auto" };

function toForm(r: Routine): Form {
  const t = r.trigger;
  const days = t.days ?? DAYS;
  const kind = t.type === "time"
    ? (days.length === 7 ? "daily" : days.join() === DAYS.slice(0, 5).join() ? "weekdays"
       : days.join() === "sat,sun" ? "weekends" : "days")
    : t.type === "interval" ? "every" : t.type;
  return { id: r.id, name: r.name, trigger: kind, at: (t.at ?? "08:00").replace("T", " "),
    days, every_minutes: String(t.minutes ?? 30), email_from: t.from ?? "",
    email_subject: t.subject ?? "", minutes_before: String(t.minutes_before ?? 10),
    action: r.action, deliver: r.deliver };
}

/** Things Jarvis does on its own: schedules and triggers. Created by asking
 *  ("every weekday at 8 send me my briefing"); managed here. */
export function RoutinesPage() {
  const [items, setItems] = useState<Routine[] | null>(null);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<{ name: string; text: string } | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [formError, setFormError] = useState("");

  const save = async () => {
    if (!form) return;
    const { id, ...body } = form;
    const res = await fetch(`${API}/routines${id ? `/${id}` : ""}`, {
      method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((x) => x.json()).catch((e) => ({ error: String(e) }));
    if (res.error) { setFormError(res.error); return; }
    setForm(null);
    setFormError("");
    load();
  };
  const set = (patch: Partial<Form>) => form && setForm({ ...form, ...patch });

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
    toast("Routine deleted");
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
        <PageHeader title="Routines"
                    actions={!form && <button className="btn primary" onClick={() => { setForm({ ...EMPTY }); setFormError(""); }}>
                      <Plus /> New routine</button>}>
          Things Jarvis does on its own. Or just ask — “every weekday at 8 send me my briefing on
          Telegram”, “tell me when an email from my landlord arrives”.
        </PageHeader>


        {form && (
          <div className="panel routine-form">
            <h3>{form.id ? "Edit routine" : "New routine"}</h3>
            <label>Name <input className="search" value={form.name} placeholder="Morning briefing"
                               onChange={(e) => set({ name: e.target.value })} /></label>
            <label>When
              <select value={form.trigger} onChange={(e) => set({ trigger: e.target.value })}>
                <option value="daily">every day at…</option>
                <option value="weekdays">weekdays at…</option>
                <option value="weekends">weekends at…</option>
                <option value="days">on these days at…</option>
                <option value="every">every N minutes</option>
                <option value="once">once, at a date and time</option>
                <option value="email">when an email arrives</option>
                <option value="calendar">before each calendar event</option>
              </select>
            </label>
            {["daily", "weekdays", "weekends", "days"].includes(form.trigger) && (
              <label>Time <input className="search" value={form.at} placeholder="08:00 or 6pm"
                                 onChange={(e) => set({ at: e.target.value })} /></label>
            )}
            {form.trigger === "days" && (
              <div className="routine-days">
                {DAYS.map((d) => (
                  <label key={d}><input type="checkbox" checked={form.days.includes(d)}
                    onChange={(e) => set({ days: e.target.checked ? [...form.days, d]
                                                                  : form.days.filter((x) => x !== d) })} /> {d}</label>
                ))}
              </div>
            )}
            {form.trigger === "every" && (
              <label>Minutes <input className="search" type="number" min={5} value={form.every_minutes}
                                    onChange={(e) => set({ every_minutes: e.target.value })} /></label>
            )}
            {form.trigger === "once" && (
              <label>Date &amp; time <input className="search" value={form.at} placeholder="2026-10-12 15:00"
                                            onChange={(e) => set({ at: e.target.value })} /></label>
            )}
            {form.trigger === "email" && (
              <>
                <label>From <input className="search" value={form.email_from}
                                   placeholder="my landlord, Sam, or an address"
                                   onChange={(e) => set({ email_from: e.target.value })} /></label>
                <label>Subject contains <input className="search" value={form.email_subject}
                                               onChange={(e) => set({ email_subject: e.target.value })} /></label>
              </>
            )}
            {form.trigger === "calendar" && (
              <label>Minutes before <input className="search" type="number" min={1} value={form.minutes_before}
                                           onChange={(e) => set({ minutes_before: e.target.value })} /></label>
            )}
            <label>Do <input className="search" value={form.action}
                             placeholder="optional — e.g. give me my daily briefing (empty = just alert me)"
                             onChange={(e) => set({ action: e.target.value })} /></label>
            <label>Send to
              <select value={form.deliver} onChange={(e) => set({ deliver: e.target.value })}>
                {Object.entries(DELIVER).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            {formError && <div className="sub" style={{ color: "var(--danger)" }}>{formError}</div>}
            <div className="form-actions">
              <button className="btn ghost" onClick={() => setForm(null)}>Cancel</button>
              <button className="btn primary" onClick={save}>{form.id ? "Save changes" : "Create routine"}</button>
            </div>
          </div>
        )}

        <div className="panel">
          {items === null && <div className="sub">Loading…</div>}
          {items && items.length === 0 && (
            <EmptyState icon={AlarmClock} title="No routines yet"
                        action={<button className="btn" onClick={() => { setForm({ ...EMPTY }); setFormError(""); }}><Plus /> New routine</button>}>
              Ask Jarvis to set one up, or create one here.
            </EmptyState>
          )}
          {items?.map((r) => (
            <div key={r.id} className="list-row" style={{ opacity: r.enabled ? 1 : 0.55 }}>
              <div className="tile-icon"><AlarmClock /></div>
              <div className="grow">
                <div className="title">{r.name}{!r.enabled && <span className="badge" style={{ marginLeft: 8 }}>Paused</span>}</div>
                <div className="meta">
                  {r.summary}{r.action ? <> → {r.action}</> : null} · {DELIVER[r.deliver] ?? r.deliver}
                </div>
                {r.last_fired ? <div className="meta muted">Last ran {timeAgo(r.last_fired)}</div> : null}
              </div>
              <div className="actions">
                <button className="icon-btn" title="Edit" aria-label="Edit" onClick={() => { setForm(toForm(r)); setFormError(""); }}>
                  <Pencil />
                </button>
                <button className="icon-btn" title="Run now" aria-label="Run now" disabled={busy === r.id} onClick={() => runNow(r)}>
                  {busy === r.id ? <span className="spinner" /> : <Zap />}
                </button>
                <button className="icon-btn" title={r.enabled ? "Pause" : "Resume"} aria-label={r.enabled ? "Pause" : "Resume"} onClick={() => toggle(r)}>
                  {r.enabled ? <Pause /> : <Play />}
                </button>
                <button className="icon-btn" title="Delete" aria-label="Delete" onClick={() => remove(r)}><Trash2 /></button>
              </div>
            </div>
          ))}
        </div>

        {result && (
          <div className="panel">
            <div className="panel-head"><h3><Zap className="icon-sm" /> {result.name}</h3><span className="sub">just now</span></div>
            <div className="answer-card">{result.text}</div>
          </div>
        )}
      </div>
    </div>
  );
}

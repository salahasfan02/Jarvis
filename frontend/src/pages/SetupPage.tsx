import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, CircleHelp, CircleMinus, Info, RefreshCw, RotateCw } from "lucide-react";
import { API } from "../lib/api";
import { PageHeader, Ring } from "../components/ui";

interface Check {
  id: string; name: string; why: string; status: "ok" | "missing" | "ask" | "unknown" | "optional" | "restart";
  detail: string; fix: string; fix_label: string;
}

const ICON = {
  ok: <CheckCircle2 style={{ color: "var(--ok)" }} />,
  missing: <CircleAlert style={{ color: "var(--danger)" }} />,
  ask: <CircleAlert style={{ color: "var(--warn)" }} />,
  unknown: <CircleHelp style={{ color: "var(--text-3)" }} />,
  optional: <CircleMinus style={{ color: "var(--text-3)" }} />,
  restart: <RotateCw style={{ color: "var(--warn)" }} />,
};

const needsYou = (c: Check) => c.status === "missing" || c.status === "ask" || c.status === "restart";

const GROUPS: [string, (c: Check) => boolean][] = [
  ["Essentials", (c) => ["ollama", "accessibility", "screen", "whisper", "camera", "microphone"].includes(c.id)
                        || c.id.startsWith("model:")],
  ["Apps Jarvis controls", (c) => c.id.startsWith("automation:") || ["calendar", "reminders"].includes(c.id)],
  ["Optional", () => true],
];

/** Media permissions belong to this window, so the page checks them itself. */
async function mediaCheck(kind: "camera" | "microphone"): Promise<Check> {
  let state = "prompt";
  try {
    state = (await navigator.permissions.query({ name: kind as PermissionName })).state;
  } catch { /* not supported: treat as not asked */ }
  const name = kind === "camera" ? "Camera" : "Microphone";
  const why = kind === "camera" ? "“open the camera and tell me what you see”" : "the wake word and voice commands";
  return {
    id: kind, name, why,
    status: state === "granted" ? "ok" : state === "denied" ? "missing" : "ask",
    detail: state === "granted" ? "" : state === "denied" ? "Blocked for Jarvis." : "Not asked yet.",
    fix: state === "granted" ? "" : state === "denied" ? "media_settings" : "media_test",
    fix_label: state === "denied" ? "Open Settings" : "Test & allow",
  };
}

/** How many things need the user — the backend's checks plus this window's
 *  microphone and camera — for the sidebar badge and the Core notice. */
export async function countSetupProblems(): Promise<number> {
  const res = await fetch(`${API}/setup/check`).then((r) => r.json()).catch(() => ({ checks: [] }));
  const media = await Promise.all([mediaCheck("microphone"), mediaCheck("camera")]);
  return [...(res.checks as Check[]), ...media].filter(needsYou).length;
}

export function SetupPage({ onOpenSettings, onProblems }: {
  onOpenSettings: () => void;
  onProblems?: (n: number) => void;   // keeps the sidebar badge in step
}) {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [grantTo, setGrantTo] = useState("");
  const [busy, setBusy] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = async () => {
    const res = await fetch(`${API}/setup/check`).then((r) => r.json()).catch(() => ({ checks: [] }));
    setGrantTo(res.grant_to ?? "");
    const media = await Promise.all([mediaCheck("microphone"), mediaCheck("camera")]);
    setChecks([...(res.checks as Check[]), ...media]);
  };
  useEffect(() => { load(); }, []);

  const fix = async (c: Check) => {
    setBusy(c.id);
    let note = "";
    try {
      if (c.fix === "settings_page") { onOpenSettings(); return; }
      if (c.fix === "restart") {
        const bridge = (window as any).jarvisWindow;
        if (bridge?.relaunch) { await bridge.relaunch(); return; }
        note = "Quit Jarvis and open it again.";
        return;
      }
      if (c.fix === "media_test") {
        const stream = await navigator.mediaDevices.getUserMedia(
          c.id === "camera" ? { video: true } : { audio: true });
        stream.getTracks().forEach((t) => t.stop());
        note = "Allowed.";
      } else if (c.fix === "media_settings") {
        await fetch(`${API}/setup/open/${c.id}`, { method: "POST" });
        note = "Turn Jarvis on in the pane that opened, then re-check.";
      } else if (c.fix === "settings") {
        const kind = c.id.startsWith("automation:") ? "automation" : c.id;
        await fetch(`${API}/setup/open/${kind}`, { method: "POST" });
        note = "Turn Jarvis on in the pane that opened, then re-check.";
      } else {
        const res = await fetch(`${API}/setup/fix/${encodeURIComponent(c.id)}`, { method: "POST" })
          .then((r) => r.json());
        note = res.result;
      }
    } catch (e: any) {
      note = `Didn't work: ${e?.message ?? e}`;
    } finally {
      setBusy("");
      setNotes((n) => ({ ...n, [c.id]: note }));
      setTimeout(load, 1500);
    }
  };

  const problems = (checks ?? []).filter(needsYou).length;
  const ready = (checks ?? []).filter((c) => c.status === "ok").length;
  const counted = (checks ?? []).filter((c) => c.status !== "optional" && c.status !== "unknown").length;
  useEffect(() => { if (checks) onProblems?.(problems); }, [checks, problems]);
  const placed = new Set<string>();

  return (
    <div className="page">
      <div className="page-inner">
        <PageHeader title="Setup check"
                    actions={<button className="btn" onClick={() => { setChecks(null); load(); }}>
                      <RefreshCw /> Re-check</button>}>
          Everything Jarvis needs from your Mac — permissions, models and voice — and a one-click fix for each.
        </PageHeader>

        <div className="panel setup-hero">
          {checks ? <Ring done={ready} total={counted} /> : <Ring done={0} total={1} />}
          <div>
            <h3>{checks === null ? "Checking…" : problems === 0
              ? "Everything Jarvis needs is in place"
              : `${problems} thing${problems > 1 ? "s" : ""} need${problems > 1 ? "" : "s"} your attention`}</h3>
            <p>{checks === null ? "Asking macOS and the AI engine…"
              : problems === 0 ? "Jarvis can hear you, see the screen and control your apps."
              : "Fix them below — each button opens the right place or asks macOS for you."}</p>
          </div>
        </div>

        {grantTo && (
          <div className="panel grant-note">
            <Info />
            <div>
              macOS gives permissions to the app that started Jarvis — right now that's <b>{grantTo}</b>.
              In System Settings, switch on <b>{grantTo}</b>
              {grantTo !== "Jarvis" && <> (there's no “Jarvis” entry until Jarvis is installed as an
                app: <code>cd desktop &amp;&amp; npm run install-app</code>)</>}.
            </div>
          </div>
        )}
        {checks && GROUPS.map(([title, belongs]) => {
          const rows = checks.filter((c) => !placed.has(c.id) && belongs(c));
          rows.forEach((c) => placed.add(c.id));
          if (!rows.length) return null;
          return (
            <div className="panel" key={title}>
              <h3>{title}</h3>
              {rows.map((c) => (
                <div key={c.id} className="setup-row">
                  {ICON[c.status]}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="name">{c.name}</div>
                    <div className="sub">For {c.why}.{c.detail ? ` ${c.detail}` : ""}</div>
                    {notes[c.id] && <div className="sub" style={{ color: "var(--accent-text)", marginTop: 4 }}>{notes[c.id]}</div>}
                  </div>
                  {c.fix && (
                    <button className={`btn sm ${needsYou(c) ? "primary" : ""}`}
                            disabled={busy === c.id} onClick={() => fix(c)}>
                      {busy === c.id ? <span className="spinner" /> : c.fix_label}
                    </button>
                  )}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, CircleHelp, CircleMinus, RefreshCw } from "lucide-react";
import { API } from "../lib/api";

interface Check {
  id: string; name: string; why: string; status: "ok" | "missing" | "ask" | "unknown" | "optional";
  detail: string; fix: string; fix_label: string;
}

const ICON = {
  ok: <CheckCircle2 style={{ color: "var(--accent)" }} />,
  missing: <CircleAlert style={{ color: "var(--danger)" }} />,
  ask: <CircleAlert style={{ color: "#f5a623" }} />,
  unknown: <CircleHelp style={{ color: "var(--text-dim)" }} />,
  optional: <CircleMinus style={{ color: "var(--text-dim)" }} />,
};

const GROUPS: [string, (c: Check) => boolean][] = [
  ["Essentials", (c) => ["ollama", "accessibility", "screen", "whisper", "camera", "microphone"].includes(c.id)
                        || c.id.startsWith("model:")],
  ["Apps Jarvis controls", (c) => c.id.startsWith("automation:") || c.id === "calendar"],
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

export function SetupPage({ onOpenSettings }: { onOpenSettings: () => void }) {
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

  const problems = (checks ?? []).filter((c) => c.status === "missing" || c.status === "ask").length;
  const placed = new Set<string>();

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Setup check</h1>
        <div className="sub" style={{ marginTop: -8, display: "flex", gap: 12, alignItems: "center" }}>
          {checks === null ? "Checking…" : problems === 0
            ? "Everything Jarvis needs is in place."
            : `${problems} thing${problems > 1 ? "s" : ""} need${problems > 1 ? "" : "s"} your attention.`}
          <button className="btn" onClick={() => { setChecks(null); load(); }}><RefreshCw /> Re-check</button>
        </div>
        {grantTo && (
          <div className="panel" style={{ fontSize: 14 }}>
            macOS gives permissions to the app that started Jarvis — right now that's{" "}
            <b>{grantTo}</b>. In System Settings, switch on <b>{grantTo}</b>
            {grantTo !== "Jarvis" && <> (there's no “Jarvis” entry until Jarvis is installed as an
              app: <code>cd desktop &amp;&amp; npm run install-app</code>)</>}.
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
                    <div style={{ fontWeight: 600 }}>{c.name}</div>
                    <div className="sub">For {c.why}.{c.detail ? ` ${c.detail}` : ""}</div>
                    {notes[c.id] && <div className="sub" style={{ color: "var(--accent)" }}>{notes[c.id]}</div>}
                  </div>
                  {c.fix && (
                    <button className={`btn ${c.status === "missing" || c.status === "ask" ? "primary" : ""}`}
                            disabled={busy === c.id} onClick={() => fix(c)}>
                      {busy === c.id ? "…" : c.fix_label}
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

import { useEffect, useState } from "react";
import { Check, Timer, X } from "lucide-react";
import { api } from "../lib/api";

export function DevPage() {
  const [tab, setTab] = useState<"audit" | "tools" | "agents" | "plugins">("audit");
  const [audit, setAudit] = useState<any[]>([]);
  const [tools, setTools] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [plugins, setPlugins] = useState<any[]>([]);

  const refresh = () => {
    api.audit().then(setAudit).catch(() => {});
    api.tools().then(setTools).catch(() => {});
    api.agents().then(setAgents).catch(() => {});
    api.plugins().then(setPlugins).catch(() => {});
  };
  useEffect(() => {
    refresh();
    const t = setInterval(() => tab === "audit" && api.audit().then(setAudit).catch(() => {}), 4000);
    return () => clearInterval(t);
  }, [tab]);

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Developer</h1>
        <div style={{ display: "flex", gap: 8 }}>
          {(["audit", "tools", "agents", "plugins"] as const).map((t) => (
            <button key={t} className={`btn ${tab === t ? "primary" : ""}`} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </div>

        {tab === "audit" && (
          <div className="panel">
            <h3>Audit log — every tool call, confirmation and denial</h3>
            {audit.map((e, i) => (
              <div className="audit-row" key={i}>
                {new Date(e.ts * 1000).toLocaleTimeString()} <b>{e.event}</b>{" "}
                {e.tool && <b>{e.tool}</b>}{" "}
                {e.event === "chat_timing" ? <><Timer className="icon-sm" /> {timingSummary(e)}</>
                  : JSON.stringify({ ...e, ts: undefined, event: undefined, tool: undefined })}
              </div>
            ))}
            {audit.length === 0 && <div className="sub">No activity yet.</div>}
          </div>
        )}

        {tab === "tools" && (
          <div className="panel">
            <h3>{tools.length} registered tools</h3>
            {tools.map((t) => (
              <div className="row" key={t.name}>
                <div>
                  <div className="label">{t.name} <span className="sub" style={{ display: "inline" }}>· {t.risk}</span></div>
                  <div className="sub">{t.description}</div>
                </div>
                <span className="sub">{t.tags.join(", ") || "all agents"}</span>
              </div>
            ))}
          </div>
        )}

        {tab === "agents" && (
          <div className="panel">
            <h3>{agents.length} agents (auto-routed per message)</h3>
            {agents.map((a) => (
              <div className="row" key={a.id}>
                <div>
                  <div className="label">{a.name}</div>
                  <div className="sub">{a.description}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === "plugins" && (
          <div className="panel">
            <h3>Plugins</h3>
            <div className="sub" style={{ marginBottom: 10 }}>
              Drop a folder containing plugin.py into ~/.jarvis/plugins and reload.
            </div>
            {plugins.map((p) => (
              <div className="row" key={p.path}>
                <div>
                  <div className="label inline-icon">
                    {p.ok ? <Check className="icon-ok" /> : <X className="icon-bad" />} {p.name}
                  </div>
                  <div className="sub">{p.error ?? p.path}</div>
                </div>
              </div>
            ))}
            <button className="btn" style={{ marginTop: 10 }}
                    onClick={() => fetch("http://127.0.0.1:8765/api/plugins/reload", { method: "POST" }).then(refresh)}>
              Reload plugins
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** "3.2 s total · first word 2.4 s · read 4,712 tokens (11.8 s) · …" — prompt
 *  tokens are the ones Ollama had to process; a small number = cache hit. */
function timingSummary(e: any): string {
  const sec = (ms: number) => `${(ms / 1000).toFixed(1)} s`;
  const parts = [`${sec(e.total_ms ?? 0)} total`, `agent ${e.agent}`];
  if (e.first_token_ms) parts.push(`first word ${sec(e.first_token_ms)}`);
  (e.rounds ?? []).forEach((r: any, i: number) => {
    parts.push(`model call ${i + 1}: read ${r.prompt_tokens.toLocaleString()} tokens ` +
      `(${sec(r.prompt_ms)}), wrote ${r.gen_tokens} (${sec(r.gen_ms)})` +
      (r.load_ms > 500 ? `, loaded model ${sec(r.load_ms)}` : ""));
  });
  return parts.join(" · ");
}

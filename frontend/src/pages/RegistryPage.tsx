import { useEffect, useState } from "react";
import { Check, Wand2, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Gap, gapsApi } from "../lib/api";

const PRIORITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 } as const;

export function RegistryPage({ onFixIt }: { onFixIt?: (gap: Gap) => void }) {
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [reports, setReports] = useState<{ id: string }[]>([]);
  const [generating, setGenerating] = useState(false);

  const refresh = () => {
    gapsApi.list().then(setGaps).catch(() => {});
    gapsApi.reports().then(setReports).catch(() => {});
  };
  useEffect(() => { refresh(); }, []);

  const open = gaps.filter((g) => g.status === "open")
    .sort((a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] || b.count - a.count);
  const done = gaps.filter((g) => g.status === "completed");
  const dismissed = gaps.filter((g) => g.status === "dismissed");

  const stats = {
    total: open.length,
    critical: open.filter((g) => g.priority === "critical").length,
    high: open.filter((g) => g.priority === "high").length,
    topRequested: [...open].sort((a, b) => b.count - a.count).slice(0, 3),
  };

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Missing Capabilities Registry</h1>
        <div className="sub" style={{ marginTop: -8 }}>
          Every request Jarvis couldn't fulfill is logged here automatically.
          Repeats raise the priority: 1–3× low · 4–10× medium · 10+× high · 20+× critical.
        </div>

        <div className="registry-stats">
          <div className="stat-tile"><b>{stats.total}</b><span>open gaps</span></div>
          <div className="stat-tile crit"><b>{stats.critical}</b><span>critical</span></div>
          <div className="stat-tile high"><b>{stats.high}</b><span>high</span></div>
          <div className="stat-tile ok"><b>{done.length}</b><span>completed</span></div>
        </div>

        <div className="panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>Weekly Capability Report</h3>
            <div style={{ display: "flex", gap: 8 }}>
              {reports.slice(0, 3).map((r) => (
                <button key={r.id} className="btn"
                        onClick={() => gapsApi.report(r.id).then((x) => setReport(x.markdown))}>
                  {r.id}
                </button>
              ))}
              <button className="btn primary" disabled={generating}
                      onClick={async () => {
                        setGenerating(true);
                        try {
                          const r = await gapsApi.generateReport();
                          setReport(r.markdown);
                          refresh();
                        } finally { setGenerating(false); }
                      }}>
                {generating ? "Generating…" : "Generate now"}
              </button>
            </div>
          </div>
          {report && (
            <div className="report-view">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
            </div>
          )}
        </div>

        <div className="panel">
          <h3>Open gaps ({open.length})</h3>
          {open.length === 0 && (
            <div className="sub">Nothing here — either Jarvis can do everything you've asked, or you haven't stumped it yet.</div>
          )}
          {open.map((g) => (
            <div key={g.id} className="gap-row">
              <div className="gap-head" onClick={() => setExpanded(expanded === g.id ? null : g.id)}>
                <span className={`priority-badge ${g.priority}`}>{g.priority}</span>
                <span className="gap-name">{g.capability}</span>
                <span className="gap-count">{g.count}×</span>
              </div>
              {expanded === g.id && (
                <div className="gap-detail">
                  {g.user_prompt && <div><b>Last request:</b> “{g.user_prompt}”</div>}
                  {g.goal && <div><b>Goal:</b> {g.goal}</div>}
                  {g.reason && <div><b>Why it failed:</b> {g.reason}</div>}
                  {g.technical_limitation && <div><b>Technical limitation:</b> {g.technical_limitation}</div>}
                  {g.missing_tool && <div><b>Missing tool:</b> {g.missing_tool}</div>}
                  {g.missing_integration && <div><b>Missing integration:</b> {g.missing_integration}</div>}
                  {g.missing_permission && <div><b>Missing permission:</b> {g.missing_permission}</div>}
                  {g.missing_ai_capability && <div><b>Missing AI capability:</b> {g.missing_ai_capability}</div>}
                  {g.suggested_fix && <div><b>Suggested fix:</b> {g.suggested_fix}</div>}
                  <div><b>Estimated difficulty:</b> {g.difficulty || "unknown"} ·{" "}
                    <b>first seen:</b> {new Date(g.created_at * 1000).toLocaleDateString()}</div>
                  <div className="gap-actions">
                    {onFixIt && (
                      <button className="btn primary" onClick={() => onFixIt(g)}>
                        <Wand2 /> Fix it in Code Studio
                      </button>
                    )}
                    <button className="btn"
                            onClick={() => gapsApi.patch(g.id, { status: "completed" }).then(refresh)}>
                      <Check /> Mark completed
                    </button>
                    <button className="btn"
                            onClick={() => gapsApi.patch(g.id, { status: "dismissed" }).then(refresh)}>
                      Dismiss
                    </button>
                    <button className="btn danger"
                            onClick={() => gapsApi.remove(g.id).then(refresh)}>
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {done.length > 0 && (
          <div className="panel">
            <h3>Completed capabilities ({done.length})</h3>
            {done.map((g) => (
              <div key={g.id} className="gap-row completed">
                <div className="gap-head">
                  <span className="priority-badge done">done</span>
                  <span className="gap-name">{g.capability}</span>
                  <button className="btn danger" style={{ marginLeft: "auto" }}
                          onClick={() => gapsApi.remove(g.id).then(refresh)}><X className="icon-sm" /></button>
                </div>
              </div>
            ))}
          </div>
        )}

        {dismissed.length > 0 && (
          <div className="panel">
            <h3>Dismissed ({dismissed.length})</h3>
            {dismissed.map((g) => (
              <div key={g.id} className="gap-row completed">
                <div className="gap-head">
                  <span className="priority-badge">off</span>
                  <span className="gap-name">{g.capability}</span>
                  <button className="btn" style={{ marginLeft: "auto" }}
                          onClick={() => gapsApi.patch(g.id, { status: "open" }).then(refresh)}>
                    Reopen
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

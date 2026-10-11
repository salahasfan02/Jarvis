import { useEffect, useState } from "react";
import { History, RotateCcw } from "lucide-react";
import { API } from "../lib/api";

interface Entry {
  id: string;
  ts: number;
  tool: string;
  arguments: Record<string, unknown>;
  result: string;
  source: string;
  can_undo: boolean;
  undone: number;
}

const SOURCE: Record<string, string> = { app: "you", Telegram: "phone", routine: "routine" };

function summary(e: Entry): string {
  const a = e.arguments;
  const pick = ["path", "source", "destination", "title", "name", "to", "target", "query",
                "url", "text", "fact", "keys"].map((k) => a[k]).filter(Boolean);
  return pick.map(String).join(" → ").slice(0, 140);
}

/** Everything Jarvis did (not just reads), newest first, with Undo where it
 *  knows how: file moves, overwrites, trashed files, created documents and
 *  folders, saved memories/people/routines. */
export function ActivityPage() {
  const [items, setItems] = useState<Entry[] | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = () => fetch(`${API}/activity`).then((r) => r.json()).then(setItems).catch(() => setItems([]));
  useEffect(() => { load(); }, []);

  const undo = async (e: Entry) => {
    const res = await fetch(`${API}/activity/${e.id}/undo`, { method: "POST" }).then((r) => r.json());
    setNotes((n) => ({ ...n, [e.id]: res.result }));
    load();
  };

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Activity</h1>
        <div className="sub" style={{ marginTop: -8 }}>
          What Jarvis did, newest first. Undo moves files back, restores overwritten or trashed
          files, removes documents it created, and forgets what it saved. You can also just say
          <i> “undo that”</i>.
        </div>
        {items && items.length === 0 && (
          <div className="panel" style={{ textAlign: "center", color: "var(--text-dim)", padding: 32 }}>
            <History className="empty-icon" />
            <div style={{ marginTop: 8 }}>Nothing yet.</div>
          </div>
        )}
        {items?.map((e) => (
          <div key={e.id} className="panel" style={{ display: "flex", gap: 12, alignItems: "center",
                                                      opacity: e.undone ? 0.5 : 1 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>
                {e.tool.replace(/_/g, " ")}
                <span className="sub" style={{ fontWeight: 400 }}>
                  {" "}· {new Date(e.ts * 1000).toLocaleString()} · by {SOURCE[e.source] ?? e.source}
                  {e.undone ? " · undone" : ""}
                </span>
              </div>
              <div className="sub" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {summary(e) || e.result.slice(0, 140)}
              </div>
              {notes[e.id] && <div className="sub" style={{ color: "var(--accent)" }}>{notes[e.id]}</div>}
            </div>
            {e.can_undo && (
              <button className="btn" onClick={() => undo(e)}><RotateCcw /> Undo</button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

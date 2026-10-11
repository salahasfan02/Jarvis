import { useEffect, useState } from "react";
import { History, RotateCcw, Undo2 } from "lucide-react";
import { API } from "../lib/api";
import { EmptyState, PageHeader, toast } from "../components/ui";
import { stepLabel, timeAgo } from "../lib/format";

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
    const failed = /^(couldn't|no such|already|that one can't)/i.test(res.result ?? "");
    toast(failed ? res.result : "Undone", failed ? "error" : "ok");
    load();
  };

  return (
    <div className="page">
      <div className="page-inner">
        <PageHeader title="Activity">
          What Jarvis did, newest first. Undo puts files back, restores what it overwrote or
          binned, removes documents it made and forgets what it saved — or just say “undo that”.
        </PageHeader>
        <div className="panel">
          {items === null && <div className="sub">Loading…</div>}
          {items && items.length === 0 && (
            <EmptyState icon={History} title="Nothing yet">
              When Jarvis moves, creates, sends or saves something, it shows up here.
            </EmptyState>
          )}
          {items?.map((e) => (
            <div key={e.id} className="list-row" style={{ opacity: e.undone ? 0.5 : 1 }}>
              <div className="tile-icon">{e.undone ? <Undo2 /> : <History />}</div>
              <div className="grow">
                <div className="title">{stepLabel(e.tool, true)}{e.undone ? " · undone" : ""}</div>
                <div className="meta" title={summary(e) || e.result}>
                  {summary(e) || e.result.slice(0, 140)}
                </div>
                <div className="meta muted">
                  {timeAgo(e.ts)} · by {SOURCE[e.source] ?? e.source}
                </div>
                {notes[e.id] && <div className="sub" style={{ color: "var(--accent-text)" }}>{notes[e.id]}</div>}
              </div>
              {e.can_undo && (
                <button className="btn sm" onClick={() => undo(e)}><RotateCcw /> Undo</button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

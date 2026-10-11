import { useEffect, useRef, useState } from "react";
import { Brain, FileText, Pencil, Plus, Trash2, Upload } from "lucide-react";
import { API, api } from "../lib/api";
import { EmptyState, PageHeader, toast } from "../components/ui";
import { timeAgo } from "../lib/format";

export function MemoryPage() {
  const [memories, setMemories] = useState<any[]>([]);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [docs, setDocs] = useState<any[]>([]);
  const [uploading, setUploading] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => {
    api.memories().then(setMemories).catch(() => {});
    fetch(`${API}/knowledge`).then((r) => r.json()).then(setDocs).catch(() => {});
  };
  useEffect(() => { refresh(); }, []);

  const uploadFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    for (const file of Array.from(files)) {
      setUploading(`ingesting ${file.name}…`);
      try {
        const res = await fetch(
          `${API}/knowledge/upload?name=${encodeURIComponent(file.name)}`,
          { method: "POST", body: await file.arrayBuffer(),
            headers: { "Content-Type": "application/octet-stream" } });
        const r = await res.json();
        setUploading(r.error ? `Couldn't add ${file.name}: ${r.error}` : "");
      } catch (e: any) {
        setUploading(`Couldn't add ${file.name}: ${e.message}`);
      }
    }
    refresh();
  };

  const add = () => {
    if (!draft.trim()) return;
    api.addMemory(draft.trim()).then(() => { setDraft(""); refresh(); toast("Remembered"); });
  };

  return (
    <div className="page">
      <div className="page-inner">
        <PageHeader title="Memory">
          What Jarvis knows about you, and documents it can answer questions from. Everything stays on this Mac.
        </PageHeader>

        <div className="panel">
          <h3>Teach Jarvis something</h3>
          <p className="desc">Or just say “remember that …” in a chat.</p>
          <div style={{ display: "flex", gap: 8 }}>
            <input type="text" className="field" style={{ flex: 1 }}
                   placeholder="e.g. I prefer dark roast coffee" aria-label="New memory"
                   value={draft} onChange={(e) => setDraft(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && add()} />
            <button className="btn primary" disabled={!draft.trim()} onClick={add}><Plus /> Remember</button>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h3>Memories <span className="badge">{memories.length}</span></h3>
          </div>
          {memories.length === 0 && (
            <EmptyState icon={Brain} title="Nothing remembered yet">
              Jarvis also picks up lasting facts from your chats on its own.
            </EmptyState>
          )}
          {memories.map((m) => (
            <div className="list-row" key={m.id}>
              {editing === m.id ? (
                <input type="text" style={{ flex: 1 }} className="field" value={editText} autoFocus
                       aria-label="Edit memory"
                       onChange={(e) => setEditText(e.target.value)}
                       onKeyDown={(e) => {
                         if (e.key === "Enter") {
                           api.editMemory(m.id, editText).then(() => { setEditing(null); refresh(); toast("Saved"); });
                         }
                         if (e.key === "Escape") setEditing(null);
                       }} />
              ) : (
                <div className="grow">
                  <div className="title" style={{ fontWeight: 450 }}>{m.content}</div>
                  <div className="meta muted">{m.category} · {timeAgo(m.created_at)}</div>
                </div>
              )}
              <div className="actions">
                <button className="icon-btn" title="Edit" aria-label="Edit"
                        onClick={() => { setEditing(m.id); setEditText(m.content); }}><Pencil /></button>
                <button className="icon-btn" title="Forget" aria-label="Forget"
                        onClick={() => api.deleteMemory(m.id).then(() => { refresh(); toast("Forgotten"); })}><Trash2 /></button>
              </div>
            </div>
          ))}
        </div>

        <div className="panel"
             onDragOver={(e) => e.preventDefault()}
             onDrop={(e) => { e.preventDefault(); uploadFiles(e.dataTransfer.files); }}>
          <div className="panel-head">
            <h3>Documents <span className="badge">{docs.length}</span></h3>
            <button className="btn sm" onClick={() => fileRef.current?.click()}><Upload /> Add documents</button>
          </div>
          <p className="desc">Drop PDF, text or Markdown files here. Jarvis reads them and answers questions from them.</p>
          {uploading && <div className="sub"><span className="spinner" /> {uploading}</div>}
          <input ref={fileRef} type="file" multiple accept=".pdf,.txt,.md,.csv,.json,.log"
                 style={{ display: "none" }}
                 onChange={(e) => { uploadFiles(e.target.files); e.target.value = ""; }} />
          {docs.map((d) => (
            <div className="list-row" key={d.id}>
              <div className="tile-icon"><FileText /></div>
              <div className="grow">
                <div className="title">{d.name}</div>
                <div className="meta muted">{d.chunk_count} passages · {timeAgo(d.created_at)}</div>
              </div>
              <button className="icon-btn" title="Remove" aria-label="Remove document"
                      onClick={() => fetch(`${API}/knowledge/${d.id}`, { method: "DELETE" }).then(() => { refresh(); toast("Document removed"); })}>
                <Trash2 />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

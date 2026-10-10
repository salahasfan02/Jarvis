import { useEffect, useRef, useState } from "react";
import { FileText } from "lucide-react";
import { API, api } from "../lib/api";

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

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Memory</h1>
        <div className="panel">
          <h3>Add a memory</h3>
          <div style={{ display: "flex", gap: 8 }}>
            <input type="text" className="search" style={{ flex: 1 }}
                   placeholder="e.g. I prefer dark roast coffee"
                   value={draft} onChange={(e) => setDraft(e.target.value)}
                   onKeyDown={(e) => {
                     if (e.key === "Enter" && draft.trim()) {
                       api.addMemory(draft.trim()).then(() => { setDraft(""); refresh(); });
                     }
                   }} />
            <button className="btn primary"
                    onClick={() => draft.trim() && api.addMemory(draft.trim()).then(() => { setDraft(""); refresh(); })}>
              Save
            </button>
          </div>
        </div>
        <div className="panel"
             onDragOver={(e) => e.preventDefault()}
             onDrop={(e) => { e.preventDefault(); uploadFiles(e.dataTransfer.files); }}>
          <h3>Documents ({docs.length})</h3>
          <div className="sub" style={{ marginBottom: 10 }}>
            Drop PDF / text / markdown files here (or click Add). Jarvis reads them
            and can answer questions from their contents — everything stays local.
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
            <button className="btn primary" onClick={() => fileRef.current?.click()}>
              ＋ Add documents
            </button>
            <span className="sub">{uploading}</span>
            <input ref={fileRef} type="file" multiple accept=".pdf,.txt,.md,.csv,.json,.log"
                   style={{ display: "none" }}
                   onChange={(e) => { uploadFiles(e.target.files); e.target.value = ""; }} />
          </div>
          {docs.map((d) => (
            <div className="row" key={d.id}>
              <div>
                <div className="label inline-icon"><FileText className="icon-sm" /> {d.name}</div>
                <div className="sub">{d.chunk_count} passages · {new Date(d.created_at * 1000).toLocaleDateString()}</div>
              </div>
              <button className="btn danger"
                      onClick={() => fetch(`${API}/knowledge/${d.id}`, { method: "DELETE" }).then(refresh)}>
                Delete
              </button>
            </div>
          ))}
        </div>

        <div className="panel">
          <h3>{memories.length} memories</h3>
          {memories.length === 0 && (
            <div className="sub">Nothing yet. Say “remember that …” in chat, or add one above.</div>
          )}
          {memories.map((m) => (
            <div className="row" key={m.id}>
              {editing === m.id ? (
                <input type="text" style={{ flex: 1 }} className="search" value={editText}
                       autoFocus
                       onChange={(e) => setEditText(e.target.value)}
                       onKeyDown={(e) => {
                         if (e.key === "Enter") {
                           api.editMemory(m.id, editText).then(() => { setEditing(null); refresh(); });
                         }
                         if (e.key === "Escape") setEditing(null);
                       }} />
              ) : (
                <div>
                  <div className="label">{m.content}</div>
                  <div className="sub">{m.category} · {new Date(m.created_at * 1000).toLocaleDateString()}</div>
                </div>
              )}
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn" onClick={() => { setEditing(m.id); setEditText(m.content); }}>Edit</button>
                <button className="btn danger" onClick={() => api.deleteMemory(m.id).then(refresh)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

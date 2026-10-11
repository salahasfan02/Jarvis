import { useEffect, useState } from "react";
import { ArrowLeft, Check, ChevronRight, Code, Folder, FolderPlus, MessageSquare, Trash2 } from "lucide-react";
import { API } from "../lib/api";
import { EmptyState, PageHeader, toast } from "../components/ui";
import { timeAgo } from "../lib/format";

interface Project {
  id: string;
  name: string;
  description: string;
  notes: string;
  updated_at: number;
  conversations?: { id: string; title: string; mode?: string }[];
}

export function ProjectsPage({ onOpenConversation }: {
  onOpenConversation: (id: string) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);
  const [newName, setNewName] = useState("");
  const [saved, setSaved] = useState(false);

  const refresh = () =>
    fetch(`${API}/projects`).then((r) => r.json()).then(setProjects).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const open = (id: string) =>
    fetch(`${API}/projects/${id}`).then((r) => r.json()).then(setSelected).catch(() => {});

  const patch = (fields: Partial<Project>) => {
    if (!selected) return;
    setSelected({ ...selected, ...fields } as Project);
    fetch(`${API}/projects/${selected.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }).then(() => {
      setSaved(true);
      setTimeout(() => setSaved(false), 1200);
      refresh();
    });
  };

  const create = () => {
    const name = newName.trim();
    if (!name) return;
    fetch(`${API}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then((r) => r.json()).then((p) => {
      setNewName("");
      refresh();
      if (p.id) open(p.id);
    });
  };

  return (
    <div className="page">
      <div className="page-inner">
        <PageHeader title="Projects">
          A project remembers for you: its notes go into every chat assigned to it, and Jarvis
          writes new decisions there by itself.
        </PageHeader>

        {!selected && (
          <div className="panel">
            <div style={{ display: "flex", gap: 8 }}>
              <input type="text" className="field" style={{ flex: 1 }} aria-label="New project name"
                     placeholder="New project — e.g. Jarvis App, Thesis, Home Server"
                     value={newName}
                     onChange={(e) => setNewName(e.target.value)}
                     onKeyDown={(e) => e.key === "Enter" && create()} />
              <button className="btn primary" disabled={!newName.trim()} onClick={create}><FolderPlus /> Create</button>
            </div>
          </div>
        )}

        {!selected ? (
          <div className="panel">
            {projects.length === 0 && (
              <EmptyState icon={Folder} title="No projects yet">
                Create one above, then pick it in a chat's header to give that chat its memory.
              </EmptyState>
            )}
            {projects.map((p) => (
              <div className="list-row clickable" key={p.id} role="button" tabIndex={0}
                   onClick={() => open(p.id)} onKeyDown={(e) => e.key === "Enter" && open(p.id)}>
                <div className="tile-icon"><Folder /></div>
                <div className="grow">
                  <div className="title">{p.name}</div>
                  <div className="meta">{p.description || "No description"} · updated {timeAgo(p.updated_at)}</div>
                </div>
                <ChevronRight className="icon-sm muted" />
              </div>
            ))}
          </div>
        ) : (
          <div className="panel">
            <div className="panel-head">
              <h3><button className="ghost-icon" title="All projects" aria-label="All projects"
                          onClick={() => setSelected(null)}><ArrowLeft /></button>
                <Folder className="icon-sm" style={{ color: "var(--accent)" }} /> {selected.name}</h3>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {saved && <span className="sub inline-icon" style={{ color: "var(--ok)" }}><Check className="icon-sm" /> Saved</span>}
                <button className="btn danger sm"
                        onClick={() => {
                          if (window.confirm(`Delete project "${selected.name}"? Conversations stay, only the project and its notes are removed.`)) {
                            fetch(`${API}/projects/${selected.id}`, { method: "DELETE" })
                              .then(() => { setSelected(null); refresh(); toast("Project deleted"); });
                          }
                        }}><Trash2 /> Delete</button>
              </div>
            </div>

            <div className="row">
              <div style={{ width: "100%" }}>
                <div className="label" style={{ marginBottom: 4 }}>Description</div>
                <input type="text" className="field" style={{ width: "100%" }}
                       placeholder="What is this project about?"
                       value={selected.description}
                       onChange={(e) => setSelected({ ...selected, description: e.target.value })}
                       onBlur={(e) => patch({ description: e.target.value })} />
              </div>
            </div>

            <div className="row">
              <div style={{ width: "100%" }}>
                <div className="label" style={{ marginBottom: 4 }}>
                  Project memory (notes Jarvis carries into every project conversation)
                </div>
                <textarea className="field"
                          style={{ width: "100%", minHeight: 180, resize: "vertical",
                                   fontFamily: "var(--mono)", fontSize: 12.5 }}
                          placeholder="Decisions, links, conventions, progress… Jarvis appends here too."
                          value={selected.notes}
                          onChange={(e) => setSelected({ ...selected, notes: e.target.value })}
                          onBlur={(e) => patch({ notes: e.target.value })} />
              </div>
            </div>

            <h3 style={{ marginTop: 18 }}>
              Chats <span className="badge">{selected.conversations?.length ?? 0}</span>
            </h3>
            {(selected.conversations ?? []).map((c) => (
              <div className="list-row clickable" key={c.id} role="button" tabIndex={0}
                   onClick={() => onOpenConversation(c.id)}
                   onKeyDown={(e) => e.key === "Enter" && onOpenConversation(c.id)}>
                {c.mode === "code" ? <Code className="icon-sm muted" /> : <MessageSquare className="icon-sm muted" />}
                <div className="grow title" style={{ fontWeight: 450 }}>{c.title}</div>
                <ChevronRight className="icon-sm muted" />
              </div>
            ))}
            {(selected.conversations?.length ?? 0) === 0 && (
              <div className="sub" style={{ marginTop: 6 }}>None yet — in a chat, pick this project in the header.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Check, Code, Folder, MessageSquare } from "lucide-react";
import { API } from "../lib/api";

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
        <h1>Projects</h1>
        <div className="sub" style={{ marginTop: -8 }}>
          A project remembers everything: its notes are injected into every
          conversation assigned to it, and Jarvis saves new decisions there
          automatically with project_remember.
        </div>

        <div className="panel">
          <div style={{ display: "flex", gap: 8 }}>
            <input type="text" className="search" style={{ flex: 1 }}
                   placeholder="New project name — e.g. Jarvis App, Thesis, Home Server"
                   value={newName}
                   onChange={(e) => setNewName(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && create()} />
            <button className="btn primary" onClick={create}>＋ Create</button>
          </div>
        </div>

        {!selected ? (
          <div className="panel">
            <h3>{projects.length} projects</h3>
            {projects.length === 0 && (
              <div className="sub">No projects yet — create one above, then assign
                conversations to it from the Workspace header.</div>
            )}
            {projects.map((p) => (
              <div className="row" key={p.id} style={{ cursor: "pointer" }}
                   onClick={() => open(p.id)}>
                <div>
                  <div className="label inline-icon"><Folder className="icon-sm" /> {p.name}</div>
                  <div className="sub">
                    {p.description || "no description"} · updated{" "}
                    {new Date(p.updated_at * 1000).toLocaleDateString()}
                  </div>
                </div>
                <span className="sub">open ›</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 className="inline-icon" style={{ margin: 0 }}><Folder /> {selected.name}</h3>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {saved && <span className="sub inline-icon" style={{ color: "var(--ok)" }}><Check className="icon-sm" /> saved</span>}
                <button className="btn" onClick={() => setSelected(null)}>‹ All projects</button>
                <button className="btn danger"
                        onClick={() => {
                          if (window.confirm(`Delete project "${selected.name}"? Conversations stay, only the project and its notes are removed.`)) {
                            fetch(`${API}/projects/${selected.id}`, { method: "DELETE" })
                              .then(() => { setSelected(null); refresh(); });
                          }
                        }}>Delete</button>
              </div>
            </div>

            <div className="row">
              <div style={{ width: "100%" }}>
                <div className="label" style={{ marginBottom: 4 }}>Description</div>
                <input type="text" className="search" style={{ width: "100%" }}
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
                <textarea className="search"
                          style={{ width: "100%", minHeight: 180, resize: "vertical",
                                   fontFamily: "var(--mono)", fontSize: 12.5 }}
                          placeholder="Decisions, links, conventions, progress… Jarvis appends here too."
                          value={selected.notes}
                          onChange={(e) => setSelected({ ...selected, notes: e.target.value })}
                          onBlur={(e) => patch({ notes: e.target.value })} />
              </div>
            </div>

            <h3 style={{ marginTop: 14 }}>
              Conversations ({selected.conversations?.length ?? 0})
            </h3>
            {(selected.conversations ?? []).map((c) => (
              <div className="row" key={c.id} style={{ cursor: "pointer" }}
                   onClick={() => onOpenConversation(c.id)}>
                <span className="label inline-icon">
                  {c.mode === "code" ? <Code className="icon-sm" /> : <MessageSquare className="icon-sm" />}
                  {c.title}
                </span>
                <span className="sub">open ›</span>
              </div>
            ))}
            {(selected.conversations?.length ?? 0) === 0 && (
              <div className="sub">None yet — open the Workspace and pick this project
                in the header dropdown.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

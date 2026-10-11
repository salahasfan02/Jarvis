import { useEffect, useRef, useState } from "react";
import { Download, Pencil, Sparkles, Trash2, Upload } from "lucide-react";
import { Skill, skillsApi } from "../lib/api";
import { EmptyState, PageHeader, toast } from "../components/ui";

/** Custom skills = saved prompt templates. Invoke in chat with /name.
 *  {input} in the template is replaced with whatever you type after the name. */
export function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [importMsg, setImportMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => skillsApi.list().then(setSkills).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const exportSkills = () => {
    const clean = skills.map((s) => ({ name: s.name, description: s.description, template: s.template }));
    const blob = new Blob([JSON.stringify({ skills: clean }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "jarvis-skills.json";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const importFiles = async (files: FileList | File[] | null) => {
    const list = files ? Array.from(files) : [];
    for (const file of list) {
      try {
        const parsed = JSON.parse(await file.text());
        const items = Array.isArray(parsed) ? parsed : parsed.skills;
        const r = await skillsApi.import(items);
        setImportMsg(`Imported ${r.added.length}${r.skipped.length ? `, skipped ${r.skipped.length} duplicate(s)` : ""}.`);
      } catch (e: any) {
        setImportMsg(`Couldn't import ${file.name}: ${e.message}`);
      }
    }
    refresh();
    setTimeout(() => setImportMsg(""), 5000);
  };

  const save = () => {
    if (!name.trim() || !template.trim()) return;
    const body = { name: name.trim(), description: description.trim(), template: template.trim() };
    const p = editing
      ? skillsApi.update(editing, body)
      : skillsApi.create(body);
    p.then(() => { toast(editing ? "Skill saved" : "Skill added"); setName(""); setDescription(""); setTemplate(""); setEditing(null); refresh(); });
  };

  const edit = (s: Skill) => {
    setEditing(s.id); setName(s.name); setDescription(s.description); setTemplate(s.template);
  };

  return (
    <div className="page"
         onDragOver={(e) => e.preventDefault()}
         onDrop={(e) => { e.preventDefault(); importFiles(e.dataTransfer.files); }}>
      <div className="page-inner">
        <PageHeader title="Skills" actions={<>
          <button className="btn" onClick={() => fileRef.current?.click()}><Upload /> Import</button>
          <button className="btn" disabled={skills.length === 0} onClick={exportSkills}><Download /> Export</button>
          <input ref={fileRef} type="file" accept=".json,application/json" multiple
                 style={{ display: "none" }}
                 onChange={(e) => { importFiles(e.target.files); e.target.value = ""; }} />
        </>}>
          Prompts you use often. In a chat, type <code>/name</code> and your text — {"{input}"} in the
          template is replaced with whatever you type after the name.
        </PageHeader>
        {importMsg && <div className="sub" style={{ color: "var(--accent-text)" }}>{importMsg}</div>}

        <div className="panel">
          <h3>{editing ? "Edit skill" : "New skill"}</h3>
          <div className="form-grid" style={{ marginTop: 10 }}>
            <label className="form-field">Name — you'll type /name
              <input type="text" className="field" value={name} placeholder="email"
                     onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="form-field">Description
              <input type="text" className="field" value={description} placeholder="Draft a professional email"
                     onChange={(e) => setDescription(e.target.value)} />
            </label>
            <label className="form-field full">Template — use {"{input}"} where your text goes
              <textarea className="field" style={{ minHeight: 110, resize: "vertical" }}
                        placeholder={"Write a concise, professional email.\nContext: {input}"}
                        value={template} onChange={(e) => setTemplate(e.target.value)} />
            </label>
          </div>
          <div className="form-actions" style={{ marginTop: 12 }}>
            {editing && <button className="btn ghost" onClick={() => {
              setEditing(null); setName(""); setDescription(""); setTemplate("");
            }}>Cancel</button>}
            <button className="btn primary" disabled={!name.trim() || !template.trim()} onClick={save}>
              {editing ? "Save changes" : "Add skill"}</button>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><h3>Your skills <span className="badge">{skills.length}</span></h3></div>
          {skills.length === 0 && (
            <EmptyState icon={Sparkles} title="No skills yet">Create one above, or drop a .json skill pack here.</EmptyState>
          )}
          {skills.map((s) => (
            <div className="list-row" key={s.id}>
              <div className="tile-icon"><Sparkles /></div>
              <div className="grow">
                <div className="title"><code>/{s.name}</code> <span className="muted" style={{ fontWeight: 400 }}>— {s.description || "no description"}</span></div>
                <div className="meta">{s.template.replace(/\n/g, " ")}</div>
              </div>
              <div className="actions">
                <button className="icon-btn" title="Edit" aria-label="Edit" onClick={() => edit(s)}><Pencil /></button>
                <button className="icon-btn" title="Delete" aria-label="Delete"
                        onClick={() => skillsApi.remove(s.id).then(() => { refresh(); toast("Skill deleted"); })}><Trash2 /></button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

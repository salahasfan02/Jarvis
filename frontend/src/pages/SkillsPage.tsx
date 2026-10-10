import { useEffect, useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { Skill, skillsApi } from "../lib/api";

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
    p.then(() => { setName(""); setDescription(""); setTemplate(""); setEditing(null); refresh(); });
  };

  const edit = (s: Skill) => {
    setEditing(s.id); setName(s.name); setDescription(s.description); setTemplate(s.template);
  };

  return (
    <div className="page"
         onDragOver={(e) => e.preventDefault()}
         onDrop={(e) => { e.preventDefault(); importFiles(e.dataTransfer.files); }}>
      <div className="page-inner">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <h1>Skills</h1>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" onClick={() => fileRef.current?.click()}><Upload /> Import</button>
            <button className="btn" disabled={skills.length === 0} onClick={exportSkills}><Download /> Export</button>
            <input ref={fileRef} type="file" accept=".json,application/json" multiple
                   style={{ display: "none" }}
                   onChange={(e) => { importFiles(e.target.files); e.target.value = ""; }} />
          </div>
        </div>
        <div className="sub" style={{ marginTop: -8 }}>
          Save prompts you use often. In the Workspace, type <code>/name</code> and
          your text — Jarvis expands the template (<code>{"{input}"}</code> is replaced
          with what you type after the name), so you never re-write the same prompt.
          Import/export or drag a <code>.json</code> skill pack here to share.
        </div>
        {importMsg && <div className="sub" style={{ color: "var(--accent)" }}>{importMsg}</div>}

        <div className="panel">
          <h3>{editing ? "Edit skill" : "New skill"}</h3>
          <div className="row">
            <div className="label">Name <span className="sub">(used as /name)</span></div>
            <input type="text" value={name} placeholder="email"
                   onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="row">
            <div className="label">Description</div>
            <input type="text" value={description} placeholder="Draft a professional email"
                   onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="row" style={{ borderBottom: "none" }}>
            <div style={{ width: "100%" }}>
              <div className="label" style={{ marginBottom: 4 }}>
                Template <span className="sub">— use {"{input}"} where your text should go</span>
              </div>
              <textarea className="search" style={{ width: "100%", minHeight: 120, resize: "vertical" }}
                        placeholder={"Write a concise, professional email.\nContext: {input}"}
                        value={template} onChange={(e) => setTemplate(e.target.value)} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 10 }}>
            {editing && <button className="btn" onClick={() => {
              setEditing(null); setName(""); setDescription(""); setTemplate("");
            }}>Cancel</button>}
            <button className="btn primary" onClick={save}>{editing ? "Save changes" : "Add skill"}</button>
          </div>
        </div>

        <div className="panel">
          <h3>{skills.length} skills</h3>
          {skills.length === 0 && <div className="sub">No skills yet — create one above.</div>}
          {skills.map((s) => (
            <div className="row" key={s.id}>
              <div>
                <div className="label"><code>/{s.name}</code> — {s.description || "no description"}</div>
                <div className="sub" style={{ maxWidth: 520, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {s.template.replace(/\n/g, " ")}
                </div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn" onClick={() => edit(s)}>Edit</button>
                <button className="btn danger" onClick={() => skillsApi.remove(s.id).then(refresh)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

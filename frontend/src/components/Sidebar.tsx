import { useState } from "react";
import {
  AlarmClock, Brain, Camera, Code, Folder, History, ListChecks, LucideIcon, MessagesSquare, Orbit,
  PanelLeftClose, Settings, Sparkles, SquareTerminal, X,
} from "lucide-react";
import { Conversation } from "../lib/api";

export type Page = "core" | "chat" | "code" | "projects" | "camera"
  | "skills" | "settings" | "memory" | "dev" | "registry" | "routines" | "activity";

const NAV: { id: Page; icon: LucideIcon; label: string }[] = [
  { id: "core", icon: Orbit, label: "Core" },
  { id: "chat", icon: MessagesSquare, label: "Workspace" },
  { id: "projects", icon: Folder, label: "Projects" },
  { id: "skills", icon: Sparkles, label: "Skills" },
  { id: "camera", icon: Camera, label: "Camera" },
  { id: "routines", icon: AlarmClock, label: "Routines" },
  { id: "activity", icon: History, label: "Activity" },
  { id: "memory", icon: Brain, label: "Memory" },
  { id: "registry", icon: ListChecks, label: "Capabilities" },
  { id: "dev", icon: SquareTerminal, label: "Developer" },
  { id: "settings", icon: Settings, label: "Settings" },
];

export function Sidebar(props: {
  conversations: Conversation[];
  activeId: string | null;
  page: Page;
  busy: boolean;
  ollamaUp: boolean;
  model: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onSearch: (q: string) => void;
  onPage: (p: Page) => void;
}) {
  const [query, setQuery] = useState("");

  if (props.collapsed) {
    return (
      <div className="sidebar collapsed">
        <div className="brand" title="Expand" onClick={props.onToggleCollapse}
             style={{ cursor: "pointer", justifyContent: "center" }}>
          <div className={`orb ${props.busy ? "thinking" : ""}`} />
        </div>
        {NAV.map((n) => (
          <button key={n.id} title={n.label}
                  className={`nav-icon ${props.page === n.id ? "active" : ""}`}
                  onClick={() => props.onPage(n.id)}>
            <n.icon />
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <div className="statusline" style={{ justifyContent: "center" }}>
          <span className={`dot ${props.ollamaUp ? "up" : ""}`} />
        </div>
      </div>
    );
  }

  return (
    <div className="sidebar">
      <div className="brand">
        <div className={`orb ${props.busy ? "thinking" : ""}`} />
        Jarvis
        <button className="collapse-btn" title="Collapse" onClick={props.onToggleCollapse}>
          <PanelLeftClose />
        </button>
      </div>

      <div className="nav" style={{ borderTop: "none", paddingTop: 0 }}>
        {NAV.map((n) => (
          <button key={n.id} className={props.page === n.id ? "active" : ""}
                  onClick={() => props.onPage(n.id)}>
            <n.icon /> {n.label}
          </button>
        ))}
      </div>

      <button className="new-chat" onClick={props.onNewChat}>＋ New chat</button>
      <input
        className="search"
        placeholder="Search conversations…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          props.onSearch(e.target.value);
        }}
      />
      <div className="conv-list">
        {props.conversations.map((c) => (
          <div
            key={c.id}
            className={`conv-item ${c.id === props.activeId && props.page === "chat" ? "active" : ""}`}
            onClick={() => props.onSelect(c.id)}
          >
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
              {c.mode === "code" && <Code className="icon-sm" style={{ marginRight: 5 }} />}{c.title}
            </span>
            <button
              className="del"
              title="Delete conversation"
              onClick={(e) => {
                e.stopPropagation();
                props.onDelete(c.id);
              }}
            >
              <X className="icon-sm" />
            </button>
          </div>
        ))}
      </div>

      <div className="statusline">
        <span className={`dot ${props.ollamaUp ? "up" : ""}`} />
        {props.ollamaUp ? props.model : "Ollama offline"}
      </div>
    </div>
  );
}

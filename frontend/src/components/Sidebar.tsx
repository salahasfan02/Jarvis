import { useEffect, useState } from "react";
import {
  AlarmClock, Brain, Camera, Code, Folder, History, ListChecks, LucideIcon, MessageSquare,
  MessagesSquare, Orbit, PanelLeftClose, PanelLeftOpen, Plus, Search, Settings, ShieldCheck,
  Sparkles, SquareTerminal, Trash2, X,
} from "lucide-react";
import { Conversation } from "../lib/api";

export type Page = "core" | "chat" | "code" | "projects" | "camera"
  | "skills" | "settings" | "memory" | "dev" | "registry" | "routines" | "activity" | "setup";

export const NAV: { id: Page; icon: LucideIcon; label: string; group: "" | "Assistant" | "System" }[] = [
  { id: "core", icon: Orbit, label: "Core", group: "" },
  { id: "chat", icon: MessagesSquare, label: "Chat", group: "" },
  { id: "projects", icon: Folder, label: "Projects", group: "Assistant" },
  { id: "routines", icon: AlarmClock, label: "Routines", group: "Assistant" },
  { id: "memory", icon: Brain, label: "Memory", group: "Assistant" },
  { id: "skills", icon: Sparkles, label: "Skills", group: "Assistant" },
  { id: "camera", icon: Camera, label: "Camera", group: "Assistant" },
  { id: "activity", icon: History, label: "Activity", group: "System" },
  { id: "registry", icon: ListChecks, label: "Capabilities", group: "System" },
  { id: "setup", icon: ShieldCheck, label: "Setup check", group: "System" },
  { id: "dev", icon: SquareTerminal, label: "Developer", group: "System" },
  { id: "settings", icon: Settings, label: "Settings", group: "System" },
];

const isMac = typeof navigator !== "undefined" && /Mac/.test(navigator.platform);
export const MOD = isMac ? "⌘" : "Ctrl";

export function Sidebar(props: {
  conversations: Conversation[];
  activeId: string | null;
  page: Page;
  busy: boolean;
  ollamaUp: boolean;
  model: string;
  assistantName: string;
  collapsed: boolean;
  setupProblems: number;
  onToggleCollapse: () => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onPage: (p: Page) => void;
  onOpenPalette: () => void;
}) {
  // Deleting takes two clicks: the × turns into a red bin for a few seconds.
  const [arming, setArming] = useState<string | null>(null);
  useEffect(() => {
    if (!arming) return;
    const t = setTimeout(() => setArming(null), 3000);
    return () => clearTimeout(t);
  }, [arming]);

  const item = (n: typeof NAV[number]) => (
    <button key={n.id} title={props.collapsed ? n.label : undefined} aria-label={n.label}
            className={`side-item ${props.page === n.id ? "active" : ""}`}
            aria-current={props.page === n.id ? "page" : undefined}
            onClick={() => props.onPage(n.id)}>
      <n.icon />
      {!props.collapsed && <span>{n.label}</span>}
      {n.id === "setup" && props.setupProblems > 0 && (
        <span className="badge warn" title={`${props.setupProblems} to fix`}>{props.setupProblems}</span>
      )}
    </button>
  );

  if (props.collapsed) {
    return (
      <nav className="sidebar collapsed" aria-label="Main">
        <button className="side-brand ghost-icon" style={{ width: 40, height: 40 }}
                title="Expand sidebar" aria-label="Expand sidebar" onClick={props.onToggleCollapse}>
          <div className={`orb ${props.busy ? "thinking" : ""}`} />
        </button>
        <button className="side-item" title={`Search (${MOD}K)`} aria-label="Search"
                onClick={props.onOpenPalette}><Search /></button>
        <button className="side-item" title="New chat" aria-label="New chat"
                onClick={props.onNewChat}><Plus /></button>
        <div className="side-gap" />
        {NAV.map(item)}
        <div style={{ flex: 1 }} />
        <button className="ghost-icon" title="Expand sidebar" aria-label="Expand sidebar"
                onClick={props.onToggleCollapse}><PanelLeftOpen /></button>
        <span className={`dot ${props.ollamaUp ? "up" : ""}`} style={{ margin: "10px 0 4px" }}
              title={props.ollamaUp ? props.model : "AI engine offline"} />
      </nav>
    );
  }

  const groups: ("" | "Assistant" | "System")[] = ["", "Assistant", "System"];
  return (
    <nav className="sidebar" aria-label="Main">
      <div className="side-brand">
        <div className={`orb ${props.busy ? "thinking" : ""}`} />
        <span className="grow">{props.assistantName}</span>
        <button className="ghost-icon" title="Collapse sidebar" aria-label="Collapse sidebar"
                onClick={props.onToggleCollapse}><PanelLeftClose /></button>
      </div>

      <button className="side-search" onClick={props.onOpenPalette}>
        <Search /> <span className="grow">Search or jump to…</span> <kbd>{MOD}K</kbd>
      </button>

      <div className="side-nav">
        {groups.map((g) => (
          <div key={g || "main"}>
            {g && <div className="side-label">{g}</div>}
            {NAV.filter((n) => n.group === g).map(item)}
          </div>
        ))}
      </div>

      <div className="side-recent">
        <div className="side-label">
          Recent chats
          <button className="ghost-icon" style={{ width: 22, height: 22 }} title="New chat"
                  aria-label="New chat" onClick={props.onNewChat}><Plus /></button>
        </div>
        <div className="recent-list">
          {props.conversations.length === 0 && <div className="recent-empty">No chats yet</div>}
          {props.conversations.slice(0, 40).map((c) => (
            <div key={c.id} role="button" tabIndex={0}
                 className={`recent-item ${c.id === props.activeId && props.page === "chat" ? "active" : ""}`}
                 onClick={() => props.onSelect(c.id)}
                 onKeyDown={(e) => e.key === "Enter" && props.onSelect(c.id)}>
              {c.mode === "code" ? <Code /> : <MessageSquare />}
              <span className="title">{c.title}</span>
              <button className="del" aria-label={arming === c.id ? "Confirm delete" : "Delete chat"}
                      title={arming === c.id ? "Click again to delete" : "Delete chat"}
                      style={arming === c.id ? { opacity: 1, color: "var(--danger)" } : undefined}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (arming === c.id) { setArming(null); props.onDelete(c.id); }
                        else setArming(c.id);
                      }}>
                {arming === c.id ? <Trash2 className="icon-sm" /> : <X className="icon-sm" />}
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="side-footer" title={props.ollamaUp ? "AI engine running" : "Ollama isn't running"}>
        <span className={`dot ${props.ollamaUp ? "up" : ""}`} />
        <span className="model">{props.ollamaUp ? props.model : "AI engine offline"}</span>
      </div>
    </nav>
  );
}

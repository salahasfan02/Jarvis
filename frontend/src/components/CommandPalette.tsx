import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, CornerDownLeft, LucideIcon, MessageSquare, Search, Sparkles } from "lucide-react";
import { api, Conversation } from "../lib/api";
import { NAV, Page } from "./Sidebar";

export interface PaletteAction {
  id: string;
  label: string;
  icon: LucideIcon;
  hint?: string;
  run: () => void;
}

type Item = { key: string; group: string; label: string; icon: LucideIcon; hint?: string; run: () => void };

/** ⌘K: jump to a page or chat, run an action, or ask Jarvis straight away. */
export function CommandPalette(props: {
  onClose: () => void;
  conversations: Conversation[];
  actions: PaletteAction[];
  assistantName: string;
  onPage: (p: Page) => void;
  onOpenConversation: (id: string) => void;
  onAsk: (text: string) => void;
}) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Conversation[] | null>(null);   // server search (titles + text)
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const query = q.trim();
    if (query.length < 2) { setFound(null); return; }
    const t = setTimeout(() => api.conversations(query).then(setFound).catch(() => setFound(null)), 160);
    return () => clearTimeout(t);
  }, [q]);

  const items = useMemo<Item[]>(() => {
    const query = q.trim().toLowerCase();
    const match = (s: string) => !query || s.toLowerCase().includes(query);
    const out: Item[] = [];
    if (query) {
      out.push({ key: "ask", group: "", label: `Ask ${props.assistantName}: “${q.trim()}”`, icon: Sparkles,
                 hint: "Enter", run: () => props.onAsk(q.trim()) });
    }
    for (const a of props.actions) {
      if (match(a.label)) out.push({ key: `a:${a.id}`, group: "Actions", label: a.label, icon: a.icon, hint: a.hint, run: a.run });
    }
    for (const n of NAV) {
      if (match(n.label)) out.push({ key: `p:${n.id}`, group: "Go to", label: n.label, icon: n.icon, run: () => props.onPage(n.id) });
    }
    const convs = found ?? props.conversations.filter((c) => match(c.title));
    for (const c of convs.slice(0, query ? 12 : 6)) {
      out.push({ key: `c:${c.id}`, group: query ? "Chats" : "Recent chats", label: c.title, icon: MessageSquare,
                 run: () => props.onOpenConversation(c.id) });
    }
    return out;
  }, [q, found, props.actions, props.conversations, props.assistantName]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const choose = (it: Item | undefined) => {
    if (!it) return;
    props.onClose();
    it.run();
  };

  let lastGroup = "";
  return (
    <div className="palette-backdrop" onMouseDown={props.onClose}>
      <div className="palette" role="dialog" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}>
        <div className="palette-input">
          <Search />
          <input autoFocus value={q} placeholder="Search pages, chats and actions — or ask anything…"
                 onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => {
                   if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, items.length - 1)); }
                   else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
                   else if (e.key === "Enter") { e.preventDefault(); choose(items[active]); }
                   else if (e.key === "Escape") { e.preventDefault(); props.onClose(); }
                 }} />
        </div>
        <div className="palette-list" ref={listRef} role="listbox">
          {items.length === 0 && <div className="palette-empty">Nothing matches “{q}”</div>}
          {items.map((it, i) => {
            const header = it.group && it.group !== lastGroup ? it.group : "";
            lastGroup = it.group;
            return (
              <div key={it.key}>
                {header && <div className="palette-group">{header}</div>}
                <button data-i={i} role="option" aria-selected={i === active}
                        className={`palette-item ${i === active ? "active" : ""}`}
                        onMouseMove={() => setActive(i)} onClick={() => choose(it)}>
                  <it.icon /> <span>{it.label}</span>
                  {it.hint ? <span className="hint">{it.hint}</span>
                    : i === active ? <span className="hint"><ArrowRight className="icon-xs" /></span> : null}
                </button>
              </div>
            );
          })}
        </div>
        <div className="palette-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
          <span><kbd><CornerDownLeft className="icon-xs" /></kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}

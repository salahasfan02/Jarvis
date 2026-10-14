import { CSSProperties, PointerEvent as ReactPointerEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Bot, Brain, ChartNoAxesColumn, Check, Code, Crown, Globe, LayoutTemplate, LocateFixed, LucideIcon,
  Megaphone, Minus, PenLine, Palette, Plus, Search, Server, Shield, TriangleAlert, X, FileCode,
} from "lucide-react";
import {
  canLink, fitView, linkMid, linkPath, NODE_H, NODE_W, portIn, portOut, reachable, RunState, Team, TeamAgent,
} from "../lib/teams";

export const AGENT_ICONS: Record<string, LucideIcon> = {
  crown: Crown, server: Server, layout: LayoutTemplate, megaphone: Megaphone, search: Search,
  pen: PenLine, bot: Bot, code: Code, chart: ChartNoAxesColumn, palette: Palette, brain: Brain,
  shield: Shield,
};

export type Selection = { kind: "agent"; id: string } | { kind: "link"; from: string; to: string } | null;

type View = { x: number; y: number; zoom: number };

/** Keep getting this pointer's moves while it's held down (even off the element). */
function capture(e: ReactPointerEvent<Element>) {
  try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* not a live pointer */ }
}
const MIN_ZOOM = 0.3, MAX_ZOOM = 2;
const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

/** The team as a picture you can work on: drag agents around, drag from an
 *  agent's right-hand dot to another agent to let it hand that one work,
 *  double-click empty space for a new agent. Scroll to pan, pinch or ⌘-scroll
 *  to zoom. While a team runs, each agent shows what it's doing and the link
 *  work is moving along lights up. */
export function TeamCanvas(props: {
  team: Team;
  run: RunState | null;
  selected: Selection;
  onSelect: (sel: Selection) => void;
  onMoveAgent: (id: string, x: number, y: number, done: boolean) => void;
  onLink: (from: string, to: string) => void;
  onAddAgent: (x: number, y: number) => void;
  onDelete: (sel: Selection) => void;
}) {
  const { team, run, selected } = props;
  const viewport = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>({ x: 40, y: 40, zoom: 1 });
  const viewRef = useRef(view);
  viewRef.current = view;
  const pan = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const drag = useRef<{ id: string; x: number; y: number; ox: number; oy: number; moved: boolean } | null>(null);
  const [connecting, setConnecting] = useState<{ from: string; x: number; y: number; over: string } | null>(null);

  const toWorld = (clientX: number, clientY: number) => {
    const r = viewport.current!.getBoundingClientRect();
    const v = viewRef.current;
    return { x: (clientX - r.left - v.x) / v.zoom, y: (clientY - r.top - v.y) / v.zoom };
  };

  const fit = useCallback(() => {
    const el = viewport.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setView(fitView(team.agents, r.width, r.height));
  }, [team.agents]);

  // A different team: show all of it.
  useLayoutEffect(() => { fit(); }, [team.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  // The selected agent (a new one, or one picked from the list) is brought into view.
  const selectedAgent = selected?.kind === "agent" ? selected.id : "";
  useEffect(() => {
    const a = team.agents.find((x) => x.id === selectedAgent);
    const el = viewport.current;
    if (!a || !el) return;
    const r = el.getBoundingClientRect(), v = viewRef.current, pad = 24;
    const left = a.x * v.zoom + v.x, top = a.y * v.zoom + v.y;
    const right = left + NODE_W * v.zoom, bottom = top + NODE_H * v.zoom;
    const dx = left < pad ? pad - left : right > r.width - pad ? r.width - pad - right : 0;
    const dy = top < pad ? pad - top : bottom > r.height - pad ? r.height - pad - bottom : 0;
    if (dx || dy) setView((cur) => ({ ...cur, x: cur.x + dx, y: cur.y + dy }));
  }, [selectedAgent]);   // eslint-disable-line react-hooks/exhaustive-deps

  const zoomAt = (clientX: number, clientY: number, factor: number) => {
    const r = viewport.current!.getBoundingClientRect();
    setView((v) => {
      const zoom = clampZoom(v.zoom * factor);
      const px = clientX - r.left, py = clientY - r.top;
      return { zoom, x: px - ((px - v.x) / v.zoom) * zoom, y: py - ((py - v.y) / v.zoom) * zoom };
    });
  };

  // Wheel: pinch / ⌘-scroll zooms, plain scroll pans (needs a non-passive listener).
  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.01));
      else setView((v) => ({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY }));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onBackgroundDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest(".tc-tools")) return;
    props.onSelect(null);
    pan.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    capture(e);
  };
  const onBackgroundMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const p = pan.current;
    if (p) setView((v) => ({ ...v, x: p.vx + e.clientX - p.x, y: p.vy + e.clientY - p.y }));
  };
  const onBackgroundUp = () => { pan.current = null; };

  const onNodeDown = (e: ReactPointerEvent<HTMLDivElement>, a: TeamAgent) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest(".tc-port")) return;
    e.stopPropagation();
    props.onSelect({ kind: "agent", id: a.id });
    drag.current = { id: a.id, x: e.clientX, y: e.clientY, ox: a.x, oy: a.y, moved: false };
    capture(e);
  };
  const onNodeMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const dx = (e.clientX - d.x) / view.zoom, dy = (e.clientY - d.y) / view.zoom;
    if (!d.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
    d.moved = true;
    props.onMoveAgent(d.id, Math.round(d.ox + dx), Math.round(d.oy + dy), false);
  };
  const onNodeUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    drag.current = null;
    if (d?.moved) {
      props.onMoveAgent(d.id, Math.round(d.ox + (e.clientX - d.x) / view.zoom),
                        Math.round(d.oy + (e.clientY - d.y) / view.zoom), true);
    }
  };

  const agentAt = (clientX: number, clientY: number): string => {
    const el = document.elementFromPoint(clientX, clientY)?.closest("[data-agent]") as HTMLElement | null;
    return el?.dataset.agent ?? "";
  };
  // Kept in a ref too: a quick flick can end before React has re-rendered.
  const linking = useRef<{ from: string; x: number; y: number; over: string } | null>(null);
  const setLinking = (next: { from: string; x: number; y: number; over: string } | null) => {
    linking.current = next;
    setConnecting(next);
  };
  const onPortDown = (e: ReactPointerEvent<HTMLDivElement>, a: TeamAgent) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const p = toWorld(e.clientX, e.clientY);
    setLinking({ from: a.id, x: p.x, y: p.y, over: "" });
    capture(e);
  };
  const onPortMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const cur = linking.current;
    if (!cur) return;
    const p = toWorld(e.clientX, e.clientY);
    const over = agentAt(e.clientX, e.clientY);
    setLinking({ ...cur, x: p.x, y: p.y, over: over !== cur.from ? over : "" });
  };
  const onPortUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const cur = linking.current;
    if (!cur) return;
    const target = agentAt(e.clientX, e.clientY);
    if (target && canLink(team, cur.from, target)) props.onLink(cur.from, target);
    setLinking(null);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.key === "Delete" || e.key === "Backspace") && selected) {
      e.preventDefault();
      props.onDelete(selected);
    }
    if (e.key === "Escape") props.onSelect(null);
  };

  const byId = useMemo(() => new Map(team.agents.map((a) => [a.id, a])), [team.agents]);
  const live = useMemo(() => reachable(team), [team]);
  const used = useMemo(() => new Set((run?.handoffs ?? []).map((h) => `${h.from}>${h.to}`)), [run?.handoffs]);

  // The SVG covers every agent (and a link being drawn), so links stay clickable anywhere.
  const box = useMemo(() => {
    const xs = team.agents.flatMap((a) => [a.x, a.x + NODE_W]).concat(connecting ? [connecting.x] : []);
    const ys = team.agents.flatMap((a) => [a.y, a.y + NODE_H]).concat(connecting ? [connecting.y] : []);
    const minX = Math.min(0, ...xs) - 400, minY = Math.min(0, ...ys) - 400;
    return { x: minX, y: minY, w: Math.max(...xs, 0) + 400 - minX, h: Math.max(...ys, 0) + 400 - minY };
  }, [team.agents, connecting]);

  const grid = 24 * view.zoom;
  const style: CSSProperties = {
    backgroundSize: `${grid}px ${grid}px`,
    backgroundPosition: `${view.x}px ${view.y}px`,
  };

  return (
    <div className={`tc ${connecting ? "connecting" : ""}`} ref={viewport} style={style} tabIndex={0}
         role="application" aria-label="Team canvas"
         onPointerDown={onBackgroundDown} onPointerMove={onBackgroundMove} onPointerUp={onBackgroundUp}
         onPointerCancel={onBackgroundUp} onKeyDown={onKeyDown}
         onDoubleClick={(e) => {
           if ((e.target as HTMLElement).closest(".tc-node, .tc-tools, .tc-link-x, .hit")) return;
           const p = toWorld(e.clientX, e.clientY);
           props.onAddAgent(p.x - NODE_W / 2, p.y - 30);
         }}>
      <div className="tc-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` }}>
        <svg className="tc-links" style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
             viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`}>
          <defs>
            <marker id="tc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
                    orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" />
            </marker>
          </defs>
          {team.links.map((l) => {
            const a = byId.get(l.from), b = byId.get(l.to);
            if (!a || !b) return null;
            const d = linkPath(portOut(a), portIn(b));
            const isSel = selected?.kind === "link" && selected.from === l.from && selected.to === l.to;
            const active = run?.active && run.active.from === l.from && run.active.to === l.to;
            const color = b.color || "var(--accent)";
            return (
              <g key={`${l.from}>${l.to}`}
                 className={`tc-link ${isSel ? "selected" : ""} ${active ? "active" : ""} ${used.has(`${l.from}>${l.to}`) ? "used" : ""}`}
                 style={{ "--agent": color } as CSSProperties}>
                <path className="hit" d={d}
                      onPointerDown={(e) => { e.stopPropagation(); props.onSelect({ kind: "link", from: l.from, to: l.to }); }} />
                <path className="line" d={d} markerEnd="url(#tc-arrow)" />
                {active && (
                  <circle r="6" className="pulse">
                    <animateMotion dur="1.4s" repeatCount="indefinite" path={d}
                                   {...(run?.active?.back ? { keyPoints: "1;0", keyTimes: "0;1", calcMode: "linear" } : {})} />
                  </circle>
                )}
              </g>
            );
          })}
          {connecting && byId.get(connecting.from) && (
            <path className="tc-link-temp"
                  d={linkPath(portOut(byId.get(connecting.from)!), { x: connecting.x, y: connecting.y })} />
          )}
        </svg>

        {selected?.kind === "link" && byId.get(selected.from) && byId.get(selected.to) && (() => {
          const m = linkMid(portOut(byId.get(selected.from)!), portIn(byId.get(selected.to)!));
          return (
            <button className="tc-link-x" style={{ left: m.x, top: m.y }} title="Remove this connection"
                    aria-label="Remove this connection"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => props.onDelete(selected)}><X /></button>
          );
        })()}

        {team.agents.map((a) => {
          const Icon = AGENT_ICONS[a.icon] ?? Bot;
          const state = run?.agents[a.id];
          const status = state?.status ?? "idle";
          const lead = team.lead === a.id;
          return (
            <div key={a.id} data-agent={a.id}
                 className={`tc-node st-${status} ${selected?.kind === "agent" && selected.id === a.id ? "selected" : ""} ${lead ? "lead" : ""} ${!live.has(a.id) ? "orphan" : ""} ${connecting?.over === a.id ? "drop" : ""}`}
                 style={{ transform: `translate(${a.x}px, ${a.y}px)`, width: NODE_W,
                          "--agent": a.color || "var(--accent)" } as CSSProperties}
                 onPointerDown={(e) => onNodeDown(e, a)} onPointerMove={onNodeMove} onPointerUp={onNodeUp}
                 onPointerCancel={onNodeUp}>
              <div className="tc-port in" aria-hidden />
              <div className="tc-node-head">
                <span className="tc-node-icon"><Icon /></span>
                <span className="tc-node-name" title={a.name}>{a.name}</span>
                {status === "done" && <Check className="tc-done" aria-label="Done" />}
                {status === "error" && <TriangleAlert className="tc-err" aria-label="Couldn't finish" />}
                {(status === "planning" || status === "working") && <span className="spinner" aria-label="Working" />}
              </div>
              <div className={`tc-node-role ${a.role ? "" : "muted"}`}>
                {a.role || "Select it, then say what this agent does."}
              </div>
              <div className="tc-node-foot">
                {lead && <span className="tc-chip lead"><Crown /> You talk to it</span>}
                {a.skills.includes("research") && <span className="tc-chip"><Globe /> Research</span>}
                {a.skills.includes("files") && <span className="tc-chip"><FileCode /> Files</span>}
                {!live.has(a.id) && <span className="tc-chip warn">Not connected</span>}
              </div>
              {state && state.status !== "idle" && state.status !== "done" && (
                <div className="tc-node-status" title={state.detail}>
                  {state.status === "planning" ? "Working out who does what…"
                    : state.status === "waiting" ? (state.detail || "Waiting for its team…")
                    : state.status === "stopped" ? "Stopped"
                    : state.status === "error" ? (state.detail || "Couldn't finish")
                    : (state.detail || "Working…")}
                </div>
              )}
              <div className="tc-port out" title="Drag to another agent to hand it work"
                   onPointerDown={(e) => onPortDown(e, a)} onPointerMove={onPortMove} onPointerUp={onPortUp}
                   onPointerCancel={() => setLinking(null)} />
            </div>
          );
        })}
      </div>

      {team.agents.length <= 1 && team.links.length === 0 && (
        <div className="tc-hint">
          Double-click to add an agent · drag from an agent's right-hand dot to another agent to connect them
        </div>
      )}

      <div className="tc-tools" onPointerDown={(e) => e.stopPropagation()}>
        <button className="ghost-icon" title="Zoom out" aria-label="Zoom out"
                onClick={() => { const r = viewport.current!.getBoundingClientRect(); zoomAt(r.left + r.width / 2, r.top + r.height / 2, 1 / 1.2); }}>
          <Minus /></button>
        <span className="tc-zoom">{Math.round(view.zoom * 100)}%</span>
        <button className="ghost-icon" title="Zoom in" aria-label="Zoom in"
                onClick={() => { const r = viewport.current!.getBoundingClientRect(); zoomAt(r.left + r.width / 2, r.top + r.height / 2, 1.2); }}>
          <Plus /></button>
        <button className="ghost-icon" title="Show the whole team" aria-label="Show the whole team" onClick={fit}>
          <LocateFixed /></button>
      </div>
    </div>
  );
}

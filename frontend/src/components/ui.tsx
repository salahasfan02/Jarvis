import { ReactNode, useEffect, useState } from "react";
import { CircleCheck, CircleAlert, LucideIcon } from "lucide-react";

/** Title, one line on what the page is for, and its main actions. */
export function PageHeader(props: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="text">
        <h1>{props.title}</h1>
        {props.children && <p>{props.children}</p>}
      </div>
      {props.actions && <div className="actions">{props.actions}</div>}
    </div>
  );
}

export function EmptyState(props: { icon: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  const Icon = props.icon;
  return (
    <div className="empty">
      <div className="icon-wrap"><Icon /></div>
      <h4>{props.title}</h4>
      {props.children && <p>{props.children}</p>}
      {props.action && <div style={{ marginTop: 8 }}>{props.action}</div>}
    </div>
  );
}

// ---- toasts: toast("Copied") from anywhere -----------------------------------

type Toast = { id: number; text: string; kind: "ok" | "error" };
const bus = new EventTarget();
let next = 1;

export function toast(text: string, kind: "ok" | "error" = "ok") {
  bus.dispatchEvent(new CustomEvent("toast", { detail: { id: next++, text, kind } }));
}

export function Toasts() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const on = (e: Event) => {
      const t = (e as CustomEvent<Toast>).detail;
      setItems((xs) => [...xs.slice(-2), t]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), 2600);
    };
    bus.addEventListener("toast", on);
    return () => bus.removeEventListener("toast", on);
  }, []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          {t.kind === "error" ? <CircleAlert /> : <CircleCheck />} {t.text}
        </div>
      ))}
    </div>
  );
}

/** A small progress ring: done of total. */
export function Ring(props: { done: number; total: number; size?: number }) {
  const size = props.size ?? 64;
  const r = size / 2 - 5;
  const c = 2 * Math.PI * r;
  const frac = props.total ? props.done / props.total : 0;
  const color = frac >= 1 ? "var(--ok)" : frac >= 0.6 ? "var(--accent)" : "var(--warn)";
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth="5" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="5"
                strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - frac)}
                style={{ transition: "stroke-dashoffset .6s var(--ease)" }} />
      </svg>
      <div className="n">{props.done}/{props.total}</div>
    </div>
  );
}

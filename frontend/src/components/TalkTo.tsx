import { useEffect, useRef, useState } from "react";
import { Bot, Check, ChevronDown, Sparkles, Users } from "lucide-react";
import { teamsApi } from "../lib/teamsApi";
import { isSingle, Team } from "../lib/teams";
import { AGENT_ICONS } from "./TeamCanvas";

/** "Talk to: Jarvis ▾" — pick one of your agents or teams and what you type or
 *  say goes straight to it (it works in the background and answers in the chat).
 *  value is the agent's or team's id; "" is Jarvis. */
export function TalkTo(props: {
  value: string;
  onChange: (id: string, name: string) => void;
  up?: boolean;               // open the menu upwards (under a bottom-of-screen box)
}) {
  const [open, setOpen] = useState(false);
  const [teams, setTeams] = useState<Team[] | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const load = () => teamsApi.list().then(setTeams).catch(() => setTeams([]));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    // The chosen one was deleted: back to Jarvis.
    if (teams && props.value && !teams.some((t) => t.id === props.value)) props.onChange("", "Jarvis");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teams, props.value]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const chosen = teams?.find((t) => t.id === props.value);
  const iconOf = (t: Team) => (isSingle(t) ? AGENT_ICONS[t.agents[0].icon] ?? Bot : Users);
  const Current = chosen ? iconOf(chosen) : Sparkles;
  const pick = (id: string, name: string) => { props.onChange(id, name); setOpen(false); };

  return (
    <div className={`talk-to ${props.up ? "up" : ""}`} ref={box}>
      <button type="button" className={`talk-to-btn ${chosen ? "on" : ""}`} aria-haspopup="menu"
              aria-expanded={open} title="Who your message goes to"
              onClick={() => { if (!open) load(); setOpen(!open); }}>
        <Current /> <span className="muted">Talk to</span> <b>{chosen?.name ?? "Jarvis"}</b> <ChevronDown />
      </button>
      {open && (
        <div className="talk-to-menu" role="menu">
          <div className="talk-to-item" role="menuitem" tabIndex={0}
               onClick={() => pick("", "Jarvis")} onKeyDown={(e) => e.key === "Enter" && pick("", "Jarvis")}>
            <Sparkles /> <span className="grow"><b>Jarvis</b><span className="sub">Your assistant — it can also hand work to any agent or team</span></span>
            {!props.value && <Check className="icon-sm" />}
          </div>
          {(teams ?? []).length > 0 && <div className="talk-to-label">Your agents &amp; teams</div>}
          {(teams ?? []).map((t) => {
            const Icon = iconOf(t);
            return (
              <div key={t.id} className="talk-to-item" role="menuitem" tabIndex={0}
                   onClick={() => pick(t.id, t.name)} onKeyDown={(e) => e.key === "Enter" && pick(t.id, t.name)}>
                <Icon /> <span className="grow"><b>{t.name}</b>
                  <span className="sub">{isSingle(t) ? "Agent" : `Team of ${t.agents.length}`}</span></span>
                {props.value === t.id && <Check className="icon-sm" />}
              </div>
            );
          })}
          {teams !== null && teams.length === 0 && (
            <div className="talk-to-empty">Make agents and teams in the Agents tab.</div>
          )}
        </div>
      )}
    </div>
  );
}

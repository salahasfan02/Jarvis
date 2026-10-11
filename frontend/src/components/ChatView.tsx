import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown, Ban, Bug, Check, Circle, CloudSun, Copy, ExternalLink, File, FileCode, FileImage,
  FileText, FileVideo, Folder, FolderOpen, Globe, Mail, Monitor, Pencil, Play, RefreshCw,
  LayoutTemplate, ScanSearch, ShieldAlert, ShieldCheck, Terminal, TriangleAlert, Wand2, X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { API, Message } from "../lib/api";
import {
  describeAction, greeting, linkCitations, Listing, parseListing, shortWhen, Source,
  splitSources, stepLabel, timeAgo,
} from "../lib/format";
import { toast } from "./ui";

const RUNNABLE = ["python", "py", "javascript", "js", "typescript", "ts",
  "bash", "sh", "html", "c", "cpp", "c++", "go", "rust", "java"];

// A step the user said no to (or that isn't allowed from where they are).
const REFUSED = /^(?:The user DENIED|'[\w_]+' (?:is blocked|needs the user|controls the screen))/;

export const AGENTS: Record<string, string> = {
  research: "Research", files: "Files", messaging: "Messages", vision: "Vision",
  automation: "Automation", media: "Media", coding: "Code", planner: "Planner",
};

function textOf(node: any): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node?.props?.children) return textOf(node.props.children);
  return "";
}

function fileIcon(name: string, dir: boolean) {
  if (dir) return Folder;
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (["png", "jpg", "jpeg", "gif", "heic", "webp", "svg"].includes(ext)) return FileImage;
  if (["mov", "mp4", "m4v", "avi", "mkv"].includes(ext)) return FileVideo;
  if (["py", "js", "ts", "tsx", "json", "html", "css", "sh", "swift", "go", "rs"].includes(ext)) return FileCode;
  if (["pdf", "doc", "docx", "txt", "md", "pages", "rtf", "xlsx", "csv", "pptx", "key"].includes(ext)) return FileText;
  return File;
}

/** A folder listing as a list of files, not a code block. */
function FileList({ listing }: { listing: Listing }) {
  const [all, setAll] = useState(false);
  const shown = all ? listing.rows : listing.rows.slice(0, 12);
  return (
    <div className="file-list">
      {(listing.path || listing.note) && (
        <div className="file-list-head">
          <FolderOpen className="icon-sm" />
          <span className="path">{listing.path || "Results"}</span>
          {listing.note && <span>{listing.note}</span>}
        </div>
      )}
      <div className="file-list-body">
        {shown.map((r, i) => {
          const Icon = fileIcon(r.name, r.dir);
          return (
            <div key={i} className={`file-row ${r.dir ? "dir" : ""}`}>
              <Icon /> <span className="name" title={r.name}>{r.name}</span>
              {r.when && <span className="when">{shortWhen(r.when)}</span>}
            </div>
          );
        })}
      </div>
      {listing.rows.length > 12 && (
        <button className="file-list-more" onClick={() => setAll((a) => !a)}>
          {all ? "Show less" : `Show all ${listing.rows.length}`}
        </button>
      )}
    </div>
  );
}

/** Fenced code blocks get Copy (and Run when the sandbox can run them);
 *  ```listing blocks become a file list. */
function PreBlock(props: any) {
  const child = Array.isArray(props.children) ? props.children[0] : props.children;
  const cls: string = child?.props?.className ?? "";
  const lang = (cls.match(/language-([\w+#-]+)/)?.[1] ?? "").toLowerCase();
  const code = textOf(child);
  const [result, setResult] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [copied, setCopied] = useState(false);
  const listing = useMemo(() => (lang === "listing" ? parseListing(code) : null), [lang, code]);
  if (listing) return <FileList listing={listing} />;
  const runnable = RUNNABLE.includes(lang) && code.trim().length > 0;

  const run = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await fetch(`${API}/code/run`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, language: lang }),
      });
      setResult(await res.json());
    } catch (e: any) {
      setResult({ error: e.message });
    } finally {
      setRunning(false);
    }
  };

  const { node: _node, ...rest } = props;
  return (
    <div className="codeblock">
      <div className="codeblock-bar">
        <span>{lang || "code"}</span>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => {
            navigator.clipboard.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1400);
          }}>{copied ? <><Check /> Copied</> : <><Copy /> Copy</>}</button>
          {runnable && (
            <button onClick={run} disabled={running}>
              {running ? <><span className="spinner" style={{ width: 10, height: 10 }} /> Running</> : <><Play /> Run</>}
            </button>
          )}
        </div>
      </div>
      <pre {...rest} />
      {result && (
        <div className={`run-output ${result.error || result.exit_code ? "failed" : "passed"}`}>
          <div className="run-head inline-icon">
            {result.error ? <><TriangleAlert className="icon-bad" /> {result.error}</>
              : result.preview_url ? <><Check className="icon-ok" /> Built</>
              : result.exit_code === 0
                ? <><Check className="icon-ok" /> Ran in {result.seconds ?? "?"}s (sandboxed)</>
              : <><X className="icon-bad" /> Exit code {result.exit_code}</>}
          </div>
          {result.preview_url && (
            <div style={{ padding: "8px 14px" }}>
              <a href={result.preview_url} target="_blank" rel="noreferrer" className="inline-icon">
                <ExternalLink className="icon-sm" /> Open live preview
              </a>
            </div>
          )}
          {result.stdout && <pre>{result.stdout}</pre>}
          {result.stderr && <pre className="stderr">{result.stderr}</pre>}
        </div>
      )}
    </div>
  );
}

/** Links open in the browser (never inside Jarvis); [1] citations are chips. */
function Link(props: React.AnchorHTMLAttributes<HTMLAnchorElement> & { node?: unknown }) {
  const { node: _node, title, children, ...rest } = props;
  if (title?.startsWith("cite:")) {
    return <a {...rest} className="cite" title={title.slice(5)} target="_blank" rel="noreferrer">{children}</a>;
  }
  return <a {...rest} title={title} target="_blank" rel="noreferrer">{children}</a>;
}

function Sources({ sources }: { sources: Source[] }) {
  return (
    <>
      <div className="sources-label">Sources</div>
      <div className="sources">
        {sources.map((s) => (
          <a key={`${s.n}-${s.url}`} className="source" href={s.url} target="_blank" rel="noreferrer" title={s.url}>
            <span className="site"><span className="n">{s.n}</span>{s.site}</span>
            <span className="t">{s.title}</span>
          </a>
        ))}
      </div>
    </>
  );
}

/** An answer: Markdown, with [n] linked to the sources listed at the end. */
export function Answer({ content, streaming = false }: { content: string; streaming?: boolean }) {
  const { body, sources } = useMemo(() => splitSources(content), [content]);
  const md = useMemo(() => linkCitations(body, sources), [body, sources]);
  return (
    <>
      <div className={`bubble prose ${streaming ? "stream-cursor-wrap" : ""}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}
                       components={{ pre: PreBlock, a: Link }}>
          {md}
        </ReactMarkdown>
      </div>
      {sources.length > 0 && !streaming && <Sources sources={sources} />}
    </>
  );
}

export interface ToolChipInfo {
  name: string;
  status: "pending" | "running" | "done" | "denied";
  result?: string;
}

/** The steps Jarvis took ("Researched the web", "Sent the file ×3"). */
function Steps({ steps }: { steps: ToolChipInfo[] }) {
  const merged: (ToolChipInfo & { count: number })[] = [];
  for (const s of steps) {
    const last = merged[merged.length - 1];
    if (last && last.name === s.name && last.status === s.status) last.count++;
    else merged.push({ ...s, count: 1 });
  }
  if (!merged.length) return null;
  return (
    <div className="steps">
      {merged.map((s, i) => (
        <span key={i} className={`step ${s.status}`} title={s.result?.slice(0, 300)}>
          {s.status === "running" ? <span className="spinner" style={{ width: 11, height: 11 }} />
            : s.status === "denied" ? <Ban />
            : s.status === "pending" ? <Circle />
            : <Check />}
          {s.status === "pending" ? s.name
            : s.status === "denied" ? `${describeAction(s.name, {}).title} — not allowed`
            : stepLabel(s.name, s.status !== "running")}
          {s.count > 1 && ` ×${s.count}`}
        </span>
      ))}
    </div>
  );
}

const SUGGESTIONS = [
  { icon: CloudSun, title: "What's the weather today?", sub: "Live forecast for where you are" },
  { icon: Globe, title: "What's new in AI this week?", sub: "Researched, with sources" },
  { icon: FileText, title: "Write a report about electric cars", sub: "As a Word document" },
  { icon: FolderOpen, title: "What's on my Desktop?", sub: "Newest files first" },
  { icon: Mail, title: "Summarise my unread emails", sub: "From Apple Mail" },
  { icon: Monitor, title: "What's on my screen right now?", sub: "Reads the front window" },
];

const CODE_SUGGESTIONS = [
  { icon: Terminal, title: "Write a Python script that renames photos by date", sub: "Runnable in the sandbox" },
  { icon: LayoutTemplate, title: "Build a small HTML page with a countdown timer", sub: "With a live preview" },
  { icon: Bug, title: "Explain this error and how to fix it", sub: "Paste the traceback" },
  { icon: ScanSearch, title: "Review my code for bugs and edge cases", sub: "Paste or attach a file" },
  { icon: Wand2, title: "Refactor this function to be clearer", sub: "Same behaviour, cleaner code" },
  { icon: FileCode, title: "Write tests for this module", sub: "pytest or vitest" },
];

export function ChatView(props: {
  messages: Message[];
  streaming: string | null;          // partial assistant text while generating
  chips: ToolChipInfo[];             // tool activity for the in-flight turn
  agentName: string | null;
  busy: boolean;
  onEdit: (msg: Message) => void;
  onRegenerate: (msg: Message) => void;
  onCopy: (text: string) => void;
  onSuggestion: (text: string) => void;
  assistantName: string;
  userName?: string;
  mode?: "chat" | "code";
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const toBottom = (smooth = true) =>
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: smooth ? "smooth" : "auto" });

  useEffect(() => {
    if (pinned) toBottom(false);
  }, [props.messages.length, props.streaming, props.chips.length, pinned]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 120);
  };

  if (props.messages.length === 0 && !props.streaming && !props.busy) {
    return (
      <div className="welcome">
        <div className="orb" />
        <h2>{greeting(props.userName ?? "")}</h2>
        <p>{props.mode === "code" ? "What are we building?" : `What can ${props.assistantName} do for you?`}</p>
        <div className="suggest-grid">
          {(props.mode === "code" ? CODE_SUGGESTIONS : SUGGESTIONS).map((s) => (
            <button key={s.title} className="suggest" onClick={() => props.onSuggestion(s.title)}>
              <s.icon />
              <div><b>{s.title}</b><span>{s.sub}</span></div>
            </button>
          ))}
        </div>
      </div>
    );
  }

  const copy = (text: string) => { props.onCopy(text); toast("Copied"); };
  const live = props.streaming !== null || props.chips.length > 0;

  return (
    <>
      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="chat-inner">
          {props.messages.map((m, i) => {
            const last = i === props.messages.length - 1;
            if (m.role === "user") {
              return (
                <div key={m.id} className="msg user" dir="auto">
                  <div className="msg-body">
                    <div className="bubble">{m.content}</div>
                    <div className="msg-actions">
                      <button onClick={() => copy(m.content)} title="Copy"><Copy /></button>
                      <button onClick={() => props.onEdit(m)} title="Edit and resend"><Pencil /></button>
                    </div>
                  </div>
                </div>
              );
            }
            const steps = (m.meta?.tools ?? []).map((t: any): ToolChipInfo => ({
              name: t.name, result: t.result,
              status: REFUSED.test(t.result ?? "") ? "denied" : "done" }));
            const agent = AGENTS[m.meta?.agent ?? ""];
            return (
              <div key={m.id} className={`msg assistant ${last && !live ? "last" : ""}`} dir="auto">
                <div className="avatar orb" />
                <div className="msg-body">
                  <div className="msg-name">{props.assistantName}{agent && <span className="agent">{agent}</span>}</div>
                  <Steps steps={steps} />
                  <Answer content={m.content} />
                  <div className="msg-actions">
                    <button onClick={() => copy(m.content)} title="Copy"><Copy /> Copy</button>
                    {last && !props.busy && (
                      <button onClick={() => props.onRegenerate(m)} title="Ask again"><RefreshCw /> Retry</button>
                    )}
                    {m.created_at && <span className="when">{timeAgo(m.created_at)}</span>}
                  </div>
                </div>
              </div>
            );
          })}

          {live && (
            <div className="msg assistant" dir="auto" aria-live="polite">
              <div className="avatar orb thinking" />
              <div className="msg-body">
                <div className="msg-name">
                  {props.assistantName}
                  {props.agentName && <span className="agent">{props.agentName}</span>}
                </div>
                <Steps steps={props.chips} />
                {props.streaming ? <Answer content={props.streaming} streaming />
                  : <div className="typing" aria-label="Thinking"><span /><span /><span /></div>}
              </div>
            </div>
          )}
        </div>
      </div>
      {!pinned && (
        <button className="jump-latest" onClick={() => { setPinned(true); toBottom(); }}>
          <ArrowDown className="icon-sm" /> Latest
        </button>
      )}
    </>
  );
}

export interface ConfirmRequest {
  id: string;
  tool: string;
  arguments: any;
  risk: string;
  always_ask?: boolean;  // e.g. send_email: asked every time, never "always allow"
}

/** Jarvis asks before doing something that matters — in words, not JSON. */
export function ConfirmModal(props: {
  request: ConfirmRequest;
  onResolve: (approved: boolean, remember: boolean) => void;
}) {
  const [remember, setRemember] = useState(false);
  const { request } = props;
  const danger = request.risk === "dangerous";
  const action = describeAction(request.tool, request.arguments ?? {});
  const monoKeys = new Set(["Command", "Code", "Script", "From"]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") props.onResolve(false, false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.onResolve]);

  return (
    <div className="modal-backdrop">
      <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <div className="modal-head">
          <div className={`tile-icon ${danger ? "danger" : ""}`}>{danger ? <ShieldAlert /> : <ShieldCheck />}</div>
          <div style={{ flex: 1 }}>
            <h3 id="confirm-title">{action.title}?</h3>
            <p>{danger ? "This can change or delete things on your Mac. Check it carefully."
                       : "Jarvis needs your OK before it does this."}</p>
          </div>
          <span className={`risk ${request.risk}`}>{danger ? "Careful" : "Needs OK"}</span>
        </div>
        <div className="modal-body">
          {action.lines.length > 0 && (
            <div className="modal-details">
              {action.lines.map(([k, v]) => (
                <div key={k} className="kv"><span className="k">{k}</span>
                  <span className={`v ${monoKeys.has(k) ? "mono" : ""}`}>{v}</span></div>
              ))}
            </div>
          )}
          <details className="modal-raw">
            <summary>Technical details</summary>
            <pre>{request.tool}({JSON.stringify(request.arguments, null, 2)})</pre>
          </details>
        </div>
        <div className="modal-foot">
          {!danger && !request.always_ask ? (
            <label className="remember">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              Don't ask again for this
            </label>
          ) : <span style={{ marginRight: "auto" }} />}
          <button className="btn" onClick={() => props.onResolve(false, false)}>Don't allow</button>
          <button className={`btn primary ${danger ? "danger-primary" : ""}`}
                  onClick={() => props.onResolve(true, remember)}>Allow</button>
        </div>
      </div>
    </div>
  );
}

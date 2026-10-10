import { useEffect, useRef, useState } from "react";
import { Ban, Check, Circle, ExternalLink, Play, TriangleAlert, Wrench, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { API, Message } from "../lib/api";

const RUNNABLE = ["python", "py", "javascript", "js", "typescript", "ts",
  "bash", "sh", "html", "c", "cpp", "c++", "go", "rust", "java"];

function textOf(node: any): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node?.props?.children) return textOf(node.props.children);
  return "";
}

/** Fenced code blocks in chat get a toolbar: Copy always, Run when the
 *  language is executable in the sandbox. */
function PreBlock(props: any) {
  const child = Array.isArray(props.children) ? props.children[0] : props.children;
  const cls: string = child?.props?.className ?? "";
  const lang = (cls.match(/language-([\w+#-]+)/)?.[1] ?? "").toLowerCase();
  const code = textOf(child);
  const [result, setResult] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [copied, setCopied] = useState(false);
  const runnable = RUNNABLE.includes(lang) && code.trim().length > 0;

  const run = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await fetch(`${API}/code/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, language: lang }),
      });
      setResult(await res.json());
    } catch (e: any) {
      setResult({ error: e.message });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="codeblock">
      <div className="codeblock-bar">
        <span>{lang || "code"}</span>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => {
            navigator.clipboard.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}>{copied ? <><Check /> copied</> : "copy"}</button>
          {runnable && (
            <button onClick={run} disabled={running}>
              {running ? "running…" : <><Play /> run</>}
            </button>
          )}
        </div>
      </div>
      <pre {...props} />
      {result && (
        <div className={`run-output ${result.error || result.exit_code ? "failed" : "passed"}`}>
          <div className="run-head inline-icon">
            {result.error ? <><TriangleAlert className="icon-bad" /> {result.error}</>
              : result.preview_url ? <><Check className="icon-ok" /> built</>
              : result.exit_code === 0
                ? <><Check className="icon-ok" /> ran in {result.seconds ?? "?"}s (sandboxed)</>
              : <><X className="icon-bad" /> exit code {result.exit_code}</>}
          </div>
          {result.preview_url && (
            <div style={{ padding: "8px 14px" }}>
              <a href={result.preview_url} target="_blank" rel="noreferrer"
                 className="inline-icon" style={{ color: "var(--accent)" }}>
                <ExternalLink /> open live preview
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

export interface ToolChipInfo {
  name: string;
  status: "pending" | "running" | "done" | "denied";
  result?: string;
}

export interface ConfirmRequest {
  id: string;
  tool: string;
  arguments: any;
  risk: string;
  always_ask?: boolean;  // e.g. send_email: asked every time, never "always allow"
}

function Bubble({ content }: { content: string }) {
  return (
    <div className="bubble">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}
                     components={{ pre: PreBlock }}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

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
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    if (pinned) endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [props.messages.length, props.streaming, props.chips.length, pinned]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 120);
  };

  if (props.messages.length === 0 && !props.streaming && !props.busy) {
    return (
      <div className="empty-state">
        <div className="orb" />
        <h2>How can I help, sir?</h2>
        <div>Ask anything, or try one of these</div>
        <div className="suggestions">
          {[
            "What's on my screen right now?",
            "Search the web for today's AI news",
            "Open Safari",
            "Organize the files on my Desktop",
            "Remember that I prefer TypeScript",
            "Draft an email to my professor",
          ].map((s) => (
            <button key={s} onClick={() => props.onSuggestion(s)}>{s}</button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
      <div className="chat-inner">
        {props.messages.map((m, i) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.meta?.tools?.map((t, j) => (
              <span key={j} className="chip"><Wrench className="icon-sm" /> {t.name}</span>
            ))}
            <Bubble content={m.content} />
            <div className="msg-meta msg-actions">
              {m.meta?.agent && m.role === "assistant" && <span>{m.meta.agent}</span>}
              <button onClick={() => props.onCopy(m.content)}>copy</button>
              {m.role === "user" && (
                <button onClick={() => props.onEdit(m)}>edit</button>
              )}
              {m.role === "assistant" && i === props.messages.length - 1 && !props.busy && (
                <button onClick={() => props.onRegenerate(m)}>regenerate</button>
              )}
            </div>
          </div>
        ))}

        {(props.streaming !== null || props.chips.length > 0) && (
          <div className="msg assistant">
            {props.agentName && <div className="msg-meta">{props.agentName}</div>}
            {props.chips.map((c, i) => (
              <span key={i} className={`chip ${c.status === "denied" ? "denied" : ""}`}
                    style={c.status === "pending" ? { opacity: 0.45 } : undefined}>
                {c.status === "running" ? <span className="spinner" />
                  : c.status === "denied" ? <Ban className="icon-sm" />
                  : c.status === "pending" ? <Circle className="icon-sm" />
                  : <Check className="icon-sm icon-ok" />}
                {c.name}
              </span>
            ))}
            {props.streaming ? (
              <Bubble content={props.streaming} />
            ) : (
              <div className="bubble"><span className="spinner" style={{ display: "inline-block", width: 12, height: 12, borderRadius: "50%", border: "2px solid var(--accent-soft)", borderTopColor: "var(--accent)", animation: "spin 0.8s linear infinite" }} /></div>
            )}
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

export function ConfirmModal(props: {
  request: ConfirmRequest;
  onResolve: (approved: boolean, remember: boolean) => void;
}) {
  const [remember, setRemember] = useState(false);
  const { request } = props;
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3>
          Permission needed
          <span className={`risk ${request.risk}`}>{request.risk}</span>
        </h3>
        <div style={{ fontSize: 14 }}>
          {props.request.tool === "run_command" || request.risk === "dangerous"
            ? "Jarvis wants to run a potentially destructive action:"
            : "Jarvis wants to use a tool that affects your system:"}
        </div>
        <pre>{request.tool}({JSON.stringify(request.arguments, null, 2)})</pre>
        <div className="actions">
          {request.risk !== "dangerous" && !request.always_ask && (
            <label className="remember">
              <input type="checkbox" checked={remember}
                     onChange={(e) => setRemember(e.target.checked)} />
              always allow {request.tool}
            </label>
          )}
          <button className="btn" onClick={() => props.onResolve(false, false)}>Deny</button>
          <button className="btn primary" onClick={() => props.onResolve(true, remember)}>Allow</button>
        </div>
      </div>
    </div>
  );
}

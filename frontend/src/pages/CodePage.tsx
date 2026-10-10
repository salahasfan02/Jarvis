import { useEffect, useRef, useState } from "react";
import { ArrowUp, Check, Code, Play, Square, Sparkles, TriangleAlert, Wand2, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import { API } from "../lib/api";

const LANGUAGES = ["auto", "python", "typescript", "javascript", "html", "css",
  "swift", "bash", "sql", "go", "rust", "java", "c", "c++", "c#"] as const;

const EXTENSIONS: Record<string, string> = {
  python: "py", typescript: "ts", javascript: "js", html: "html", css: "css",
  swift: "swift", bash: "sh", sql: "sql", go: "go", rust: "rs", java: "java",
  c: "c", "c++": "cpp", "c#": "cs",
};

interface Turn { role: "user" | "assistant"; content: string; }

/** Extract the contents + language of the first fenced code block. */
function extractCode(markdown: string): { code: string; lang: string } {
  const m = markdown.match(/```([\w#+-]*)\n([\s\S]*?)(?:```|$)/);
  if (m) return { lang: m[1] || "", code: m[2] };
  return { lang: "", code: markdown.trim() };
}

export function CodePage({ seed, onSeedConsumed }: {
  seed?: string;
  onSeedConsumed?: () => void;
}) {
  const [language, setLanguage] = useState<string>("auto");
  const [prompt, setPrompt] = useState("");

  // A gap's "Fix it" button pre-fills the request
  useEffect(() => {
    if (seed) {
      setPrompt(seed);
      setLanguage("python");
      onSeedConsumed?.();
    }
  }, [seed, onSeedConsumed]);
  const [history, setHistory] = useState<Turn[]>([]);
  const [output, setOutput] = useState("");       // streaming markdown
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [runResult, setRunResult] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [installMsg, setInstallMsg] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const latest = output || [...history].reverse().find((t) => t.role === "assistant")?.content || "";
  const { code, lang } = extractCode(latest);

  const generate = async () => {
    const request = prompt.trim();
    if (!request || busy) return;
    setPrompt("");
    setBusy(true);
    setOutput("");
    const turns: Turn[] = [...history, { role: "user", content: request }];
    setHistory(turns);

    const controller = new AbortController();
    abortRef.current = controller;
    let acc = "";
    try {
      const res = await fetch(`${API}/code/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: turns, language: language === "auto" ? "" : language }),
        signal: controller.signal,
      });
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.token) {
            acc += ev.token;
            setOutput(acc);
            scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
          }
          if (ev.error) acc += `\n\n**Error:** ${ev.error}`;
        }
      }
    } catch (e: any) {
      if (e.name !== "AbortError") acc += `\n\n**Error:** ${e.message}`;
    }
    setHistory((h) => [...h, { role: "assistant", content: acc }]);
    setOutput("");
    setBusy(false);
  };

  const copyCode = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const runnable = ["python", "javascript", "bash", ""].includes(lang) ||
    ["python", "javascript", "bash"].includes(language);

  const runCode = async () => {
    setRunning(true);
    setRunResult(null);
    try {
      const res = await fetch(`${API}/code/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, language: lang || language || "python" }),
      });
      setRunResult(await res.json());
    } catch (e: any) {
      setRunResult({ error: e.message });
    } finally {
      setRunning(false);
    }
  };

  const autoFix = () => {
    if (!runResult) return;
    const report = runResult.error
      ? `Execution error: ${runResult.error}`
      : `exit code ${runResult.exit_code}\nstdout:\n${runResult.stdout}\nstderr:\n${runResult.stderr}`;
    setPrompt(`I ran the code and it failed. Fix it and return the complete corrected file.\n\n${report}`);
    setRunResult(null);
  };

  const installSkill = async () => {
    const name = window.prompt("Skill name (e.g. volume_control):");
    if (!name) return;
    setInstallMsg("installing…");
    try {
      const res = await fetch(`${API}/plugins/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, code }),
      });
      const r = await res.json();
      setInstallMsg(r.error ? `Install failed: ${r.error}`
        : `Installed — new tools: ${r.new_tools?.join(", ") || "none"}`);
    } catch (e: any) {
      setInstallMsg(`Install failed: ${e.message}`);
    }
  };

  const download = () => {
    const ext = EXTENSIONS[lang] ?? EXTENSIONS[language] ?? "txt";
    const blob = new Blob([code], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `jarvis-code.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="code-page">
      <div className="code-toolbar">
        <span className="code-title inline-icon"><Code /> Code Studio</span>
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
        <div style={{ flex: 1 }} />
        {history.length > 0 && (
          <>
            {runnable && (
              <button className="btn primary" disabled={running || busy} onClick={runCode}>
                {running ? "Running…" : <><Play /> Run</>}
              </button>
            )}
            {code.includes("@tool(") && (
              <button className="btn" onClick={installSkill}><Sparkles /> Install as skill</button>
            )}
            <button className="btn" onClick={copyCode}>{copied ? <><Check /> Copied</> : "Copy code"}</button>
            <button className="btn" onClick={download}>Download</button>
            <button className="btn" onClick={() => { setHistory([]); setOutput(""); setRunResult(null); setInstallMsg(""); }}>
              New session
            </button>
          </>
        )}
      </div>
      {installMsg && <div className="run-banner">{installMsg}</div>}

      <div className="code-output" ref={scrollRef}>
        {history.length === 0 && !output ? (
          <div className="code-empty">
            <Code className="empty-icon" />
            <h2>What should I build?</h2>
            <div className="sub">
              Describe a program, script, component or function.<br />
              Then iterate: "add error handling", "make it faster", "add tests"…
            </div>
          </div>
        ) : (
          <>
            {history.map((turn, i) =>
              turn.role === "user" ? (
                <div key={i} className="code-request">&gt; {turn.content}</div>
              ) : (
                <div key={i} className="code-block">
                  <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{turn.content}</ReactMarkdown>
                </div>
              )
            )}
            {output && (
              <div className="code-block">
                <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{output}</ReactMarkdown>
              </div>
            )}
            {busy && !output && <div className="code-request">compiling thoughts<span className="cursor-blink">▊</span></div>}
            {runResult && (
              <div className={`run-output ${runResult.error || runResult.exit_code ? "failed" : "passed"}`}>
                <div className="run-head">
                  <span className="inline-icon">
                    {runResult.error ? <><TriangleAlert className="icon-bad" /> {runResult.error}</>
                      : runResult.exit_code === 0
                        ? <><Check className="icon-ok" /> ran successfully (sandboxed)</>
                      : <><X className="icon-bad" /> exited with code {runResult.exit_code}</>}
                  </span>
                  {(runResult.error || runResult.exit_code !== 0) && (
                    <button className="btn" onClick={autoFix}><Wand2 /> Auto-fix</button>
                  )}
                </div>
                {runResult.stdout && <pre>{runResult.stdout}</pre>}
                {runResult.stderr && <pre className="stderr">{runResult.stderr}</pre>}
              </div>
            )}
          </>
        )}
      </div>

      <div className="code-composer">
        <textarea
          rows={2}
          placeholder={history.length ? "Refine the code — e.g. 'add error handling'…"
                                       : "e.g. A Python script that renames all photos in a folder by date taken"}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              generate();
            }
          }}
        />
        {busy ? (
          <button className="icon-btn" title="Stop" onClick={() => abortRef.current?.abort()}><Square /></button>
        ) : (
          <button className="icon-btn primary" title="Generate" disabled={!prompt.trim()}
                  onClick={generate}><ArrowUp /></button>
        )}
      </div>
    </div>
  );
}

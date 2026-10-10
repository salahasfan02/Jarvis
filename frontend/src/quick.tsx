/** Standalone menu-bar quick-command window (loaded at ?quick).
 *  A minimal Spotlight-style bar: ask Jarvis anything, optionally with the
 *  current screen as context, and get a streamed text answer — no full app. */
import { useEffect, useRef, useState } from "react";
import { Eye } from "lucide-react";
import ReactDOM from "react-dom/client";
import ReactMarkdown from "react-markdown";
import "./styles/global.css";

const API = "http://127.0.0.1:8765/api";

function Quick() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [seeScreen, setSeeScreen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = "hacker";
    inputRef.current?.focus();
    // Electron re-focuses the input each time the window is shown.
    (window as any).jarvisFocus = () => inputRef.current?.focus();
  }, []);

  const ask = async () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setAnswer("");
    try {
      // For the "look at my screen" toggle, capture the screen via Electron (which hides this
      // panel first) so the OCR reads the app behind us, not our own bar.
      let screenText = "";
      if (seeScreen && (window as any).jarvisCaptureScreen) {
        try { screenText = await (window as any).jarvisCaptureScreen(); } catch { /* ignore */ }
      }
      const res = await fetch(`${API}/quick`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, include_screen: seeScreen, screen_text: screenText }),
      });
      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = "", acc = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.token) { acc += ev.token; setAnswer(acc); }
          if (ev.error) setAnswer(`Error: ${ev.error}`);
        }
      }
    } catch (e: any) {
      setAnswer(`Error: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="quick">
      <div className="quick-bar">
        <span className="quick-orb" />
        <input
          ref={inputRef}
          placeholder="Ask Jarvis…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") ask();
            if (e.key === "Escape") (window as any).jarvisHide?.();
          }}
        />
        <button className={`quick-eye ${seeScreen ? "on" : ""}`}
                title="Include what's on my screen"
                onClick={() => setSeeScreen((v) => !v)}><Eye /></button>
      </div>
      {(answer || busy) && (
        <div className="quick-answer">
          {answer ? <ReactMarkdown>{answer}</ReactMarkdown>
                  : <span className="quick-dim">thinking…</span>}
        </div>
      )}
      {seeScreen && !answer && (
        <div className="quick-hint inline-icon"><Eye className="icon-sm" /> on — I'll look at your screen to answer</div>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<Quick />);

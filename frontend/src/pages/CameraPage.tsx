import { useEffect, useRef, useState } from "react";
import { Camera, Play, Square } from "lucide-react";
import { API } from "../lib/api";
import { speak } from "../lib/voice";
import { cameraBus, deliverFrame, framesWanted } from "../lib/camera";

/** Live camera vision: keeps the webcam on, and answers questions about what
 *  it sees using the configured vision model (llava). */
export function CameraPage({ speakReplies, jarvisReply }: {
  speakReplies: boolean;
  jarvisReply?: string | null;   // Jarvis's answer after it looked (voice/chat request)
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [on, setOn] = useState(false);
  const [err, setErr] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);
  const autoTimer = useRef<any>(null);
  const [jarvisLooked, setJarvisLooked] = useState(false);

  const start = async (): Promise<boolean> => {
    setErr("");
    if (streamRef.current?.active) return true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } });
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setOn(true);
      return true;
    } catch (e: any) {
      setErr("Couldn't open the camera — allow camera access. " + e.message);
      return false;
    }
  };

  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setOn(false);
    setAuto(false);
  };

  useEffect(() => () => stop(), []);

  // Jarvis asked to look (voice/chat): turn the camera on, let it adjust
  // exposure for a moment, then hand over a photo.
  useEffect(() => {
    const serve = async () => {
      if (!framesWanted()) return;
      if (!(await start())) { deliverFrame(null, "camera access was refused"); return; }
      let frame: string | null = null;
      for (let i = 0; i < 40 && !frame; i++) {   // up to ~4 s for the first frame
        await new Promise((r) => setTimeout(r, 100));
        frame = captureFrame();
      }
      if (frame) await new Promise((r) => setTimeout(r, 700));   // auto-exposure settles
      setJarvisLooked(true);
      deliverFrame(captureFrame() ?? frame, "the camera didn't produce a picture");
    };
    serve();
    cameraBus.addEventListener("frame-wanted", serve);
    return () => cameraBus.removeEventListener("frame-wanted", serve);
  }, []);

  const captureFrame = (): string | null => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return null;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d")!.drawImage(v, 0, 0);
    return canvas.toDataURL("image/jpeg", 0.8);
  };

  const ask = async (q: string) => {
    const frame = captureFrame();
    if (!frame) { setErr("Camera isn't ready yet."); return; }
    setBusy(true);
    setAnswer("");
    try {
      const res = await fetch(`${API}/vision/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: frame, question: q || "What do you see?" }),
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
          if (ev.error) { setAnswer(`Error: ${ev.error}`); }
        }
      }
      if (speakReplies && acc) speak(acc);
    } catch (e: any) {
      setAnswer(`Error: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  // "keep watching": re-ask the standing question every ~8s
  useEffect(() => {
    if (auto && on) {
      autoTimer.current = setInterval(() => { if (!busy) ask(question || "Describe what you see now."); }, 8000);
      return () => clearInterval(autoTimer.current);
    }
  }, [auto, on, busy, question]);

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Camera Vision</h1>
        <div className="sub" style={{ marginTop: -8 }}>
          Turn the camera on and ask about what Jarvis sees. Uses your local
          vision model — nothing is uploaded.
        </div>

        <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
          <video ref={videoRef} autoPlay playsInline muted
                 style={{ width: "100%", display: on ? "block" : "none", background: "#000" }} />
          {!on && (
            <div style={{ padding: 40, textAlign: "center", color: "var(--text-dim)" }}>
              <Camera className="empty-icon" />
              <div style={{ marginTop: 8 }}>Camera is off</div>
            </div>
          )}
        </div>

        {err && <div className="sub" style={{ color: "var(--danger)" }}>{err}</div>}

        <div style={{ display: "flex", gap: 8 }}>
          {!on ? (
            <button className="btn primary" onClick={() => start()}><Camera /> Turn camera on</button>
          ) : (
            <>
              <button className="btn danger" onClick={stop}>Turn off</button>
              <button className={`btn ${auto ? "primary" : ""}`} onClick={() => setAuto((a) => !a)}>
                {auto ? <><Square /> Stop live commentary</> : <><Play /> Live commentary</>}
              </button>
            </>
          )}
        </div>

        {jarvisLooked && jarvisReply && (
          <div className="panel" style={{ fontSize: 14.5, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
            <div className="sub" style={{ marginBottom: 6 }}>Jarvis</div>
            {jarvisReply}
          </div>
        )}

        {on && (
          <div className="panel">
            <div style={{ display: "flex", gap: 8 }}>
              <input type="text" className="search" style={{ flex: 1 }}
                     placeholder="Ask about what the camera sees… (e.g. what is this? read this label)"
                     value={question}
                     onChange={(e) => setQuestion(e.target.value)}
                     onKeyDown={(e) => e.key === "Enter" && !busy && ask(question)} />
              <button className="btn primary" disabled={busy} onClick={() => ask(question)}>
                {busy ? "Looking…" : "Ask"}
              </button>
            </div>
            {answer && (
              <div style={{ marginTop: 12, fontSize: 14.5, lineHeight: 1.55,
                            color: "var(--text)", whiteSpace: "pre-wrap" }}>
                {answer}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

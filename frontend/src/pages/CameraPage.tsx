import { useCallback, useEffect, useRef, useState } from "react";
import { Aperture, Camera, FolderOpen, Images, Play, Send, Square, Trash2, X } from "lucide-react";
import { API, ORIGIN } from "../lib/api";
import { EmptyState, PageHeader, toast } from "../components/ui";
import { speak } from "../lib/voice";
import { cameraBus, deliverFrame, framesWanted, pendingShot } from "../lib/camera";
import { timeAgo } from "../lib/format";

interface Photo { name: string; url: string; path: string; bytes: number; taken_at: number }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const TIMERS = [0, 3, 10];

/** Live camera vision and photos: keeps the webcam on, answers questions about
 *  what it sees using the configured vision model, and takes photos — by the
 *  shutter button or when asked ("take a picture"), with a countdown to pose. */
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
  const [count, setCount] = useState<number | null>(null);
  const [flash, setFlash] = useState(false);
  const [shooting, setShooting] = useState(false);
  const [timer, setTimer] = useState<number>(() => {
    const saved = localStorage.getItem("jarvis.camera.timer");
    return saved !== null && TIMERS.includes(Number(saved)) ? Number(saved) : 3;
  });
  const [photos, setPhotos] = useState<Photo[] | null>(null);
  const [viewing, setViewing] = useState<Photo | null>(null);
  const [arming, setArming] = useState<string | null>(null);
  const serving = useRef(false);

  useEffect(() => { localStorage.setItem("jarvis.camera.timer", String(timer)); }, [timer]);
  useEffect(() => {
    if (!arming) return;
    const t = setTimeout(() => setArming(null), 3000);
    return () => clearTimeout(t);
  }, [arming]);

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

  const captureFrame = (): string | null => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return null;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d")!.drawImage(v, 0, 0);
    return canvas.toDataURL("image/jpeg", 0.9);
  };

  /** Camera on, and the first frame in (up to ~4 s): that frame, or null. */
  const ready = async (): Promise<string | null> => {
    if (!(await start())) return null;
    let frame: string | null = null;
    for (let i = 0; i < 40 && !frame; i++) {
      await sleep(100);
      frame = captureFrame();
    }
    return frame;
  };

  const countDown = async (seconds: number) => {
    for (let n = seconds; n > 0; n--) {
      setCount(n);
      await sleep(1000);
    }
    setCount(null);
  };

  const snapFlash = () => {
    setFlash(true);
    setTimeout(() => setFlash(false), 420);
  };

  const loadPhotos = useCallback(() => {
    fetch(`${API}/photos?limit=24`).then((r) => r.json()).then(setPhotos).catch(() => setPhotos([]));
  }, []);

  useEffect(() => {
    loadPhotos();
    cameraBus.addEventListener("photos-changed", loadPhotos);
    return () => cameraBus.removeEventListener("photos-changed", loadPhotos);
  }, [loadPhotos]);

  // Jarvis asked to look or to take a photo (voice/chat): turn the camera on,
  // count down if it's a photo, then hand over the picture.
  useEffect(() => {
    const serve = async () => {
      if (serving.current) return;
      serving.current = true;
      try {
        while (framesWanted()) {
          const frame = await ready();
          if (!frame) {
            deliverFrame(null, streamRef.current ? "the camera didn't produce a picture"
                                                  : "camera access was refused");
            continue;
          }
          const shot = pendingShot();
          if (shot.countdown > 0) await countDown(shot.countdown);
          else await sleep(700);   // auto-exposure settles
          const image = captureFrame() ?? frame;
          if (shot.photo) snapFlash();
          setJarvisLooked(true);
          deliverFrame(image);
        }
      } finally {
        serving.current = false;
      }
    };
    serve();
    cameraBus.addEventListener("frame-wanted", serve);
    return () => cameraBus.removeEventListener("frame-wanted", serve);
  }, []);

  /** The shutter button: a photo saved in Pictures/Jarvis. */
  const shoot = async () => {
    if (shooting || count !== null) return;
    setShooting(true);
    try {
      const first = await ready();
      if (!first) { setErr((e) => e || "The camera didn't produce a picture."); return; }
      if (timer > 0) await countDown(timer);
      const image = captureFrame() ?? first;
      snapFlash();
      const res = await fetch(`${API}/photos`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image }),
      }).then((r) => r.json());
      if (res.error) { toast(res.error, "error"); return; }
      toast("Photo saved to Pictures › Jarvis");
      loadPhotos();
    } catch {
      toast("Couldn't save the photo", "error");
    } finally {
      setShooting(false);
    }
  };

  // Space bar = shutter, while the camera is on and you're not typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.("input, textarea, select, [contenteditable]");
      if (e.code === "Space" && on && !typing && !viewing) { e.preventDefault(); shoot(); }
      if (e.key === "Escape") setViewing(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const sendPhoto = async (p: Photo) => {
    const res = await fetch(`${API}/photos/${encodeURIComponent(p.name)}/send`, { method: "POST" })
      .then((r) => r.json()).catch(() => ({ ok: false, result: "Couldn't reach Jarvis." }));
    toast(res.result, res.ok ? "ok" : "error");
  };
  const revealPhoto = (p: Photo) =>
    fetch(`${API}/photos/${encodeURIComponent(p.name)}/reveal`, { method: "POST" }).catch(() => {});
  const deletePhoto = async (p: Photo) => {
    if (arming !== p.name) { setArming(p.name); return; }
    setArming(null);
    const res = await fetch(`${API}/photos/${encodeURIComponent(p.name)}`, { method: "DELETE" })
      .then((r) => r.json()).catch(() => ({ ok: false }));
    if (res.ok) {
      toast("Moved to the Bin");
      if (viewing?.name === p.name) setViewing(null);
      loadPhotos();
    } else {
      toast("Couldn't delete it", "error");
    }
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

  const fresh = (p: Photo) => Date.now() / 1000 - p.taken_at < 90;

  return (
    <div className="page">
      <div className="page-inner">
        <PageHeader title="Camera">
          Show Jarvis something and ask about it, or take a photo — say “take a picture”, or press
          the shutter. Uses your local vision model; nothing is uploaded.
        </PageHeader>

        <div className="camera-frame">
          <video ref={videoRef} autoPlay playsInline muted style={{ display: on ? "block" : "none" }} />
          {on && <span className="live">LIVE</span>}
          {count !== null && <div className="camera-count" key={count} aria-live="assertive">{count}</div>}
          {flash && <div className="camera-flash" />}
          {!on && (
            <div className="empty">
              <div className="icon-wrap"><Camera /></div>
              <h4 style={{ color: "#e6e9ee" }}>Camera is off</h4>
              <p>Turn it on, then ask “what is this?” — or take a photo.</p>
            </div>
          )}
        </div>

        {err && <div className="sub" style={{ color: "var(--danger)" }}>{err}</div>}

        <div className="camera-controls">
          <button className="btn primary" onClick={shoot} disabled={shooting || count !== null}
                  title={on ? "Take a photo (Space)" : "Take a photo"}>
            {shooting ? <span className="spinner" /> : <Aperture />} Take photo
          </button>
          <div className="seg" role="group" aria-label="Self-timer">
            {TIMERS.map((t) => (
              <button key={t} className={timer === t ? "active" : ""} aria-pressed={timer === t}
                      title={t ? `Count down ${t} seconds first` : "Take it right away"}
                      onClick={() => setTimer(t)}>{t ? `${t}s` : "Now"}</button>
            ))}
          </div>
          <div className="grow" />
          {!on ? (
            <button className="btn" onClick={() => start()}><Camera /> Turn camera on</button>
          ) : (
            <>
              <button className={`btn ${auto ? "primary" : ""}`} onClick={() => setAuto((a) => !a)}>
                {auto ? <><Square /> Stop live commentary</> : <><Play /> Live commentary</>}
              </button>
              <button className="btn danger" onClick={stop}>Turn off</button>
            </>
          )}
        </div>

        {jarvisLooked && jarvisReply && (
          <div className="panel">
            <div className="eyebrow" style={{ marginBottom: 6 }}>Jarvis</div>
            <div className="answer-card">{jarvisReply}</div>
          </div>
        )}

        {on && (
          <div className="panel">
            <div style={{ display: "flex", gap: 8 }}>
              <input type="text" className="field" style={{ flex: 1 }} aria-label="Question"
                     placeholder="Ask about what the camera sees… (e.g. what is this? read this label)"
                     value={question}
                     onChange={(e) => setQuestion(e.target.value)}
                     onKeyDown={(e) => e.key === "Enter" && !busy && ask(question)} />
              <button className="btn primary" disabled={busy} onClick={() => ask(question)}>
                {busy ? "Looking…" : "Ask"}
              </button>
            </div>
            {answer && (
              <div className="answer-card" style={{ marginTop: 14 }}>{answer}</div>
            )}
          </div>
        )}

        <div className="panel">
          <div className="panel-head">
            <h3><Images className="icon-sm" /> Photos</h3>
            <span className="sub">Saved in Pictures › Jarvis</span>
          </div>
          {photos === null && <div className="sub">Loading…</div>}
          {photos && photos.length === 0 && (
            <EmptyState icon={Images} title="No photos yet">
              Say “take a picture” — or “take a selfie and send it to me” to get it on your phone.
            </EmptyState>
          )}
          {photos && photos.length > 0 && (
            <div className="photo-grid">
              {photos.map((p) => (
                <figure key={p.name} className={`photo-tile ${fresh(p) ? "fresh" : ""}`}>
                  <button className="photo-open" onClick={() => setViewing(p)} aria-label={`Open ${p.name}`}>
                    <img src={`${ORIGIN}${p.url}`} alt={`Photo taken ${timeAgo(p.taken_at)}`} loading="lazy" />
                  </button>
                  <figcaption>
                    <span className="when">{fresh(p) ? "Just now" : timeAgo(p.taken_at)}</span>
                    <span className="photo-actions">
                      <button className="ghost-icon" title="Send to my phone" aria-label="Send to my phone"
                              onClick={() => sendPhoto(p)}><Send /></button>
                      <button className="ghost-icon" title="Show in Finder" aria-label="Show in Finder"
                              onClick={() => revealPhoto(p)}><FolderOpen /></button>
                      <button className="ghost-icon" aria-label={arming === p.name ? "Confirm delete" : "Delete"}
                              title={arming === p.name ? "Click again to move it to the Bin" : "Delete"}
                              style={arming === p.name ? { color: "var(--danger)" } : undefined}
                              onClick={() => deletePhoto(p)}><Trash2 /></button>
                    </span>
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
        </div>
      </div>

      {viewing && (
        <div className="modal-backdrop photo-viewer" onClick={() => setViewing(null)} role="dialog"
             aria-label="Photo">
          <div className="photo-viewer-inner" onClick={(e) => e.stopPropagation()}>
            <img src={`${ORIGIN}${viewing.url}`} alt={viewing.name} />
            <div className="photo-viewer-bar">
              <span className="sub">{viewing.name}</span>
              <div className="grow" />
              <button className="btn sm" onClick={() => sendPhoto(viewing)}><Send /> Send to my phone</button>
              <button className="btn sm" onClick={() => revealPhoto(viewing)}><FolderOpen /> Show in Finder</button>
              <button className="btn sm danger" onClick={() => deletePhoto(viewing)}>
                <Trash2 /> {arming === viewing.name ? "Click again" : "Delete"}
              </button>
              <button className="icon-btn" aria-label="Close" onClick={() => setViewing(null)}><X /></button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

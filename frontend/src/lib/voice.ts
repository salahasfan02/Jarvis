/** Voice engine built on the Web Speech API (works in Chrome/Electron).
 *
 * Modes:
 *  - push-to-talk: startListening() -> one utterance -> onTranscript
 *  - wake word:    startWakeWord()  -> continuous recognition; when a wake
 *                  word is heard, the following speech becomes the command.
 */

const SR: any =
  (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

export const speechSupported = !!SR;

export interface VoiceOptions {
  language: string;
  wakeWords: string[];
  onTranscript: (text: string) => void;   // final command text
  onInterim: (text: string) => void;      // live partial text
  onWake: () => void;
  onStateChange: (state: "idle" | "listening" | "waiting-wake") => void;
  onPermissionDenied?: () => void;        // mic blocked — stop auto-restarting
}

export class VoiceEngine {
  private rec: any = null;
  private opts: VoiceOptions;
  private mode: "off" | "ptt" | "wake" = "off";
  private awake = false;

  constructor(opts: VoiceOptions) {
    this.opts = opts;
  }

  update(opts: Partial<VoiceOptions>) {
    Object.assign(this.opts, opts);
  }

  private build(continuous: boolean) {
    const rec = new SR();
    rec.lang = this.opts.language || "en-US";
    rec.continuous = continuous;
    rec.interimResults = true;
    return rec;
  }

  startListening() {
    this.stop();
    this.mode = "ptt";
    const rec = this.build(false);
    let finalText = "";
    rec.onresult = (ev: any) => {
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finalText += t;
        else interim += t;
      }
      this.opts.onInterim(finalText + interim);
    };
    rec.onend = () => {
      this.mode = "off";
      this.opts.onStateChange("idle");
      if (finalText.trim()) this.opts.onTranscript(finalText.trim());
      else this.opts.onInterim("");
    };
    rec.onerror = () => {
      this.mode = "off";
      this.opts.onStateChange("idle");
    };
    this.rec = rec;
    rec.start();
    this.opts.onStateChange("listening");
  }

  startWakeWord() {
    this.stop();
    this.mode = "wake";
    this.awake = false;
    const rec = this.build(true);
    let command = "";
    let commandTimer: any = null;

    const finishCommand = () => {
      const text = command.trim();
      command = "";
      this.awake = false;
      this.opts.onStateChange("waiting-wake");
      if (text) this.opts.onTranscript(text);
    };

    rec.onresult = (ev: any) => {
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t: string = ev.results[i][0].transcript;
        if (!this.awake) {
          const lower = t.toLowerCase();
          const wake = this.opts.wakeWords.find((w) => lower.includes(w.toLowerCase()));
          if (wake) {
            this.awake = true;
            this.opts.onWake();
            this.opts.onStateChange("listening");
            // Anything said after the wake word in the same result counts.
            const after = lower.split(wake.toLowerCase()).slice(1).join(" ").trim();
            if (after && ev.results[i].isFinal) command += after + " ";
          }
        } else {
          if (ev.results[i].isFinal) command += t + " ";
          this.opts.onInterim(command + (ev.results[i].isFinal ? "" : t));
          clearTimeout(commandTimer);
          commandTimer = setTimeout(finishCommand, 1800);
        }
      }
    };
    rec.onend = () => {
      if (this.mode === "wake") {
        try { rec.start(); } catch { /* restarting too fast is fine to ignore */ }
      }
    };
    rec.onerror = (e: any) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        this.mode = "off";
        this.opts.onStateChange("idle");
        this.opts.onPermissionDenied?.();
      }
    };
    this.rec = rec;
    rec.start();
    this.opts.onStateChange("waiting-wake");
  }

  stop() {
    this.mode = "off";
    if (this.rec) {
      this.rec.onend = null;
      try { this.rec.stop(); } catch { /* already stopped */ }
      this.rec = null;
    }
    this.opts.onStateChange("idle");
  }

  get active() {
    return this.mode !== "off";
  }
}

// ---- offline speech recognition (Whisper) -----------------------------------
//
// Same public interface as VoiceEngine, but audio is captured with
// MediaRecorder and transcribed by the local Whisper model on the backend.
// Works in every browser (no Chrome dependency, no cloud).

export class WhisperVoiceEngine {
  private opts: VoiceOptions;
  private mode: "off" | "ptt" | "wake" = "off";
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private buf = new Uint8Array(new ArrayBuffer(0));
  private generation = 0;   // bumped on stop() to cancel in-flight loops

  constructor(opts: VoiceOptions) {
    this.opts = opts;
  }

  update(opts: Partial<VoiceOptions>) {
    Object.assign(this.opts, opts);
  }

  private async ensureMic(): Promise<boolean> {
    if (this.stream?.active) return true;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      this.opts.onPermissionDenied?.();
      return false;
    }
    this.audioCtx = new AudioContext();
    const src = this.audioCtx.createMediaStreamSource(this.stream);
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 512;
    src.connect(this.analyser);
    this.buf = new Uint8Array(new ArrayBuffer(this.analyser.fftSize));
    return true;
  }

  /** Rough loudness 0..128 (deviation from silence). */
  private level(): number {
    if (!this.analyser) return 0;
    this.analyser.getByteTimeDomainData(this.buf);
    let max = 0;
    for (let i = 0; i < this.buf.length; i++) {
      max = Math.max(max, Math.abs(this.buf[i] - 128));
    }
    return max;
  }

  /** Record until the speaker goes quiet (or limits hit). Returns null if no
   *  speech was detected at all during the window. */
  private recordClip(o: { maxMs: number; silenceMs: number; waitForSpeechMs: number }):
      Promise<Blob | null> {
    return new Promise((resolve) => {
      const rec = new MediaRecorder(this.stream!);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      let spoke = false;
      let quietFor = 0;
      let waited = 0;
      const tick = 80;
      const timer = setInterval(() => {
        const loud = this.level() > 10;
        if (!spoke) {
          waited += tick;
          if (loud) spoke = true;
          else if (waited >= o.waitForSpeechMs) finish();
        } else {
          quietFor = loud ? 0 : quietFor + tick;
          if (quietFor >= o.silenceMs) finish();
        }
      }, tick);
      const hardStop = setTimeout(finish, o.maxMs);

      function finish() {
        clearInterval(timer);
        clearTimeout(hardStop);
        if (rec.state !== "inactive") rec.stop();
      }
      rec.onstop = () => resolve(spoke ? new Blob(chunks, { type: rec.mimeType }) : null);
      rec.start();
    });
  }

  private async transcribe(blob: Blob): Promise<string> {
    try {
      const { API } = await import("./api");
      const res = await fetch(`${API}/stt/transcribe`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: blob,
      });
      const data = await res.json();
      return data.text ?? "";
    } catch {
      return "";
    }
  }

  async startListening() {
    this.stop();
    if (!(await this.ensureMic())) return;
    this.mode = "ptt";
    const gen = ++this.generation;
    this.opts.onStateChange("listening");
    const blob = await this.recordClip({ maxMs: 25000, silenceMs: 1200,
                                         waitForSpeechMs: 6000 });
    if (gen !== this.generation) return;
    this.opts.onInterim("…");
    const text = blob ? await this.transcribe(blob) : "";
    this.mode = "off";
    this.opts.onInterim("");
    this.opts.onStateChange("idle");
    if (gen === this.generation && text) this.opts.onTranscript(text);
  }

  async startWakeWord() {
    this.stop();
    if (!(await this.ensureMic())) return;
    this.mode = "wake";
    const gen = ++this.generation;

    while (this.mode === "wake" && gen === this.generation) {
      this.opts.onStateChange("waiting-wake");
      // listen in short clips; silent windows are skipped without transcribing
      const clip = await this.recordClip({ maxMs: 5000, silenceMs: 900,
                                           waitForSpeechMs: 4000 });
      if (gen !== this.generation) return;
      if (!clip) continue;
      const heard = (await this.transcribe(clip)).toLowerCase();
      if (gen !== this.generation) return;
      const wake = this.opts.wakeWords.find((w) => heard.includes(w.toLowerCase()));
      if (!wake) continue;

      this.opts.onWake();
      this.opts.onStateChange("listening");
      // anything said after the wake word in the same clip starts the command
      let command = heard.split(wake.toLowerCase()).slice(1).join(" ")
        .replace(/^[\s,.!?]+/, "").trim();
      if (command.split(/\s+/).filter(Boolean).length < 2) {
        const cmdClip = await this.recordClip({ maxMs: 20000, silenceMs: 1200,
                                                waitForSpeechMs: 7000 });
        if (gen !== this.generation) return;
        this.opts.onInterim("…");
        const more = cmdClip ? await this.transcribe(cmdClip) : "";
        command = (command + " " + more).trim();
      }
      this.opts.onInterim("");
      if (gen !== this.generation) return;
      if (command) this.opts.onTranscript(command);
    }
  }

  stop() {
    this.generation++;
    this.mode = "off";
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.audioCtx?.close().catch(() => {});
    this.audioCtx = null;
    this.analyser = null;
    this.opts.onStateChange("idle");
  }

  get active() {
    return this.mode !== "off";
  }
}

// ---- text to speech ---------------------------------------------------------
//
// Speaking state + live amplitude are broadcast on `voiceBus` so the dashboard
// core visualization can react to speech:
//   voiceBus events: "speaking" (detail: boolean), "amplitude" (detail: 0..1)

export const voiceBus = new EventTarget();

/** Short rising two-tone chime confirming Jarvis heard the wake word. */
export function playWakeChime() {
  try {
    const ctx = new AudioContext();
    const now = ctx.currentTime;
    for (const [freq, start] of [[880, 0], [1318.5, 0.09]] as const) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, now + start);
      gain.gain.linearRampToValueAtTime(0.18, now + start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, now + start + 0.22);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + start);
      osc.stop(now + start + 0.25);
    }
    setTimeout(() => ctx.close().catch(() => {}), 700);
  } catch { /* audio not available */ }
}

function emitSpeaking(on: boolean) {
  voiceBus.dispatchEvent(new CustomEvent("speaking", { detail: on }));
}
function emitAmplitude(a: number) {
  voiceBus.dispatchEvent(new CustomEvent("amplitude", { detail: a }));
}

let currentAudio: HTMLAudioElement | null = null;
let ampTimer: any = null;

function cleanText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " code block omitted. ")
    .replace(/[*_#`>|]/g, "")
    .slice(0, 2500);
}

// ---- sentence queue ----------------------------------------------------------
// Sentences are enqueued as the reply streams; synthesis for the next sentence
// is PREFETCHED while the current one plays, so speech starts after the first
// sentence instead of after the whole reply.

interface QueueItem {
  text: string;
  rate: number;
  voiceName: string;
  wav: Promise<Blob | null>;   // prefetched server synthesis
}

let queue: QueueItem[] = [];
let pumping = false;
let generation = 0;

async function fetchWav(text: string): Promise<Blob | null> {
  try {
    const { serverTts } = await import("./api");
    return await serverTts(text);
  } catch {
    return null;
  }
}

/** Queue one chunk of speech (a sentence or a whole reply). */
export function enqueueSpeech(text: string, rate = 1.0, voiceName = "") {
  const clean = cleanText(text);
  if (!clean.trim()) return;
  queue.push({ text: clean, rate, voiceName, wav: fetchWav(clean) });
  void pump();
}

/** Speak a full text immediately, interrupting anything in progress. */
export function speak(text: string, rate = 1.0, voiceName = "") {
  stopSpeaking();
  enqueueSpeech(text, rate, voiceName);
}

async function pump() {
  if (pumping) return;
  pumping = true;
  const gen = generation;
  emitSpeaking(true);
  while (queue.length > 0 && gen === generation) {
    const item = queue.shift()!;
    const blob = await item.wav;
    if (gen !== generation) break;
    if (blob) await playWavReactive(blob, item.rate, gen);
    else await speakWithBrowser(item, gen);
  }
  pumping = false;
  if (gen === generation) {
    emitAmplitude(0);
    emitSpeaking(false);
  }
}

function speakWithBrowser(item: QueueItem, gen: number): Promise<void> {
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(item.text);
    u.rate = item.rate;
    if (item.voiceName) {
      const v = speechSynthesis.getVoices().find((v) => v.name === item.voiceName);
      if (v) u.voice = v;
    }
    u.onstart = () => {
      // Browser TTS exposes no audio stream — simulate a lively amplitude.
      ampTimer = setInterval(() => emitAmplitude(0.35 + Math.random() * 0.5), 90);
    };
    const end = () => {
      clearInterval(ampTimer);
      resolve();
    };
    u.onend = end;
    u.onerror = end;
    if (gen !== generation) return resolve();
    speechSynthesis.speak(u);
  });
}

/** Play a WAV with a real audio-reactive analyser driving the visualizer. */
function playWavReactive(blob: Blob, rate: number, gen: number): Promise<void> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.playbackRate = rate;
    currentAudio = audio;

    const ctx = new AudioContext();
    const source = ctx.createMediaElementSource(audio);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(ctx.destination);
    const data = new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount));

    let raf = 0;
    const tick = () => {
      analyser.getByteFrequencyData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i];
      emitAmplitude(Math.min(1, (sum / data.length / 255) * 2.2));
      raf = requestAnimationFrame(tick);
    };

    audio.onplay = () => tick();
    const end = () => {
      cancelAnimationFrame(raf);
      URL.revokeObjectURL(url);
      ctx.close().catch(() => {});
      currentAudio = null;
      resolve();
    };
    audio.onended = end;
    audio.onerror = end;
    if (gen !== generation) return end();
    audio.play().catch(end);
  });
}

export function stopSpeaking() {
  generation++;          // cancels the pump loop and any queued sentences
  queue = [];
  speechSynthesis.cancel();
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.src = "";
    currentAudio = null;
  }
  clearInterval(ampTimer);
  emitAmplitude(0);
  emitSpeaking(false);
}

export function listVoices(): SpeechSynthesisVoice[] {
  return speechSynthesis.getVoices();
}

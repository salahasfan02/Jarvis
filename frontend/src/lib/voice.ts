/** Voice engine built on the Web Speech API (works in Chrome/Electron).
 *
 * Modes:
 *  - push-to-talk: startListening() -> one utterance -> onTranscript
 *  - wake word:    startWakeWord()  -> continuous recognition; when a wake
 *                  word is heard, the following speech becomes the command.
 */

import { findWake } from "./wake";

export const voiceBus = new EventTarget();

/** What the voice pipeline is doing right now — shown in Settings → Voice
 *  ("Voice check") and used for hints, so a failure is never silent. */
export interface VoiceDiag {
  engine: "whisper" | "browser" | "none";
  mic: "off" | "starting" | "on" | "suspended" | "blocked" | "restarting" | "error";
  error: string;
  heard: { at: number; text: string; woke: boolean }[];
}
export const voiceDiag: VoiceDiag = { engine: "none", mic: "off", error: "", heard: [] };

function diag(patch: Partial<VoiceDiag>) {
  Object.assign(voiceDiag, patch);
  voiceBus.dispatchEvent(new CustomEvent("voice-diag", { detail: { ...voiceDiag } }));
}

function noteHeard(text: string, woke: boolean) {
  if (!text.trim()) return;
  diag({ heard: [{ at: Date.now(), text, woke }, ...voiceDiag.heard].slice(0, 8) });
}

const SR: any =
  (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

export const speechSupported = !!SR;

export interface VoiceOptions {
  language: string;
  wakeWords: string[];
  onTranscript: (text: string) => void;   // final command text
  onInterim: (text: string) => void;      // live partial text
  onWake: () => void;
  bargeIn?: boolean;                      // conversation mode: talking over Jarvis interrupts it
  multilingual?: boolean;                 // commands may be in Arabic (or other languages)
  onStateChange: (state: "idle" | "listening" | "waiting-wake") => void;
  onPermissionDenied?: () => void;        // mic blocked — stop auto-restarting
}

export class VoiceEngine {
  private rec: any = null;
  private opts: VoiceOptions;
  private mode: "off" | "ptt" | "wake" = "off";
  private awake = false;
  private networkErrors = 0;

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
    diag({ engine: "browser", mic: "on", error: "" });
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
      this.networkErrors = 0;
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t: string = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) noteHeard(t, !!findWake(t, this.opts.wakeWords));
        if (!this.awake) {
          const match = findWake(t, this.opts.wakeWords);
          if (match) {
            this.awake = true;
            this.opts.onWake();
            this.opts.onStateChange("listening");
            // Anything said after the wake word in the same result counts.
            if (match.command && ev.results[i].isFinal) command += match.command + " ";
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
      // A browser without a working speech service fails instantly, forever;
      // don't spin — say so (below) and stop retrying.
      if (this.mode === "wake" && this.networkErrors < 3) {
        try { rec.start(); } catch { /* restarting too fast is fine to ignore */ }
      }
    };
    rec.onerror = (e: any) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        diag({ mic: "blocked", error: "Microphone access is blocked for this page." });
        this.mode = "off";
        this.opts.onStateChange("idle");
        this.opts.onPermissionDenied?.();
      } else if (e.error === "network") {
        this.networkErrors++;
        if (this.networkErrors >= 3) {
          const msg = "This browser's speech recognition isn't available (the desktop app " +
            "and Brave don't have it). Download Whisper in Settings → Voice.";
          diag({ mic: "error", error: msg });
          this.opts.onInterim(msg);
        }
      } else if (e.error === "audio-capture") {
        diag({ mic: "error", error: "No microphone found." });
        this.opts.onInterim("No microphone found — check System Settings → Sound → Input.");
      }
    };
    this.rec = rec;
    rec.start();
    this.opts.onStateChange("waiting-wake");
  }

  stop() {
    this.mode = "off";
    this.networkErrors = 0;
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
// Same public interface as VoiceEngine; audio is transcribed by the local
// Whisper model on the backend, so it works in every browser with no cloud.
//
// The microphone is captured CONTINUOUSLY and cut into utterances by a small
// voice-activity detector that runs on the audio clock. The previous design
// recorded fixed clips with MediaRecorder and checked loudness on a timer,
// which is why the wake word was missed so often:
//  - nothing was recorded while a clip was being transcribed, and words that
//    straddled a clip boundary were cut ("Jarvis" -> "…arvis");
//  - a fixed loudness bar ignored normal speech at a distance from the mic;
//  - timers in a background tab run once a second at best, so detection fell
//    apart whenever Jarvis wasn't the front tab;
//  - if the mic dropped (AirPods, another app), the loop died silently while
//    the UI still said "listening".

const TARGET_RATE = 16000;   // what Whisper wants

/** Mono PCM -> 16-bit WAV at 16 kHz (tiny, and decodes everywhere). */
function encodeWav(chunks: Float32Array[], rate: number): Blob {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const ratio = rate / TARGET_RATE;
  const outLen = Math.floor(total / ratio);
  const pcm = new Int16Array(outLen);
  let ci = 0, offset = 0;  // walk the chunks without concatenating them
  const sampleAt = (idx: number) => {
    while (ci < chunks.length && idx - offset >= chunks[ci].length) {
      offset += chunks[ci].length;
      ci++;
    }
    return ci < chunks.length ? chunks[ci][idx - offset] : 0;
  };
  for (let i = 0; i < outLen; i++) {
    // average the source samples that fall into this output sample (anti-alias)
    const from = Math.floor(i * ratio), to = Math.max(from + 1, Math.floor((i + 1) * ratio));
    let acc = 0;
    for (let k = from; k < to; k++) acc += sampleAt(k);
    const v = Math.max(-1, Math.min(1, acc / (to - from)));
    pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  const buf = new ArrayBuffer(44 + pcm.byteLength);
  const dv = new DataView(buf);
  const str = (o: number, t: string) => [...t].forEach((c, k) => dv.setUint8(o + k, c.charCodeAt(0)));
  str(0, "RIFF"); dv.setUint32(4, 36 + pcm.byteLength, true); str(8, "WAVE");
  str(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, TARGET_RATE, true); dv.setUint32(28, TARGET_RATE * 2, true);
  dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
  str(36, "data"); dv.setUint32(40, pcm.byteLength, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], { type: "audio/wav" });
}

/** Continuous mic capture + voice-activity detection. Emits whole utterances
 *  (with pre-roll) while capture keeps running. Everything is driven by the
 *  audio callback, which browsers don't throttle in background tabs. */
class MicSegmenter {
  silenceMs = 700;          // quiet time that ends an utterance
  maxMs = 8000;             // longest utterance before it's cut anyway
  onSegment: (wav: Blob, ms: number) => void = () => {};
  onLevel: (level: number) => void = () => {};
  onSpeechStart: () => void = () => {};
  onDead: () => void = () => {};
  onSuspended: (suspended: boolean) => void = () => {};

  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private node: ScriptProcessorNode | null = null;
  private rate = 48000;
  private frameMs = 21;
  private floor = 0.002;    // running estimate of the room's noise (RMS)
  private preRoll: Float32Array[] = [];
  private segment: Float32Array[] = [];
  private segRms: number[] = [];
  private inSpeech = false;
  private loudRun = 0;
  private quietMs = 0;
  private speechMs = 0;
  private lastFrameAt = 0;
  private watchdog: any = null;
  private resumeOnGesture = () => this.ctx?.resume().catch(() => {});

  get running() { return !!this.stream?.active && !!this.ctx; }

  async start(): Promise<boolean> {
    if (this.running) return true;
    this.stop();
    try {
      // Echo cancellation keeps Jarvis's own voice out; auto gain helps quiet speech.
      // No browser noise suppression: it can clip the soft start of a word
      // ("Jar-vis"), and Whisper copes with room noise better on its own.
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: true },
      });
    } catch {
      return false;
    }
    this.ctx = new AudioContext();
    this.rate = this.ctx.sampleRate;
    const src = this.ctx.createMediaStreamSource(this.stream);
    const size = 1024;
    this.frameMs = (size / this.rate) * 1000;
    this.node = this.ctx.createScriptProcessor(size, 1, 1);
    this.node.onaudioprocess = (ev) => this.frame(ev.inputBuffer.getChannelData(0));
    src.connect(this.node);
    this.node.connect(this.ctx.destination);  // ScriptProcessor only runs when connected
    // An AudioContext made before any click starts "suspended" and hears nothing.
    this.ctx.resume().catch(() => {});
    window.addEventListener("pointerdown", this.resumeOnGesture);
    window.addEventListener("keydown", this.resumeOnGesture);
    this.stream.getAudioTracks().forEach((t) => (t.onended = () => this.onDead()));
    this.lastFrameAt = performance.now();
    // If audio stops flowing (device change, mic taken), report it so the
    // engine restarts capture instead of pretending to listen.
    let wasSuspended = false;
    this.watchdog = setInterval(() => {
      const suspended = this.ctx?.state === "suspended";
      if (suspended !== wasSuspended) this.onSuspended((wasSuspended = suspended));
      if (suspended) this.ctx!.resume().catch(() => {});
      else if (performance.now() - this.lastFrameAt > 4000) this.onDead();
    }, 1000);
    return true;
  }

  stop() {
    clearInterval(this.watchdog);
    window.removeEventListener("pointerdown", this.resumeOnGesture);
    window.removeEventListener("keydown", this.resumeOnGesture);
    if (this.node) this.node.onaudioprocess = null;
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => { t.onended = null; t.stop(); });
    this.ctx?.close().catch(() => {});
    this.node = null; this.stream = null; this.ctx = null;
    this.resetSegment();
  }

  /** Drop anything half-heard (e.g. when switching modes). */
  resetSegment() {
    this.inSpeech = false; this.segment = []; this.segRms = [];
    this.loudRun = 0; this.quietMs = 0; this.speechMs = 0;
  }

  private frame(input: Float32Array) {
    this.lastFrameAt = performance.now();
    const data = new Float32Array(input);  // the browser reuses its buffer
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    const rms = Math.sqrt(sum / data.length);
    // Speech = clearly above the room's own noise, with a floor so a silent
    // room doesn't turn breathing into "speech".
    const threshold = Math.max(this.floor * 2.5, 0.003);
    this.onLevel(Math.min(1, rms / 0.1));

    if (!this.inSpeech) {
      // follow the noise floor: quickly down, slowly up
      this.floor = rms < this.floor ? this.floor * 0.8 + rms * 0.2 : this.floor * 0.995 + rms * 0.005;
      this.preRoll.push(data);
      const keep = Math.ceil(600 / this.frameMs);   // 0.6 s before speech starts
      if (this.preRoll.length > keep) this.preRoll.shift();
      this.loudRun = rms > threshold ? this.loudRun + 1 : 0;
      if (this.loudRun >= 2) {
        this.inSpeech = true;
        this.onSpeechStart();
        this.segment = [...this.preRoll];
        this.segRms = [];
        this.preRoll = [];
        this.quietMs = 0;
        this.speechMs = 0;
      }
      return;
    }
    this.segment.push(data);
    this.segRms.push(rms);
    const loud = rms > threshold * 0.8;  // hysteresis: don't end on a soft syllable
    this.quietMs = loud ? 0 : this.quietMs + this.frameMs;
    if (loud) this.speechMs += this.frameMs;
    const segMs = this.segment.length * this.frameMs;
    if (this.quietMs >= this.silenceMs || segMs >= this.maxMs) {
      if (segMs >= this.maxMs) {
        // Constant noise (a fan, music) kept the "speech" going: learn it as
        // the new floor so it stops counting as talking.
        const sorted = [...this.segRms].sort((a, b) => a - b);
        this.floor = Math.max(this.floor, sorted[Math.floor(sorted.length / 2)] * 0.9);
      }
      const segment = this.segment, speech = this.speechMs;
      this.resetSegment();
      if (speech >= 200) this.onSegment(encodeWav(segment, this.rate), segMs);  // not a click
    }
  }
}

/** Record one utterance (for setting up the voice lock): resolves with a
 *  WAV once the speaker pauses, or null after `timeoutMs` of nothing. */
export function recordUtterance(timeoutMs = 8000): Promise<Blob | null> {
  return new Promise(async (resolve) => {
    const mic = new MicSegmenter();
    mic.silenceMs = 900;
    let done = false;
    const finish = (wav: Blob | null) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      mic.stop();
      resolve(wav);
    };
    const timer = setTimeout(() => finish(null), timeoutMs);
    mic.onSegment = (wav, ms) => { if (ms >= 1200) finish(wav); };
    if (!(await mic.start())) finish(null);
  });
}

export class WhisperVoiceEngine {
  private opts: VoiceOptions;
  private mode: "off" | "ptt" | "wake" = "off";
  private mic = new MicSegmenter();
  private queue: Blob[] = [];
  private working = false;
  private awaitingCommand = false;
  private commandTimer: any = null;
  private pttTimer: any = null;
  private generation = 0;   // bumped on stop() to drop in-flight results

  constructor(opts: VoiceOptions) {
    this.opts = opts;
    this.mic.onSegment = (wav) => { this.queue.push(wav); this.drain(); };
    // Someone talks while Jarvis speaks: turn its voice down straight away.
    this.mic.onSpeechStart = () => { if (isSpeaking()) duckSpeech(true); };
    this.mic.onLevel = (level) => voiceBus.dispatchEvent(new CustomEvent("mic-level", { detail: level }));
    this.mic.onDead = () => this.restartCapture();
    // Browsers keep audio off until the page has been clicked once; say so
    // instead of silently not hearing anything.
    this.mic.onSuspended = (suspended) => {
      diag({ mic: suspended ? "suspended" : "on" });
      this.opts.onInterim(suspended ? "Click anywhere so I can hear you" : "");
    };
  }

  update(opts: Partial<VoiceOptions>) {
    Object.assign(this.opts, opts);
  }

  private async ensureMic(): Promise<boolean> {
    diag({ engine: "whisper", mic: this.mic.running ? "on" : "starting" });
    if (await this.mic.start()) {
      diag({ mic: "on", error: "" });
      return true;
    }
    diag({ mic: "blocked", error: "Microphone access was refused — allow it for this page/app." });
    this.opts.onInterim("Microphone access was refused — allow it in your browser and in " +
                        "System Settings → Privacy & Security → Microphone.");
    this.opts.onPermissionDenied?.();
    return false;
  }

  private async restartCapture() {
    const mode = this.mode;
    if (mode === "off") return;
    diag({ mic: "restarting" });
    this.mic.stop();
    await new Promise((r) => setTimeout(r, 500));
    if (this.mode === mode && !(await this.mic.start())) {
      setTimeout(() => this.restartCapture(), 3000);  // mic busy: keep trying
    }
  }

  private async transcribe(blob: Blob, hint = "", command = false): Promise<string> {
    let error = "";
    try {
      const { API } = await import("./api");
      const res = await fetch(`${API}/stt/transcribe?hint=${encodeURIComponent(hint)}`
                              + (command ? "&command=1" : ""), {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: blob,
      });
      const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      if (data.rejected === "voice") {
        // Voice lock: not the enrolled voice (TV, someone else) — ignore it.
        noteHeard(`(ignored a voice that isn't yours — match ${Math.round((data.score ?? 0) * 100)}%)`, false);
        return "";
      }
      if (!data.error) {
        if (voiceDiag.error) diag({ error: "" });
        return data.text ?? "";
      }
      error = data.error;
    } catch (e: any) {
      error = `can't reach the Jarvis backend (${e?.message ?? e})`;
    }
    // Never fail silently: this used to return "" and the wake word just "did nothing".
    diag({ error: `Speech recognition failed: ${error}` });
    this.opts.onInterim(`Speech recognition failed: ${error}`);
    return "";
  }

  /** Transcribe utterances one at a time, in order; capture never pauses. */
  private async drain() {
    if (this.working) return;
    this.working = true;
    try {
      while (this.queue.length) {
        const wav = this.queue.shift()!;
        const gen = this.generation;
        const mode = this.mode;
        const command = mode === "ptt" || this.awaitingCommand;
        if (command) this.opts.onInterim("…");
        const hint = this.opts.wakeWords.map((w) => w[0]?.toUpperCase() + w.slice(1)).join(", ");
        // Commands go to the multilingual model when Arabic etc. is on; the
        // wake word is listened for with the (faster, more accurate) English one.
        let text = (await this.transcribe(wav, hint, command && !!this.opts.multilingual)).trim();
        if (gen !== this.generation) return;
        if (!command && this.opts.multilingual && findWake(text, this.opts.wakeWords)?.command) {
          // "Jarvis, <command>" in one breath: hear the command in any language.
          const again = (await this.transcribe(wav, hint, true)).trim();
          if (gen !== this.generation) return;
          if (again) {
            const m = findWake(again, this.opts.wakeWords);
            text = m ? again : `jarvis ${again.split(/\s+/).slice(1).join(" ")}`;
          }
        }
        noteHeard(text, command || !!findWake(text, this.opts.wakeWords));
        if (!text && isSpeaking()) duckSpeech(false);
        if (mode === "ptt") this.finishPtt(text);
        else if (mode === "wake") this.onWakeText(text);
      }
    } finally {
      this.working = false;
    }
  }

  private finishPtt(text: string) {
    clearTimeout(this.pttTimer);
    this.opts.onInterim("");
    this.mode = "off";
    this.mic.stop();
    this.opts.onStateChange("idle");
    if (text) this.opts.onTranscript(text);
  }

  private onWakeText(text: string) {
    if (isSpeaking() && !this.awaitingCommand) {
      // Talking over Jarvis. "Jarvis, …" is handled below (it stops speaking).
      if (!findWake(text, this.opts.wakeWords)) {
        const words = text.trim().split(/\s+/).filter(Boolean);
        if (/^\s*(stop|cancel|quiet|enough|shut up)\b/i.test(text)) {
          stopSpeaking();
          this.opts.onTranscript(text);   // the app treats "stop" as the emergency stop
          return;
        }
        if (this.opts.bargeIn && words.length >= 3 && !isEchoOfSpeech(text)) {
          stopSpeaking();                 // conversation mode: just answer
          this.opts.onTranscript(text);
          return;
        }
        duckSpeech(false);                // TV, someone else, or its own echo
        return;
      }
    }
    if (this.awaitingCommand) {
      // Just the wake word again ("Jarvis?") isn't a command: keep listening.
      const again = findWake(text, this.opts.wakeWords);
      if (again && !again.command) return;
      this.endCommandWindow();
      if (again?.command) this.opts.onTranscript(again.command);
      else if (text) this.opts.onTranscript(text);
      return;
    }
    const match = findWake(text, this.opts.wakeWords);
    if (!match) return;
    this.opts.onWake();
    if (match.command) {
      this.opts.onTranscript(match.command);   // "Jarvis, open YouTube" in one breath
      return;
    }
    // Just "Jarvis": the next utterance is the command.
    this.awaitingCommand = true;
    this.mic.silenceMs = 1100;  // commands get a longer pause before they end
    this.opts.onStateChange("listening");
    clearTimeout(this.commandTimer);
    this.commandTimer = setTimeout(() => this.endCommandWindow(), 8000);
  }

  private endCommandWindow() {
    clearTimeout(this.commandTimer);
    this.awaitingCommand = false;
    this.mic.silenceMs = 700;
    this.opts.onInterim("");
    if (this.mode === "wake") this.opts.onStateChange("waiting-wake");
  }

  async startListening() {
    this.generation++;
    this.queue = [];
    this.endCommandWindow();
    if (!(await this.ensureMic())) return;
    this.mode = "ptt";
    this.mic.resetSegment();
    this.mic.silenceMs = 1200;
    this.opts.onStateChange("listening");
    clearTimeout(this.pttTimer);
    this.pttTimer = setTimeout(() => {   // nothing said: give up quietly
      if (this.mode === "ptt" && !this.working) this.finishPtt("");
    }, 7000);
  }

  async startWakeWord() {
    this.generation++;
    this.queue = [];
    clearTimeout(this.pttTimer);
    if (!(await this.ensureMic())) return;
    this.mode = "wake";
    this.mic.resetSegment();
    this.endCommandWindow();
    this.opts.onStateChange("waiting-wake");
  }

  stop() {
    this.generation++;
    this.mode = "off";
    diag({ mic: "off" });
    this.queue = [];
    clearTimeout(this.pttTimer);
    clearTimeout(this.commandTimer);
    this.awaitingCommand = false;
    this.mic.stop();
    this.opts.onStateChange("idle");
  }

  get active() {
    return this.mode !== "off";
  }
}

// ---- text to speech ---------------------------------------------------------
//
// Speaking state + live amplitude are broadcast on `voiceBus` (declared at the
// top) so the dashboard core visualization can react to speech:
//   voiceBus events: "speaking" (detail: boolean), "amplitude" (detail: 0..1)

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
let currentGain: GainNode | null = null;
let ducked = false;
let spokenRecently = "";   // what Jarvis just said, to tell its echo from the user
let ampTimer: any = null;

export function isSpeaking(): boolean {
  return pumping || speechSynthesis.speaking;
}

/** Turn Jarvis's voice down while the user talks over it (and back up). */
export function duckSpeech(on: boolean) {
  ducked = on;
  if (currentGain) currentGain.gain.setTargetAtTime(on ? 0.25 : 1, currentGain.context.currentTime, 0.05);
}

/** Was this "speech" just Jarvis's own voice picked up by the mic? */
export function isEchoOfSpeech(text: string): boolean {
  const words = (s: string) => s.toLowerCase().match(/[a-z']+/g) ?? [];
  const heard = words(text);
  if (!heard.length) return true;
  const said = new Set(words(spokenRecently));
  return heard.filter((w) => said.has(w)).length / heard.length >= 0.6;
}

function cleanText(text: string): string {
  return text
    .replace(/```listing[\s\S]*?```/g, " ")   // file lists are shown, not read out
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

// Short phrases Jarvis says a lot ("One moment.") are synthesized once and
// kept, so they play with no delay.
const phraseCache = new Map<string, Promise<Blob | null>>();

async function fetchWav(text: string): Promise<Blob | null> {
  const cached = phraseCache.get(text);
  if (cached) return cached;
  try {
    const { serverTts } = await import("./api");
    return await serverTts(text);
  } catch {
    return null;
  }
}

let phraseVoice = "";

/** Synthesize these now and keep them. `voiceKey` identifies the voice: the
 *  same key again only fills in what's missing (settings reloads, React
 *  re-runs), a new key starts over. */
export function prewarmPhrases(phrases: string[], voiceKey = "") {
  if (voiceKey !== phraseVoice) {
    phraseCache.clear();
    phraseVoice = voiceKey;
  }
  for (const p of phrases) {
    const clean = cleanText(p);
    if (phraseCache.has(clean)) continue;
    phraseCache.set(clean, (async () => {
      try {
        const { serverTts } = await import("./api");
        return await serverTts(clean);
      } catch {
        return null;
      }
    })());
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
    spokenRecently = (spokenRecently + " " + item.text).slice(-600);
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
    const gain = ctx.createGain();            // lets the user talk over it (duckSpeech)
    gain.gain.value = ducked ? 0.25 : 1;
    currentGain = gain;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(gain);
    gain.connect(analyser);
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
      if (currentGain === gain) currentGain = null;
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
  ducked = false;
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

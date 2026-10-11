import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp, Code, Ear, FileText, Image as ImageIcon, MessageSquare, Mic, Paperclip, Square, X,
} from "lucide-react";
import { ChatView, ConfirmModal, ConfirmRequest, ToolChipInfo } from "./components/ChatView";
import { MatrixRain } from "./components/MatrixRain";
import { WorldMap } from "./components/WorldMap";
import { Page, Sidebar } from "./components/Sidebar";
import { API, api, Attachment, Conversation, expandSkill, Message, Skill, skillsApi } from "./lib/api";
import { enqueueSpeech, playWakeChime, speechSupported, stopSpeaking, voiceBus, VoiceEngine, WhisperVoiceEngine } from "./lib/voice";
import { ChatEvent, ChatSocket } from "./lib/ws";
import { requestFrame } from "./lib/camera";
import { CameraPage } from "./pages/CameraPage";
import { RoutinesPage } from "./pages/RoutinesPage";
import { ActivityPage } from "./pages/ActivityPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SkillsPage } from "./pages/SkillsPage";
import { DevPage } from "./pages/DevPage";
import { MemoryPage } from "./pages/MemoryPage";
import { RegistryPage } from "./pages/RegistryPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  const [page, setPage] = useState<Page>("core");
  const pageRef = useRef(page);
  pageRef.current = page;
  const [collapsed, setCollapsed] = useState(false);
  const [mode, setMode] = useState<"chat" | "code">("chat");
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [settings, setSettings] = useState<any>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [chips, setChips] = useState<ToolChipInfo[]>([]);
  const [agentName, setAgentName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [announcement, setAnnouncement] = useState<{ title: string; text: string } | null>(null);
  useEffect(() => {
    if (!announcement) return;
    const t = setTimeout(() => setAnnouncement(null), 15000);
    return () => clearTimeout(t);
  }, [announcement]);
  const [input, setInput] = useState("");
  const [voiceState, setVoiceState] = useState<"idle" | "listening" | "waiting-wake">("idle");
  const [interim, setInterim] = useState("");
  const [ollamaUp, setOllamaUp] = useState(false);

  const socket = useMemo(() => new ChatSocket(), []);
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const streamBuf = useRef("");
  const spokenRef = useRef(0);   // chars of the stream already sent to TTS
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;
  const lastInputWasVoice = useRef(false);
  const skillsRef = useRef<Skill[]>([]);
  useEffect(() => {
    const load = () => skillsApi.list().then((s) => (skillsRef.current = s)).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  // Speak completed sentences WHILE the reply streams, so Jarvis starts
  // talking after the first sentence instead of after the whole answer.
  const speakStreamedSentences = useCallback((flushAll: boolean) => {
    const st = settingsRef.current;
    if (!st?.voice?.tts_enabled) return;
    // Jarvis speaks on the Core screen (and the Camera tab it opened to look)
    // — never in the chat/code workspace.
    if (pageRef.current !== "core" && pageRef.current !== "camera") return;
    // Don't read code aloud: if we're inside an unterminated ``` fence, wait.
    const soFar = streamBuf.current;
    const fences = (soFar.match(/```/g) || []).length;
    if (!flushAll && fences % 2 === 1) return;
    const unspoken = streamBuf.current.slice(spokenRef.current);
    let cut = -1;
    if (flushAll) {
      cut = unspoken.length;
    } else {
      const re = /[.!?][)"'”]?(?=\s|$)/g;
      let m: RegExpExecArray | null;
      while ((m = re.exec(unspoken))) cut = m.index + m[0].length;
      if (cut < 40) return;   // wait for a meaty chunk; avoids "Dr." fragments
    }
    const chunk = unspoken.slice(0, cut);
    if (chunk.trim()) {
      enqueueSpeech(chunk, st.voice.tts_rate, st.voice.tts_voice);
    }
    spokenRef.current += cut;
  }, []);

  const refreshConversations = useCallback(
    (q = "") => api.conversations(q).then(setConversations).catch(() => {}),
    []
  );

  const send = useCallback((text: string, convId?: string | null) => {
    // Expand /skill shortcuts into their saved prompt template before sending.
    const content = expandSkill(text.trim(), skillsRef.current);
    if (!content) return;
    stopSpeaking();
    const target = convId !== undefined ? convId : activeIdRef.current;
    setMessages((m) => [
      ...m,
      { id: `local-${Date.now()}`, role: "user", content, meta: {}, created_at: Date.now() / 1000 },
    ]);
    setBusy(true);
    setChips([]);
    setAgentName(null);
    streamBuf.current = "";
    spokenRef.current = 0;
    setStreaming(null);
    setInput("");
    // Deliberately no navigation: talking from the Core stays on the Core.
    // Spoken requests get short, speakable answers.
    socket.chat(target, content, modeRef.current, lastInputWasVoice.current === true);
  }, [socket]);

  // ---- attachments & workspace mode ----
  const refreshAttachments = useCallback((convId: string | null) => {
    if (!convId) { setAttachments([]); return; }
    api.attachments(convId).then(setAttachments).catch(() => setAttachments([]));
  }, []);

  const uploadFiles = useCallback(async (files: FileList | File[] | null) => {
    const list = files ? Array.from(files) : [];
    if (!list.length) return;
    let convId = activeIdRef.current;
    if (!convId) {
      const conv = await api.newConversation(modeRef.current);
      convId = conv.id;
      setActiveId(conv.id);
      refreshConversations();
    }
    for (const file of list) {
      setUploading(`reading ${file.name}…`);
      try {
        const res = await fetch(
          `${API}/conversations/${convId}/attachments?name=${encodeURIComponent(file.name)}`,
          { method: "POST", body: await file.arrayBuffer(),
            headers: { "Content-Type": "application/octet-stream" } });
        const r = await res.json();
        setUploading(r.error ? `Couldn't add ${file.name}: ${r.error}` : "");
      } catch (e: any) {
        setUploading(`Couldn't add ${file.name}: ${e.message}`);
      }
    }
    refreshAttachments(convId);
  }, [refreshAttachments, refreshConversations]);

  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    if (page === "chat" || page === "projects") {
      fetch(`${API}/projects`).then((r) => r.json()).then(setProjects).catch(() => {});
    }
  }, [page]);

  const assignProject = async (projectId: string) => {
    let convId = activeIdRef.current;
    if (!convId) {
      const conv = await api.newConversation(modeRef.current);
      convId = conv.id;
      setActiveId(conv.id);
    }
    await fetch(`${API}/conversations/${convId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId || null }),
    }).catch(() => {});
    refreshConversations();
  };

  // Conversation voice mode: after Jarvis finishes speaking, reopen the mic so
  // the user can reply without repeating the wake word. Assigned once `voice`
  // exists; called via ref from the WS "done" handler.
  const maybeReopenMicRef = useRef<() => void>(() => {});

  const switchMode = (m: "chat" | "code") => {
    setMode(m);
    if (activeIdRef.current) {
      fetch(`${API}/conversations/${activeIdRef.current}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: m }),
      }).then(() => refreshConversations()).catch(() => {});
    }
  };

  // ---- websocket events ----
  useEffect(() => {
    socket.onEvent = (e: ChatEvent) => {
      switch (e.type) {
        case "conversation":
          if (activeIdRef.current !== e.conversation_id) {
            setActiveId(e.conversation_id);
            refreshConversations();
          }
          break;
        case "announce":
          // A routine or trigger fired: show it, and say it if voice is on.
          setAnnouncement({ title: e.title, text: e.text });
          if (e.speak && settingsRef.current?.voice?.tts_enabled) {
            enqueueSpeech(e.text, settingsRef.current.voice.tts_rate, settingsRef.current.voice.tts_voice);
          }
          break;
        case "ui_request":
          // A tool needs the window itself, e.g. "open the camera and tell me
          // what you see": show the Camera tab and hand back a photo.
          if (e.kind === "camera_frame") {
            setPage("camera");
            requestFrame().then(
              (image) => socket.uiResponse(e.id, { image }),
              (err: Error) => socket.uiResponse(e.id, { error: err.message }));
          } else {
            socket.uiResponse(e.id, { error: `unknown request ${e.kind}` });
          }
          break;
        case "agent":
          setAgentName(e.agent.name);
          break;
        case "token":
          streamBuf.current += e.content;
          setStreaming(streamBuf.current);
          speakStreamedSentences(false);
          break;
        case "reset_text":
          // The model wrote a tool call as text; the backend ran it as a real
          // call, so drop that text from the reply.
          streamBuf.current = e.content;
          spokenRef.current = Math.min(spokenRef.current, e.content.length);
          setStreaming(e.content || null);
          break;
        case "tool_start":
          setChips((c) => [...c.filter((x) => !(x.name === e.name && x.status === "running")),
                           { name: e.name, status: "running" }]);
          break;
        case "tool_result": {
          const status: ToolChipInfo["status"] = e.denied ? "denied" : "done";
          setChips((c) => {
            const updated: ToolChipInfo[] = c.map((x) =>
              x.name === e.name && x.status === "running"
                ? { ...x, status, result: e.result }
                : x
            );
            if (!c.some((x) => x.name === e.name)) {
              updated.push({ name: e.name, status, result: e.result });
            }
            return updated;
          });
          break;
        }
        case "confirm_request":
          setConfirm({ id: e.id, tool: e.tool, arguments: e.arguments, risk: e.risk,
                       always_ask: e.always_ask });
          break;
        case "plan":
          setChips(e.steps.map((s, i) => ({
            name: `${i + 1}. ${s.length > 60 ? s.slice(0, 57) + "…" : s}`,
            status: "pending" as const,
          })));
          break;
        case "step":
          setChips((c) => c.map((chip, i) =>
            i === e.index ? { ...chip, status: e.status } : chip));
          break;
        case "done": {
          setBusy(false);
          setStreaming(null);
          setChips([]);
          setAgentName(null);
          const id = activeIdRef.current;
          if (id) api.messages(id).then(setMessages).catch(() => {});
          streamBuf.current = e.content;      // speak whatever trailed the last "."
          speakStreamedSentences(true);
          maybeReopenMicRef.current();
          break;
        }
        case "title":
          refreshConversations();
          break;
        case "stopped":
          setBusy(false);
          setStreaming(null);
          setChips([]);
          stopSpeaking();
          break;
        case "error":
          setBusy(false);
          setStreaming(null);
          setChips([]);
          setMessages((m) => [
            ...m,
            { id: `err-${Date.now()}`, role: "assistant", content: `**Error:** ${e.message}`, meta: {}, created_at: Date.now() / 1000 },
          ]);
          break;
      }
    };
    socket.connect();
  }, [socket, refreshConversations]);

  // ---- initial load + status polling ----
  useEffect(() => {
    api.settings().then(setSettings).catch(() => {});
    refreshConversations();
    const poll = () => api.status().then((s) => setOllamaUp(s.ollama_up)).catch(() => setOllamaUp(false));
    poll();
    const t = setInterval(poll, 5000);
    return () => clearInterval(t);
  }, [refreshConversations]);

  // ---- voice ----
  // Whisper (offline, any browser) is preferred; browser recognition is the
  // fallback while the Whisper model isn't downloaded yet.
  const [sttReady, setSttReady] = useState(false);
  useEffect(() => {
    const check = () =>
      fetch(`${API}/stt/status`).then((r) => r.json())
        // A failed check (backend busy or restarting) keeps the current engine:
        // switching engines drops the microphone mid-sentence.
        .then((s) => setSttReady(!!s.available)).catch(() => {});
    check();
    const t = setInterval(check, 20000);
    return () => clearInterval(t);
  }, [settings]);

  const useWhisper = (settings?.voice?.stt_engine ?? "whisper") === "whisper" && sttReady;

  // The engine is built once per engine type; it reaches `send` through a ref
  // so re-renders never tear down the microphone.
  const sendRef = useRef(send);
  sendRef.current = send;
  const voice = useMemo(() => {
    const opts = {
      language: "en-US",
      wakeWords: settingsRef.current?.assistant?.wake_words ?? ["jarvis"],
      onTranscript: (text: string) => {
        // "Stop" / "cancel": the emergency stop — halt clicking/typing and
        // the running reply, don't send it as a new request.
        if (/^\s*(?:(?:jarvis|hey jarvis)[\s,]+)?(?:stop|cancel|abort|stop it|stop that|stop now)[\s.!]*$/i.test(text)) {
          stopSpeaking();
          socket.stop();
          fetch(`${API}/screen/stop`, { method: "POST", headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({ reason: "voice" }) }).catch(() => {});
          return;
        }
        lastInputWasVoice.current = true; sendRef.current(text);
      },
      onInterim: setInterim,
      onWake: () => {
        stopSpeaking();
        playWakeChime();   // audible confirmation that Jarvis is listening
        // While the user says the command, make sure the model has the prompt
        // opening ready (usually cached already; see chat/prefetch.py).
        fetch(`${API}/chat/prefetch`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation_id: activeIdRef.current }),
        }).catch(() => {});
      },
      onStateChange: setVoiceState,
      onPermissionDenied: () => setWakeWanted(false),
    };
    if (useWhisper) return new WhisperVoiceEngine(opts);
    if (!speechSupported) return null;
    return new VoiceEngine(opts);
  }, [useWhisper]);  // eslint-disable-line react-hooks/exhaustive-deps

  // stop the previous engine whenever the engine instance is replaced
  useEffect(() => () => voice?.stop(), [voice]);

  maybeReopenMicRef.current = () => {
    const st = settingsRef.current;
    if (!st?.voice?.conversation_mode || !voice) return;
    if (lastInputWasVoice.current !== true) return;  // only continue voice turns
    voiceBusIdle().then(() => {
      if (!busyRef.current && (pageRef.current === "core" || pageRef.current === "camera")) {
        voice.startListening();
      }
    });
  };

  useEffect(() => {
    if (voice && settings) {
      voice.update({
        language: settings.voice?.language ?? "en-US",
        wakeWords: settings.assistant?.wake_words ?? ["jarvis"],
        bargeIn: !!settings.voice?.conversation_mode,
      });
    }
  }, [voice, settings]);

  // Always-on wake word: as long as voice is enabled and nothing else is
  // using the microphone, keep listening for "Jarvis…" — so speaking the
  // wake word on the Core works without touching anything.
  const [wakeWanted, setWakeWanted] = useState<boolean | null>(null);
  useEffect(() => {
    if (wakeWanted === null && settings && voice) {
      setWakeWanted(settings.voice?.enabled !== false);
    }
  }, [settings, wakeWanted, voice]);
  useEffect(() => {
    if (!voice || !wakeWanted) return;
    if (voiceState === "idle") {
      const t = setTimeout(() => {
        try { voice.startWakeWord(); } catch { /* mic busy or denied */ }
      }, 400);
      return () => clearTimeout(t);
    }
  }, [voice, wakeWanted, voiceState]);

  const toggleWake = () => {
    if (voiceState === "waiting-wake" || wakeWanted) {
      voice?.stop();
      setWakeWanted(false);
      patchSettings({ voice: { wake_word_enabled: false } });
    } else {
      setWakeWanted(true);
      patchSettings({ voice: { wake_word_enabled: true } });
    }
  };

  // ---- theme ----
  useEffect(() => {
    const root = document.documentElement;
    const theme = settings?.ui?.theme ?? "hacker";
    root.dataset.theme = theme === "system"
      ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : theme;

    // custom accent color overrides the theme's accent everywhere
    const accent: string = settings?.ui?.accent ?? "";
    if (/^#[0-9a-fA-F]{6}$/.test(accent)) {
      root.style.setProperty("--accent", accent);
      const r = parseInt(accent.slice(1, 3), 16);
      const g = parseInt(accent.slice(3, 5), 16);
      const b = parseInt(accent.slice(5, 7), 16);
      root.style.setProperty("--core-rgb", `${r}, ${g}, ${b}`);
    } else {
      root.style.removeProperty("--accent");
      root.style.removeProperty("--core-rgb");
    }

    // custom background color (hex) overrides the theme background
    const bg: string = settings?.ui?.background ?? "";
    if (/^#[0-9a-fA-F]{6}$/.test(bg)) root.style.setProperty("--bg", bg);
    else root.style.removeProperty("--bg");
  }, [settings]);

  const bgKind: string = settings?.ui?.background ?? "";
  const bgPicture = bgKind.startsWith("image:")
    ? `${API}/backgrounds/file/${encodeURIComponent(bgKind.slice(6))}` : "";
  const animatedBg = bgKind === "matrix" || bgKind === "world" || !!bgPicture;

  const patchSettings = (patch: any) => {
    setSettings((s: any) => {
      const next = structuredClone(s);
      deepMerge(next, patch);
      return next;
    });
    api.updateSettings(patch).then(setSettings).catch(() => {});
  };

  const openConversation = (id: string) => {
    setActiveId(id);
    setPage("chat");
    api.messages(id).then(setMessages).catch(() => {});
    const conv = conversations.find((c) => c.id === id);
    setMode(conv?.mode === "code" ? "code" : "chat");
    refreshAttachments(id);
  };

  const newChat = () => {
    setActiveId(null);
    setMessages([]);
    setAttachments([]);
    setPage("chat");
    stopSpeaking();
    inputRef.current?.focus();
  };

  const deleteConversation = (id: string) => {
    api.deleteConversation(id).then(() => {
      refreshConversations();
      if (id === activeId) newChat();
    });
  };

  const editMessage = (m: Message) => {
    if (!activeId) return;
    api.truncate(activeId, m.id).then(() => {
      api.messages(activeId).then(setMessages);
      setInput(m.content);
      inputRef.current?.focus();
    });
  };

  const regenerate = (_m: Message) => {
    if (!activeId) return;
    const lastUser = [...messages].reverse().find((x) => x.role === "user");
    if (!lastUser) return;
    api.truncate(activeId, lastUser.id).then(() => {
      setMessages((msgs) => msgs.slice(0, msgs.findIndex((x) => x.id === lastUser.id)));
      send(lastUser.content, activeId);
    });
  };

  const onComposerKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!busy) { lastInputWasVoice.current = false; send(input); }
    }
  };

  // resolves once Jarvis has finished speaking (or immediately if silent)
  const voiceBusIdle = () => new Promise<void>((resolve) => {
    let speaking = false;
    const onSpeak = (ev: Event) => { speaking = (ev as CustomEvent).detail; };
    voiceBus.addEventListener("speaking", onSpeak);
    // give TTS a moment to start; then wait until it stops
    setTimeout(() => {
      const check = setInterval(() => {
        if (!speaking) {
          clearInterval(check);
          voiceBus.removeEventListener("speaking", onSpeak);
          resolve();
        }
      }, 250);
    }, 600);
  });

  const voiceEnabled = settings?.voice?.enabled !== false && voice !== null;

  return (
    <>
    {bgKind === "matrix" && <MatrixRain />}
    {bgKind === "world" && <WorldMap />}
    {bgPicture && (
      <div className="bg-picture" style={{ backgroundImage: `url("${bgPicture}")` }}>
        <div className="bg-picture-dim" style={{ opacity: settings?.ui?.background_dim ?? 0.45 }} />
      </div>
    )}
    <div className={`app ${settings?.ui?.glass !== false ? "glass" : ""} ${animatedBg ? "matrix-bg" : ""}`}>
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        page={page}
        busy={busy}
        ollamaUp={ollamaUp}
        model={settings?.ollama?.model ?? ""}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        onNewChat={newChat}
        onSelect={openConversation}
        onDelete={deleteConversation}
        onSearch={(q) => refreshConversations(q)}
        onPage={setPage}
      />

      <div className="main">
        {page === "chat" && (
          <div className="workspace"
               onDragOver={(e) => e.preventDefault()}
               onDrop={(e) => { e.preventDefault(); uploadFiles(e.dataTransfer.files); }}>
            <div className="workspace-header">
              <div className="mode-toggle">
                <button className={mode === "chat" ? "active" : ""}
                        onClick={() => switchMode("chat")}><MessageSquare /> Chat</button>
                <button className={mode === "code" ? "active" : ""}
                        onClick={() => switchMode("code")}><Code /> Code</button>
              </div>
              {mode === "code" && (
                <span className="workspace-hint">
                  senior-engineer mode · code blocks are runnable
                </span>
              )}
              <div style={{ flex: 1 }} />
              <select
                className="project-select"
                title="Assign this conversation to a project"
                value={conversations.find((c) => c.id === activeId)?.project_id ?? ""}
                onChange={(e) => assignProject(e.target.value)}
              >
                <option value="">No project</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>Project: {p.name}</option>
                ))}
              </select>
            </div>
            <ChatView
              messages={messages}
              streaming={busy ? streaming ?? "" : null}
              chips={chips}
              agentName={agentName}
              busy={busy}
              onEdit={editMessage}
              onRegenerate={regenerate}
              onCopy={(t) => navigator.clipboard.writeText(t)}
              onSuggestion={(s) => { lastInputWasVoice.current = false; send(s); }}
              assistantName={settings?.assistant?.name ?? "Jarvis"}
            />
            {(attachments.length > 0 || uploading) && (
              <div className="attach-row">
                {attachments.map((a) => (
                  <span key={a.id} className="chip">
                    {a.kind === "image" ? <ImageIcon /> : <FileText />} {a.name}
                    <button className="chip-x" title="Remove"
                            onClick={() => api.deleteAttachment(a.id)
                              .then(() => refreshAttachments(activeIdRef.current))}>
                      <X className="icon-sm" />
                    </button>
                  </span>
                ))}
                {uploading && <span className="chip">{uploading}</span>}
              </div>
            )}
            <div className="composer-wrap">
              <div className="composer">
                <button className="icon-btn" title="Attach files or images"
                        onClick={() => fileInputRef.current?.click()}>
                  <Paperclip />
                </button>
                <input ref={fileInputRef} type="file" multiple style={{ display: "none" }}
                       onChange={(e) => { uploadFiles(e.target.files); e.target.value = ""; }} />
                {voiceEnabled && (
                  <button
                    className={`icon-btn ${voiceState === "listening" ? "recording" : ""}`}
                    title="Push to talk"
                    onClick={() => voiceState === "idle" ? voice?.startListening() : voice?.stop()}
                  >
                    <Mic />
                  </button>
                )}
                {voiceEnabled && (
                  <button
                    className={`icon-btn ${voiceState === "waiting-wake" ? "wake-on" : ""}`}
                    title={`Wake word ("${(settings?.assistant?.wake_words ?? ["jarvis"])[0]}")`}
                    onClick={() => voiceState === "waiting-wake" ? voice?.stop() : voice?.startWakeWord()}
                  >
                    <Ear />
                  </button>
                )}
                <textarea
                  ref={inputRef}
                  rows={1}
                  placeholder={busy ? "Thinking…"
                    : mode === "code" ? "Describe what to build, debug or refactor…"
                    : `Message ${settings?.assistant?.name ?? "Jarvis"}…`}
                  value={input}
                  onChange={(e) => {
                    setInput(e.target.value);
                    e.target.style.height = "auto";
                    e.target.style.height = Math.min(e.target.scrollHeight, 180) + "px";
                  }}
                  onKeyDown={onComposerKey}
                  onPaste={(e) => {
                    const files = Array.from(e.clipboardData.files);
                    if (files.length) {
                      e.preventDefault();
                      uploadFiles(files);
                    }
                  }}
                />
                {busy ? (
                  <button className="icon-btn" title="Stop" onClick={() => socket.stop()}><Square /></button>
                ) : (
                  <button className="icon-btn primary" title="Send" disabled={!input.trim()}
                          onClick={() => { lastInputWasVoice.current = false; send(input); }}><ArrowUp /></button>
                )}
              </div>
              <div className="voice-hint">
                {voiceState === "waiting-wake" && !interim && `Listening for "${(settings?.assistant?.wake_words ?? ["jarvis"])[0]}"…`}
                {(voiceState === "listening" || interim) && (interim || "Listening…")}
              </div>
            </div>
          </div>
        )}
        {page === "core" && (
          <DashboardPage
            busy={busy}
            listening={voiceState === "listening"}
            assistantName={settings?.assistant?.name ?? "Jarvis"}
            onCommand={(text) => { lastInputWasVoice.current = false; send(text); }}
            lastUser={[...messages].reverse().find((m) => m.role === "user")?.content ?? null}
            reply={busy ? streaming
                        : [...messages].reverse().find((m) => m.role === "assistant")?.content ?? null}
            chips={chips}
            interim={interim}
            voiceState={voiceState}
            wakeWord={(settings?.assistant?.wake_words ?? ["jarvis"])[0]}
            wakeActive={voiceState === "waiting-wake"}
            voiceSupported={voice !== null && settings?.voice?.enabled !== false}
            voiceEngine={useWhisper ? "whisper" : "browser"}
            onToggleWake={toggleWake}
            onPushToTalk={() =>
              voiceState === "listening" ? voice?.stop() : voice?.startListening()}
            coreDesign={settings?.ui?.core_design ?? "orb"}
            onCycleDesign={() => {
              const order = ["orb", "reactor", "halo", "nebula"];
              const current = settings?.ui?.core_design ?? "orb";
              const next = order[(order.indexOf(current) + 1) % order.length];
              patchSettings({ ui: { core_design: next } });
            }}
          />
        )}
        {page === "projects" && <ProjectsPage onOpenConversation={openConversation} />}
        {page === "skills" && <SkillsPage />}
        {page === "routines" && <RoutinesPage />}
        {page === "activity" && <ActivityPage />}
        {page === "camera" && (
          <CameraPage speakReplies={settings?.voice?.tts_enabled ?? false}
                      jarvisReply={busy ? streaming
                        : [...messages].reverse().find((m) => m.role === "assistant")?.content ?? null} />
        )}
        {page === "settings" && <SettingsPage settings={settings} onPatch={patchSettings} />}
        {page === "memory" && <MemoryPage />}
        {page === "dev" && <DevPage />}
        {page === "registry" && (
          <RegistryPage onFixIt={(g) => {
            // Fix-it opens a fresh CODE-mode conversation with the request staged
            setActiveId(null);
            setMessages([]);
            setAttachments([]);
            setMode("code");
            setPage("chat");
            setInput(
              `Write a new tool plugin for my Jarvis assistant (Python) that adds this missing capability:\n\n` +
              `CAPABILITY: ${g.capability}\n` +
              (g.goal ? `GOAL: ${g.goal}\n` : "") +
              (g.reason ? `WHY IT FAILED BEFORE: ${g.reason}\n` : "") +
              (g.suggested_fix ? `SUGGESTED APPROACH: ${g.suggested_fix}\n` : "") +
              `\nThe plugin must be a single plugin.py file for the folder ` +
              `~/.jarvis/plugins/${g.capability.toLowerCase().replace(/[^a-z0-9]+/g, "_")}/ using this exact framework:\n\n` +
              `from app.tools.base import tool\n\n` +
              `@tool(\n    name="tool_name",\n    description="what it does (the LLM reads this to decide when to call it)",\n` +
              `    parameters={"type": "object", "properties": {"arg": {"type": "string"}}, "required": ["arg"]},\n` +
              `    risk="safe",  # safe | confirm | dangerous\n)\n` +
              `def tool_name(arg: str) -> str:\n    ...\n\n` +
              `Handlers can be sync or async and must return a string. Use AppleScript via ` +
              `subprocess osascript for Mac app control, or httpx for web APIs. Include all ` +
              `imports. When it looks right, install it with the create_skill tool.`
            );
          }} />
        )}
      </div>

      {announcement && (
        <div className="announce" role="status" onClick={() => setAnnouncement(null)}>
          <div className="announce-title">{announcement.title}</div>
          <div className="announce-text">{announcement.text}</div>
        </div>
      )}
      {confirm && (
        <ConfirmModal
          request={confirm}
          onResolve={(approved, remember) => {
            socket.confirm(confirm.id, approved, confirm.tool, remember);
            setConfirm(null);
          }}
        />
      )}
    </div>
    </>
  );
}

function deepMerge(base: any, patch: any) {
  for (const k of Object.keys(patch)) {
    if (patch[k] && typeof patch[k] === "object" && !Array.isArray(patch[k]) && base[k]) {
      deepMerge(base[k], patch[k]);
    } else {
      base[k] = patch[k];
    }
  }
}

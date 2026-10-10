# Architecture

## Message lifecycle

```
UI (React) ── WebSocket /api/ws/chat ──> chat/service.run_chat()
    1. persist user message (SQLite)
    1b. instant command?        chat/quick.match() — "open youtube", "pause":
                                run the tool directly, canned reply, no model
    2. memory recall  ┐ concurrently, sharing one cached embedding
    3. agent routing  ┘ agents/registry.route() (a short reply to a question
                        keeps the previous agent)
    4. LLM streaming            llm/ollama_client.chat_stream()  + tool schemas
                                prompt = [static system] + history (incl. earlier
                                tool results) + <context>…</context> on the
                                newest user message only
    5. tool-calling loop        tools/base.execute()
         · safe tools run immediately
         · confirm/dangerous -> confirm_request event -> UI dialog -> resume
    6. persist assistant message, auto-title, stream `done`
```

All server→client events are small JSON objects (`token`, `tool_start`,
`confirm_request`, `done`, …) — see `frontend/src/lib/ws.ts` for the full
union type.

## Key decisions

- **The prompt prefix never changes.** Ollama reuses its work for an
  unchanged prefix, and its templates put every system message before the
  tool schemas — so per-message facts (time, current app, memories) go on
  the newest user message, never in a system note. Otherwise each message
  re-reads thousands of tokens of tool schemas.

- **No hardcoded models.** `settings.ollama.model` is read at call time;
  changing it in Settings affects the next message.
- **Confirmation is a Future.** The chat loop yields a `confirm_request`
  event and awaits an `asyncio.Future` the WebSocket resolves when the user
  clicks Allow/Deny. Timeouts (5 min) count as denial.
- **Agents are prompt + tool subset.** Routing is one cheap non-streamed
  LLM call that returns an agent id; any failure falls back to the
  generalist, so routing can never break chat.
- **Memory degrades gracefully.** With an embedding model configured,
  recall is cosine similarity; without one it's keyword overlap. Both use
  the same SQLite table.
- **Voice lives in the frontend.** Web Speech API gives streaming STT and
  TTS with zero install; the engine is isolated in `lib/voice.ts` so it can
  be swapped for whisper.cpp/Piper via backend endpoints later.

## Adding a tool

```python
# backend/app/tools/builtin/mytools.py  (import it in main.py)
from ..base import tool

@tool(
    name="say_hi",
    description="Greets someone by name.",
    parameters={"type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]},
    risk="safe",              # safe | confirm | dangerous
    agent_tags=["automation"] # which agents see it; [] = all
)
def say_hi(name: str) -> str:
    return f"Hi {name}!"
```

Handlers may be sync or async; return a string the model can read. Sync
handlers run in a worker thread so a slow one can't stall the server — a
handler that schedules asyncio tasks or touches the event loop must be
`async def`.

## Adding an agent

Call `agents.registry.register(Agent(id=..., name=..., description=...,
prompt=..., tool_tags=[...]))`. The router LLM sees `description`; the model
sees `prompt`.

## Plugins

A plugin is a folder with `plugin.py` in `~/.jarvis/plugins/` or the repo's
`plugins/`. It uses the same `@tool` decorator (`from app.tools.base import
tool`). Loaded at startup or via POST `/api/plugins/reload` (Developer page
button). A failing plugin is reported, never fatal.

## Self-improvement pipeline (v2)

After every `done` event, `gaps.schedule_analysis()` fires a non-blocking LLM
call (JSON-schema constrained) that judges whether the request was fulfilled.
Failures become structured entries in the `capability_gaps` table; repeats are
deduplicated by word-overlap on the capability name and bump `count`, which
drives priority (`gaps/registry.py::priority_for`). `POST /api/gaps/report`
renders the registry into a weekly markdown report (saved in
`~/.jarvis/reports/`) with an LLM-written roadmap section. A user denying a
permission is deliberately NOT counted as a failure.

## Context awareness (v2)

`automation/context.py` snapshots the frontmost app, browser tabs and Music
state via AppleScript (cached ~3s, with a 2-minute backoff when Automation
permission is missing). The summary is injected into the system prompt along
with smart-window rules, and the browser tools enforce them mechanically:
`browser_open` reuses an existing same-site tab and only creates windows when
`new_window=true`; `youtube_play` targets the existing YouTube tab.

## Voice engines (v2)

`speech/engines.py` defines a tiny `TTSEngine` interface. `/api/tts/speak`
returns WAV bytes when the configured engine synthesizes server-side (Piper),
or `{"engine": "browser"}` to hand off to Web Speech. The frontend plays
server WAVs through a WebAudio analyser, so the dashboard core pulses to the
actual waveform. Add XTTS-v2 / Kokoro / a cloned voice by subclassing
`TTSEngine` and calling `register()` — the Settings dropdown lists engines
from `/api/tts/engines` automatically.

## Remote channels: the phone (v3)

`channels/telegram.py` long-polls the Telegram Bot API (outbound only — no
webhook or tunnel) and turns each message into an ordinary `run_chat()` turn,
so phone chats get the same agents, memory, tools and permission checks as
the desktop. Each Telegram chat maps to one conversation (folder `Phone`).

```
Telegram ─ getUpdates ─> TelegramBot.handle()      (poll loop: fast routing only)
   paired user? ── no ──> ignored ("/pair <code>" from Settings → Phone)
   pending question? ───> yes/no or Allow/Deny button resolves the Future
   else per-chat queue ─> worker: download file / transcribe voice note
                          ─> run_chat() with channels.current = TelegramSession
                               tool_start       -> one edited status message
                               confirm_request  -> Allow/Deny buttons
                               done             -> HTML reply (+ voice note)
```

- `channels.current` (a ContextVar) is set for the turn. `send_file` uses it
  to deliver to the chat the request came from; at the desk it just reveals
  the file in Finder.
- Remote turns add `REMOTE_TOOL_TAGS` (`remote`, `files`, `research`) to the
  routed agent's tools, so "find X and send it" and "research Y into a Word
  doc" work whichever agent the router picks.
- `_execute_with_permission` blocks `dangerous` tools on remote turns unless
  `telegram.allow_dangerous` is on (confirmation still applies then).
- The bot token lives in `~/.jarvis/telegram_token` (mode 600), never in
  `settings.json`; the update offset is persisted so a restart never replays
  a request.

A new channel (e.g. Twilio voice calls) subclasses `channels.ChannelSession`
(`name`, `allow_dangerous`, `send_file`) and drives `run_chat()` the same way.

## Roadmap hooks (already scaffolded)

- `backend/app/speech/` — server-side whisper/faster-whisper endpoints for
  fully offline STT; the frontend voice engine is the only file to change.
- `backend/app/vision/` — richer OCR (Apple Vision via pyobjc), live camera
  streaming, UI-element detection for click-by-description.
- `backend/app/automation/` — Accessibility-API window management
  (move/resize/click) beyond AppleScript.
- Meeting transcription: reuse the STT endpoint with speaker diarization,
  store transcripts as conversations tagged `folder="meetings"`.

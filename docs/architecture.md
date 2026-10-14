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

A tool can also take `prepare=fn`: it runs *before* the permission check and
returns the arguments to ask about and run with — or a string, to answer
without running. `facetime_call` uses it to look up "Salah's business
number", so the confirmation shows the actual person and number.

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
  to deliver to the chat the request came from; at the desk it goes to the
  paired phone (`telegram.owner()`), or reveals the file in Finder when no
  phone is paired.
- `send_to_phone` is "send that to me": the previous answer, the whole
  conversation (`channels.conversation` names it), or either as a Word file.
  Content comes from the database, so a long answer isn't retyped by the
  model; an answer that made a document sends the document.
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

## Web research (v4)

`tools/builtin/research.py` does the reading a 14B model with an 8k context
can't: search (DuckDuckGo, then Bing), fetch the top pages in parallel,
pull out each page's main text (trafilatura), split it into passages and
keep the few closest in meaning to the question (the embedding model). The
model gets a short numbered digest and answers with `[n]` citations; the
chat service appends the Sources list (`_with_sources`), and the UI turns
`[n]` into links. `research_report` writes the same into a Word document.

- Pages download in parallel but are parsed **one at a time on one thread**
  (`_PAGE_READER`): trafilatura shares one lxml parser, and two threads
  parsing at once crashed the backend.
- `weather.py` answers forecasts from Open-Meteo directly (no key), for the
  city in the profile, else where the internet connection is.

## Keeping the model honest (v4)

`chat/service.py` checks what the model says against what its tools did:

- **Claims** ("I've sent it") with no tool behind them get one push to
  actually do it; a claim that survives is cut from the reply.
- **"No"** is respected — after a denial nothing pushes it to act anyway.
- **Make before send** — "write X and send it to me" sorts the calls so the
  file exists before it's sent; a guessed path is swapped for the real one.
- **No repeats** — after sending an answer to the phone, a reply that copies
  that answer (runs of its words) becomes the short confirmation.
- **Research first** — a document "about" a topic is researched before it's
  written, and an email that mentions an attachment must carry one.

## Apple Music (v4)

`music_play` tries the user's library first (AppleScript). Otherwise it
finds the song in the Apple Music catalogue (Apple's iTunes Search API,
`best_match` prefers the asked-for artist over remixes), opens it in Music
with `music://…?i=<track>`, selects its row through Accessibility and uses
*Play Next*, then skips to it — so nothing is added to the library. Music
requests go to Apple Music unless the user says YouTube or video
(`_music_service`).

## Smart lights (v4)

`lights.py` controls Tapo / Kasa lights on the local network with
python-kasa. Connecting uses the Tapo account once: each light's derived key
(`credentials_hash`) is saved in `~/.jarvis/lights.json` (mode 600), never
the password. Lights are told apart from cameras by the family they announce
before sign-in (`SMART.TAPOBULB`), found again by MAC if their address
changes, and a light that doesn't answer is skipped for a minute so status
checks never stall.

macOS's Local Network privacy can block an app without ever asking (a known
macOS bug). So the network work runs in `lights_helper.py`: a small Python
process started with `posix_spawn` as its **own responsible process**
(`responsibility_spawnattrs_setdisclaim`), which macOS lists — and the user
allows — as *Python*, while every other permission stays Jarvis's. It reads
JSON requests on stdin, answers on stdout, restarts if it stops and exits
with Jarvis. `JARVIS_LIGHTS_DIRECT=1` (tests, other OSes) runs in-process.

## Calls (v5)

`tools/builtin/facetime.py`: *"FaceTime Salah's business number"* (also an
instant command in `chat/quick.py`) → `facetime_call(contact=…, kind=video|audio|phone)`.

- **Who and which number** — `parse()` takes the number words out of the
  name ("business number" → work, "mobile", "home", "iCloud"); `candidates()`
  looks the person up in Jarvis's saved people first, then Contacts with
  *every* labelled number and address (`people.contact_cards`). A wanted
  label must exist — "no work number saved" is reported, never guessed; an
  unlabelled saved number counts as a mobile. Two people by that name →
  "which one?".
- **Ask first, with the facts** — the tool's `prepare` step resolves all of
  that before the confirmation, so the dialog shows "Salah Asfan, +44 20 …
  (work)"; a lookup that fails answers without a dialog. It always works
  from `contact` — a name or number the model adds itself is ignored, so
  what's shown is what's dialled — and calls are `always_ask` (like sending
  email): a misheard name or a number planted in something the model read
  never rings unseen.
- **Dialling** — `facetime://`, `facetime-audio://` or `tel://` (through the
  iPhone). macOS then shows its own Call prompt; with Accessibility, Jarvis
  finds that button in Notification Center (AX tree) and presses it — unless
  an older prompt is still up, which could be someone else's.
- Calls never start from the phone or a routine — nobody's at the Mac to talk.

## Photos (v5)

`take_photo` asks the Jarvis window for a `camera_photo` (`ui_bridge`): the
Camera tab opens, counts down (3 s by default) and flashes, and the picture
comes back to be saved by `vision/photos.py` in `~/Pictures/Jarvis`
(`photo-<date>-<time>.jpg` — no spaces, so a model passes paths on intact).
No window → `imagesnap`. *"Undo that"* moves it to the Bin.

Sending: `ChannelSession.send_photo` — Telegram's `sendPhoto`, so it shows in
the chat (files over 10 MB, or ones Telegram refuses, go as a document).
`send_file` uses it for Jarvis's own photos, `send_to_phone(what="photo")`
sends the last one taken in the chat ("send me that picture"), and
`take_photo(send_to_phone=true)` does both in one call. The chat loop counts
it as making a file ("take a photo and email it to Sam") and as sending one.
The Camera page lists the photos (`/api/photos`) with send / show / delete.

## Agent teams (v5)

A team is a graph the user draws in the Agent teams tab: agents (name, role
= instructions, skills, optional model, canvas position) and links ("A hands
work to B"). One agent is the lead — the one the user talks to.
`teams/store.py` keeps each team as one JSON document (normalized on save:
unique ids and names, links only between agents that exist, a lead always
set) plus templates (the Startup team: main → market research, backend,
frontend, marketing).

`teams/engine.py` runs one team at a time, in the background:

```
_turn(agent, brief):
   has teammates? → plan (JSON schema: requirements + assignments
                    [{agent ∈ teammate names, brief}], in working order)
                  → each teammate: handoff → _turn(teammate, its brief,
                    + what earlier teammates produced) → report
                  → combine the reports into one answer
   else           → work: its role, its skills' tools, up to 5 tool rounds
```

- **Skills are safe by construction**, so a run never stops to ask:
  `research` (research / web_search / web_fetch, through `tools.execute`)
  and `files` (save_file / read_file / list_files, confined to the run's
  workspace `~/.jarvis/projects/teams/<team>-<time>/`). That folder is served
  at `/projects/…` with the CSP sandbox, so a page an agent saves is live
  ("deployed") but can't reach Jarvis's API — and has no storage, which the
  agents are told.
- Cycles are cut (a teammate never hands work back up its own chain), depth
  is capped, a failing teammate is reported to its lead instead of sinking
  the run, and long conversations shrink their oldest tool results.
- Every step is an event (`agent_status`, `handoff`, `agent_plan`,
  `agent_token`, `agent_tool`, `file`, `report`, `final`, `done`).
  `GET /api/teams/runs/{id}/stream` replays the run so far (text merged) and
  then follows it, so the tab can be left and rejoined; finished runs are
  saved with every brief and output for the Runs menu.
- `run_agent_team` hands a task to a team from chat, voice or the phone; the
  answer comes back into that chat (and to the phone) when it's done.

## Roadmap hooks (already scaffolded)

- `backend/app/speech/` — server-side whisper/faster-whisper endpoints for
  fully offline STT; the frontend voice engine is the only file to change.
- `backend/app/vision/` — richer OCR (Apple Vision via pyobjc), live camera
  streaming, UI-element detection for click-by-description.
- `backend/app/automation/` — Accessibility-API window management
  (move/resize/click) beyond AppleScript.
- Meeting transcription: reuse the STT endpoint with speaker diarization,
  store transcripts as conversations tagged `folder="meetings"`.

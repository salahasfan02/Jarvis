# What changed

Newest first. The short hashes in brackets show which commit made each change.

---

# October 2026 — FaceTime, photos and agent teams

## FaceTime calls

- **"FaceTime Salah's business number"**, *"video call mum"*, *"FaceTime
  audio Sam"*, *"call my landlord on FaceTime"* — answered instantly. Jarvis
  finds the person in your saved people, then Contacts, and picks the number
  you meant by its label (work, mobile, home, iCloud). If they have no such
  number it says so instead of calling another one; two people with that
  name, and it asks which.
- The confirmation shows exactly who and which number before anything
  rings. With Accessibility, Jarvis also presses FaceTime's own *Call*
  prompt. *"Phone … through my iPhone"* makes an ordinary call.
- Calls never start from the phone or a routine.

## Photos

- **"Take a picture"** opens the Camera tab, counts down 3 seconds, flashes
  and saves the photo in Pictures › Jarvis. The Camera page has a shutter
  button with a self-timer, and a strip of your photos to view, send, show in
  Finder or delete.
- **"Take a selfie and send it to me"**, **"send me that picture"**, or *"send
  it to me"* right after: the photo arrives in your Telegram chat as a
  picture, not a file. *"Undo that"* moves a photo to the Bin.

## Agent teams

- A new **Agent teams** tab: build a team of AI agents on a canvas — add
  agents, say what each does, give them skills (web research, making files),
  pick a model per agent, and drag from one agent to another to connect them.
- You talk to one agent (the one with the crown). It works out what's needed,
  writes a detailed brief for each agent it's connected to, they work in turn
  — each building on what came before — and it brings their work together.
  Watch it live: who's working, which brief is moving along which link, each
  agent's output, the files they saved.
- A ready-made **Startup team** — main agent, market research, backend,
  frontend and marketing — and a Research & writing team. Web pages a team
  makes are live at once in a sandboxed preview.
- Runs are kept: open any earlier run from the Runs menu. Or ask from chat or
  your phone: *"ask my startup team to build a landing page for my bakery"* —
  the answer comes back into that chat.
- Team agents can only research the web and write into their run's own
  folder, so a run never needs to stop and ask.

---

# October 2026 — research, Apple Music, smart lights, a redesign and a real Mac app

## Research the web, with sources [8c16c6d, be67cd9]

- **"Do a research on MCP servers"** — Jarvis searches (DuckDuckGo, then
  Bing), reads the top pages, keeps the passages that answer the question
  and replies with numbered citations and a Sources list. The citations are
  links in the app.
- **Live weather** from Open-Meteo, no API key: *"do I need an umbrella
  tomorrow?"*
- **Research reports:** *"research X and write me a Word doc"* → a `.docx`
  with its sources.
- **Fixed a crash:** reading several pages at once could crash the whole
  backend mid-answer (two threads sharing trafilatura's lxml parser). Pages
  still download in parallel but are parsed one at a time.

## Your phone [8c16c6d, 96a2b89, d5056af]

- **"Send that to me"** at the Mac sends the answer you just got to Telegram;
  *"send me the whole chat"*; *"put that in a document and send it to me"*.
  An answer that made a document sends the document.
- "Write a document and send it to me" no longer gets stuck: the file is
  made before it's sent.
- **No more repeating itself** — after sending something, it confirms in a
  line instead of saying it all again.
- A message cut off by a restart is offered back.

## Apple Music [2cb2059]

- **"Play Janice STFU by Drake"** plays any song in the Apple Music
  catalogue, not just your library (subscription needed), using *Play Next*
  so nothing is added to your library. Music requests go to Apple Music
  unless you say YouTube or video.

## Smart lights (Tapo / Kasa) [2cb2059, d5056af, f46a72f, 96fceb2]

- **"Lights off", "dim the lights", "make the bedroom light blue",
  "warm white at 40%"** — instantly, and in routines ("lights off at 11pm
  every night"). Controls on the Core screen and in Settings → Smart lights.
- Your Tapo password is used once and never stored — only a per-light key.
- Talks to the lights on your Wi-Fi, so Alexa keeps working; cameras are
  left alone; a light that changes address is found again.
- Works around a macOS bug that blocks some apps from the local network
  without asking: the lights are reached through a small helper macOS
  lists as *Python*. Clear messages for a blocked network and for Tapo's
  *Third-Party Compatibility* switch.

## A redesign [c180845, a4464da]

- Calmer, clearer screens that keep the green look: new sidebar, **⌘K**
  command palette, page headers, empty states, toasts.
- Setup check with a progress ring and a matching badge; searchable tool
  permissions instead of a 13,000-pixel settings page; a section menu in
  Settings that follows where you are.
- Chat: answers with source cards, readable folder listings, clearer steps.
- An updated Jarvis no longer shows its old screens for a while after an
  update (the page is re-checked on every load).

## Honest and dependable [df4a908, 7b372ce, ba38d24]

- Never claims it sent or saved something no tool did — it's pushed to do
  it, and a claim that survives is cut.
- Respects a *"no"*: nothing pushes it to act anyway.
- Reminder times are kept (*"remind me at 6"*, in Arabic too).
- Chat titles see the answer, so "MCP servers" isn't titled "Minecraft".
- 90 real requests in the eval suite.

## A real Mac app [92a5cd6, 8d3e023, 2740966, ada422a, e8a953e]

- `npm run install-app` builds **Jarvis.app** with its icon, installs it,
  starts Ollama, opens at login, and only ever runs once.
- **Permissions stick:** signed with a local certificate made once on your
  Mac, so granted permissions survive rebuilds; a restart button when macOS
  needs one.
- Calendar and Reminders can be granted (the app says why it needs them).
- Setup check says exactly which app to switch on in System Settings.

## Doing things on your Mac [a368f97, cf35855, ca7bd3b, 86d6f27, 8fd2914, 91382f0, fbe7f96, a74f237]

- **Full control of any app** through Accessibility (buttons, fields, keys,
  scrolling, dragging); **Esc** or "stop" is the emergency stop; password
  managers, System Settings, terminals and banking sites are off-limits.
- A glowing frame around the screen whenever Jarvis reads or controls it.
- **Routines & triggers:** daily/weekday times, every N minutes, when an
  email arrives, before meetings — results to Telegram, a notification or
  spoken.
- **"This" means what you're looking at:** "email this to Sam",
  "summarize this page".
- Instant timers, reminders, volume and sums with no model call.
- People memory ("email my landlord"), document tools (read, compare,
  Excel, PowerPoint, PDF forms), the **"About you"** profile and form
  filling, macOS Shortcuts, an activity log with **undo**.
- "Text John…" always drafts an iMessage, never sends it.

## Voice and vision [a368f97, 0cf5387, 623cf47, e998048, 86cf2c9]

- Reliable offline wake word (Whisper small.en: 25/25 on noisy audio, no
  false wakes); talk over Jarvis to interrupt; short spoken answers.
- **Arabic:** commands, replies and voice.
- **Voice lock** (experimental): only answer the enrolled voice.
- Vision on **qwen3.5** (8/8 on test questions vs llava's 4/8), faster with
  shrunk images; the camera works through the app.
- **Proactive help:** offers a hand when the same error stays on screen
  (opt-in).

## Speed [ca7bd3b, 86d6f27, 8fd2914]

- Only the tools a request needs go into the prompt, and every request
  opens with the same cached prompt: median time to the first word fell
  from 8.0 s to 5.8 s. Long conversations are summarized in the background.

---

# Earlier — the phone, speed and email

Eleven commits on top of `d719a39` ("Revise README for clarity and updated
instructions"), 59 files (+5,518 / −523 lines).

## 1. Text Jarvis from your phone (Telegram) [12cde49]

- **Message Jarvis on Telegram from anywhere.** It does the task on your Mac
  and replies in the same chat. The bot only connects outward, so you need no
  open ports, webhook or tunnel.
- **Pairing:** Settings → Phone shows a one-time code and a t.me link. Only
  paired accounts in private chats can talk to Jarvis.
- **"Send me the lease PDF from my Downloads"**: Jarvis finds the file and
  sends it. Folders are zipped first, up to 50 MB.
- **"Research X and send me a Word doc"**: Jarvis searches the web, writes a
  `.docx` with sources and sends it. A new tool, `create_word_document`, saves
  to `~/Documents/Jarvis` and never overwrites a file.
- **Voice notes both ways:**
  - Your voice notes are transcribed with Whisper.
  - Jarvis can reply with a spoken voice bubble (Kokoro).
- **Files and photos:** anything you send to the bot is saved to
  `~/Downloads/Jarvis`.
- **Approvals on the phone:** when a tool needs permission, you get Allow / Deny
  buttons, or you can type or say yes or no.
- **Dangerous tools are blocked from the phone.** Shell commands and deleting
  files can't run from the phone unless you turn that on in Settings.
- **Commands:** `/new` starts a new chat, `/stop` cancels the current request,
  and `/help` lists the commands.
- **Storage:** the bot token is kept in `~/.jarvis/telegram_token`, readable
  only by you, and is hidden in error messages. After a restart, old messages
  are never run again.
- **No more freezing:** slow tools (AppleScript, shell) now run in the
  background. The app and the bot stay responsive while they work.

## 2. Speed [3a6b747]

- **Instant commands** answer in well under a second, with no AI model call:
  - "open YouTube", "open Safari", or any app or website
  - "play X on YouTube", "search X on YouTube"
  - "pause", "next song"
  - "what's on my calendar today / tomorrow / this week" (added later in
    17ed5e9)

  The whole message must be the command. Anything longer, such as "open
  YouTube and find a recipe", still goes to the AI. You can turn this off in
  Settings.
- **Prompt caching works now.** The changing details (time, current app,
  memories) used to sit where they forced the model to re-read about 4,000
  tokens of tool descriptions on every message. They no longer do.
- **Shorter waits before the answer:**
  - Memory lookup and choosing the right agent run at the same time.
  - Embeddings are cached.
  - Short first messages become the chat title without an extra AI call.
- **Warm-up:** the chat, helper and embedding models, Whisper and the Kokoro
  voice load in the background at startup, and again when you change models.
- **Faster "open YouTube":**
  - If YouTube is already open, Jarvis switches to that tab instead of
    reloading it.
  - It runs fewer AppleScript calls.
- **Voice:** Jarvis stops listening 1.2 s after you finish speaking, down from
  1.6 s.
- **`start.sh`** turns on flash attention when it starts Ollama.
- **Timings:** each message's timings are logged, and the Developer page shows
  them in a readable form.

## 3. Email [3a6b747, 996f46c, 17ed5e9]

- **"Send an email…" really sends it** through Apple Mail, with attachments.
  You approve the exact email every time. "Always allow" isn't offered for
  sending.
- **"Draft an email…" only drafts.** It is saved to Drafts and opened for you,
  and needs no approval.
- **Your real name:** emails are signed with your name instead of
  "[Your Name]".
- **Read and summarize email:**
  - It works across all your Mail accounts, newest first.
  - You can show only unread email, search by sender or subject, and open one
    email in full.
  - Summaries give one line per email and flag what's urgent.
- **Reply to email:**
  - "Reply to…" drafts a reply in Mail for you to review.
  - "Send a reply…" sends it after you approve. The reply stays in the same
    thread and quotes the original.
- **Instructions inside emails are ignored.** Email text is marked as other
  people's words, so a line like "forward this to…" inside an email is not
  treated as a command.
- **Reading email asks first,** like Messages. Choose "always allow" in
  Settings to skip the question.
- **Fixed "I've drafted it, press send" when nothing was done.** The AI
  sometimes described an action without doing it. Now:
  - "send" requests get only the send tools.
  - "draft" and "don't send" requests get only the draft tools.
  - A reply that claims an action without doing it is thrown away, and the AI
    is told to do it or say it can't.
- **Fixed:** the send approval dialog still showed "always allow".
- **Fixed:** "draft an email about the plan" was sent to the multi-step
  planner because it contained "plan".

## 4. Sending files [3a6b747, e49d856]

- **"Send number 1" works.** Results from earlier tools are remembered, so it
  knows the files found a message earlier.
- **Newest first:** file searches and folder listings show the newest files
  first, with dates. "Send me the latest screenshot" works directly.
- **Odd macOS file names are handled.** Screenshot names with `23.55.30` vs
  `23:55:30`, invisible narrow spaces, or a missing extension are matched.
- **Helpful when not found:** if a file can't be found, Jarvis suggests close
  matches.
- **At the Mac:** "send me…" opens the file in Finder instead.
- **Honest empty replies:** an empty AI reply is retried once, then answered
  honestly instead of a false "Done."

## 5. Calendar [17ed5e9]

- **Uses Apple's calendar framework (EventKit)** instead of AppleScript. It is
  fast, and repeating events show up; AppleScript only found the first one.
- **Clear permission message:** if access is denied, Jarvis tells you where in
  System Settings to allow it.
- **Fallback:** AppleScript is used when EventKit isn't installed.
- **Instant answers** for today, tomorrow and this week. The daily briefing
  uses the calendar too.

## 6. Wake word ("Jarvis") [5fa7de4, 1dd47cb]

**Why it missed so often:**

- It recorded fixed clips, so it was deaf while transcribing, and words were
  cut at clip edges ("…arvis").
- It used a fixed loudness level.
- Its timers slowed down when Jarvis wasn't the front window.
- It stopped silently when the mic changed.
- It needed the exact spelling "jarvis", but Whisper often writes "Jervis",
  "Javis", "Jar is" or "Gervais".

**Now:**

- **Always listening.** It records continuously, never pauses while
  transcribing, adjusts to background noise, and keeps 0.4 s of audio from
  before you spoke.
- **Fixes itself:** it restarts when the mic drops or audio stops. If the
  browser blocked audio, it says "Click anywhere so I can hear you".
- **Tolerant matching:** near-misses and common mishearings of "Jarvis" count.
  "Jarvis, open YouTube" in one breath runs the command straight away.
- **Whisper hint:** Whisper is told to expect the wake word.
- **Steady mic:** a failed status check no longer switches engines, which used
  to drop the mic.
- **Desktop app:** audio isn't throttled or blocked there anymore.
- **Visible problems:** mic and transcription problems are now shown on
  screen. Before, they were silent.
- **Browser recognizer notice:** if Whisper isn't downloaded, Jarvis uses the
  browser's speech recognition, which doesn't work in the desktop app or
  Brave. It now says so: "download Whisper in Settings → Voice".
- **New: Settings → Voice → Voice check.** It shows:
  - which engine is in use
  - the mic status
  - a live level bar
  - the last things Jarvis heard, marked when they woke it

## 7. Look and feel [8d40de1, ec1e45f]

- **Icons:** all emoji in the app were replaced with open-source SVG icons
  from Lucide (ISC licence). They follow your theme and accent colour.
- **Error messages in words:** status lines say what happened, without emoji
  decoration.
- **Picture backgrounds:** Settings → Appearance → Background → Picture.
  - Upload a JPEG, PNG, WebP or GIF up to 25 MB. iPhone HEIC photos are
    converted automatically.
  - Pick from a gallery, dim the picture for readability, or delete it.
  - Pictures are stored in `~/.jarvis/backgrounds`.

## 8. Security fixes [e9170c2]

- **Calculator:** it no longer uses `eval()`, which could be tricked into
  running shell commands without asking. It now only understands numbers and
  math.
- **Websites can't control Jarvis.** Before, any web page you visited could
  open Jarvis's chat connection and approve its own shell command. Now only
  Jarvis's own window is accepted. DNS-rebinding tricks are blocked too.
- **Desktop app:** it now loads the UI from the backend (`/app`) instead of
  from a local file.
- **Previews:** generated HTML previews run in a sandbox and can't use
  Jarvis's API.
- **Web fetching:** it refuses local and private network addresses, including
  after redirects.
- **Code sandbox:**
  - Code can't control other apps.
  - It can't read `~/.ssh`, `~/.jarvis`, Mail, Messages, keychains or browser
    data.
- **Audit log:** it reads only the end of the file and rotates at 10 MB.

## 9. Setup (`start.sh`) [06dd8e7, e9170c2]

- **Python:** it finds Python 3.11 or newer by itself, and refuses an
  outdated virtual environment with instructions to fix it.
- **Python packages:** they are reinstalled when `requirements.txt` changes.
  Packages are only marked as installed once installing succeeded.
- **UI packages:** they are reinstalled when a pull changed them. That was why
  the icons update failed to start.
- **Browser:** it opens once the UI is actually ready.
- **AI model:** if the configured chat model is missing, an installed one is
  picked.
- **New Python package:** `pyobjc-framework-EventKit`, for the calendar.

## 10. Tests and docs [all commits]

- **95 automated tests** in `backend/tests/`. They use a fake Telegram, a
  fake AI model, a fake Mail and a fake Calendar, and all pass.
- **End-to-end runs in Chromium with a fake microphone:**
  - the wake word
  - the Voice check
  - email approvals
  - instant commands
  - the security fixes
- **Docs:** the README and `docs/architecture.md` were updated.

---

## New files

- `backend/app/channels/__init__.py`: phone channel basics.
- `backend/app/channels/telegram.py`: the Telegram bot.
- `backend/app/chat/quick.py`: instant commands.
- `backend/app/warmup.py`: loads models in the background.
- `backend/app/backgrounds.py`: picture backgrounds.
- `backend/app/tools/builtin/documents.py`: Word documents and `send_file`.
- `backend/app/tools/builtin/mail.py`: reading, searching and replying to
  email.
- `backend/app/tools/builtin/calendars.py`: calendar via EventKit.
- `frontend/src/lib/wake.ts`: wake-word matching.
- `backend/tests/`: 11 test files.

## Not tested on a real Mac yet

These parts were built against fakes because the cloud machine isn't a Mac.
Check them on yours:

- **Apple Mail:** sending, drafting, reading and replying.
- **Calendar:** the first request should show macOS's permission prompt.
- **Wake word:** with Whisper downloaded. Use Settings → Voice → Voice check.
- **Kokoro voice replies and the Electron desktop app.**
- **The code sandbox** (`sandbox-exec`).
- **A live Telegram bot:** create it with @BotFather, then paste the token in
  Settings → Phone.

<div align="center">

# 🟢 Jarvis

### A private, local AI operating system for your Mac.

**Voice. Vision. Automation. Memory. 100% on your machine — no cloud, no API keys, no subscriptions.**

Jarvis turns your MacBook into the AI assistant from the movies: talk to it, let it see your screen and camera, control your apps, remember everything about you, and get real work done — all powered by local LLMs through [Ollama](https://ollama.com). Nothing ever leaves your Mac.

[![macOS](https://img.shields.io/badge/macOS-Apple_Silicon-000000?logo=apple&logoColor=white)](#-requirements)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](#-requirements)
[![TypeScript](https://img.shields.io/badge/TypeScript-React-3178C6?logo=typescript&logoColor=white)](#️-tech-stack)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-black)](https://ollama.com)
[![Local & Private](https://img.shields.io/badge/100%25-Local_%26_Private-00ff66)](#-why-jarvis)
[![License: Noncommercial](https://img.shields.io/badge/License-Noncommercial-green.svg)](LICENSE)

**⭐ If this looks cool, star the repo — it genuinely helps.**

[![Buy Me A Coffee](https://img.shields.io/badge/☕_Buy_me_a_coffee-Support_Jarvis-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/salahasfan)

<br/>

![Jarvis demo](docs/demo.gif)

</div>

---

## 🧠 Why Jarvis?

Every AI assistant wants your data in the cloud. Jarvis doesn't.

- **🔒 Totally private** — runs on local models via Ollama. No accounts, no API keys, no telemetry. Your conversations, screen, camera, files, and memories never leave your machine.
- **🎙️ Voice-first** — say *"Jarvis…"* and it wakes up (with a chime), listens with **offline Whisper**, and replies in a **human neural voice**. Have a real back-and-forth conversation, hands-free.
- **👁️ It can actually see** — reads your screen with Apple's OCR, watches through your camera, and answers questions about whatever's in front of you.
- **🌐 It knows what's going on** — researches the web, reads the best pages and answers with **numbered sources**; live weather without an API key.
- **🦾 It does things** — opens apps, controls your browser, plays anything on **Apple Music**, switches your **smart lights**, makes **FaceTime calls**, takes **photos**, drafts emails, manages files, runs code — with a permission prompt before anything touches your system.
- **📱 It's in your pocket** — message it on Telegram, and *"send that to me"* puts any answer, chat or document on your phone.
- **🧩 It's an OS, not a chatbot** — a living command-center dashboard with agents, **agent teams you wire together on a canvas**, projects, long-term memory, and a plugin system it can extend *itself*.
- **🆓 Free & source-available** — free for any **noncommercial** use. Fork it, hack it, make it yours.

---

## 📸 Screenshots

<div align="center">

**The Core** — ask anything by voice or text; answers come with their sources, and your Mac's vitals sit alongside
![Core](docs/screenshots/core.png)

**Research with sources** — Jarvis searches the web, reads the best pages and cites every claim
![Chat](docs/screenshots/chat.png)

</div>

| Routines — things it does on its own | Setup check — every permission, one click to fix |
|:---:|:---:|
| ![Routines](docs/screenshots/routines.png) | ![Setup check](docs/screenshots/setup.png) |

| Long-term Memory | Custom Skills |
|:---:|:---:|
| ![Memory](docs/screenshots/memory.png) | ![Skills](docs/screenshots/skills.png) |

| Smart lights in Settings | ⌘K — jump anywhere, or just ask |
|:---:|:---:|
| ![Settings](docs/screenshots/settings.png) | ![Command palette](docs/screenshots/palette.png) |

<div align="center">

**Self-improvement** — what it couldn't do yet, logged and ranked so it can build it
<img src="docs/screenshots/capabilities.png" width="49%" alt="Capabilities">

</div>

---

## ✨ What it can do

<table>
<tr>
<td width="50%" valign="top">

### 🎙️ Voice
- Wake word (*"Jarvis…"*) with an audible chime — robust to room noise, no phantom wakes
- **Offline speech recognition** (Whisper `small.en`) — works in any browser
- Say *"stop"* any time to halt what it's doing · **talk over it** — it lowers its voice at once, and *"Jarvis…"* (or, in conversation mode, any reply) interrupts
- **Short spoken answers** — a couple of sentences when you're talking, with *"Want the details?"*
- **Human-sounding neural voices** (Kokoro TTS)
- Sentence-streaming replies (talks as it thinks)
- Conversation mode — reply without repeating the wake word

### 👁️ Vision
- Read the **exact text** on your screen (Apple Vision OCR)
- **Live camera** — *"open the camera and tell me what you see"*
- **Take photos** — *"take a picture"* counts down, snaps and saves it in Pictures › Jarvis (or press the shutter, with a 3 s or 10 s timer) · *"take a selfie and send it to me"* / *"send me that picture"* puts it on your phone, as a photo in the Telegram chat
- **You always know** — a glowing frame surrounds your screen whenever Jarvis reads or controls it
- **Screen watch** — "tell me when the download finishes"
- **Screen memory** — auto-journals what you're working on

### 🦾 Mac Automation
- **Full control of any app** — presses buttons (even icon-only ones) by name through macOS Accessibility, fills in fields, types, keyboard shortcuts, scrolls and drags · **Esc** is the emergency stop · password managers, System Settings, terminals and banking sites are **off-limits** (editable)
- **Shortcuts** — runs any of your macOS Shortcuts (HomeKit scenes, Focus modes…)
- **Activity & undo** — every action logged; *"undo that"* moves files back, restores overwritten or trashed ones, removes what it created
- Open apps and **files by name** (*"open my CV"*), control windows, notifications, clipboard
- **Browser agent** — clicks links and buttons on any page, closes tabs by name, reuses your tabs
- **Apple Music** — *"play Espresso by Sabrina Carpenter"* plays any song in the Apple Music catalogue, not just your library (needs a subscription), without adding it to your library · *"put on some relaxing jazz"* · **YouTube** when you ask for it
- **Smart lights** — Tapo & Kasa bulbs on your Wi-Fi: *"lights off"*, *"dim the lights"*, *"make the bedroom light blue"*, *"warm white at 40%"*, or a routine like *"turn the lights off at 11pm every night"* · works alongside Alexa
- **Calendar** — *"what's on my calendar tomorrow?"* (all calendars, repeating events included) · **Notes, Reminders** — read and create; *"remind me at 6 to call Sam"* keeps the time (in Arabic too)
- **Email** — *"summarize my emails"*, *"any new mail from Sam?"*, reply, draft, or send with attachments by name (*"email my CV to…"*); you approve every email first · draft iMessages
- **Knows your people** — *"email my landlord"* finds them in Jarvis's memory or your Contacts
- **FaceTime** — *"FaceTime Salah's business number"*, *"video call mum"*, *"FaceTime audio Sam"* — finds the person *and the right number* (the one labelled work, mobile, home…) in your saved people and Contacts, shows you exactly who and which number, then calls · with Accessibility allowed it also presses FaceTime's own *Call* prompt · *"phone the office through my iPhone"* makes an ordinary call

</td>
<td width="50%" valign="top">

### 🧑‍💻 Developer Workspace
- Unified **Chat + Code** modes
- **Run code in a sandbox** — Python, JS/TS, C/C++, Go, Rust, Java
- Multi-file projects, package installs, **live HTML preview**
- Senior-engineer coding agent (review, refactor, tests, docs)

### 🧠 Memory & Knowledge
- **Long-term memory** — remembers your preferences & projects
- **Auto-capture** — learns facts as you talk (toggleable)
- **Document RAG** — drop in PDFs/Word/Excel, or index a whole folder, and search it by meaning
- **Documents** — read & compare PDFs/Word, create **Word, Excel and PowerPoint** files, fill in PDF forms, then email or send them
- **Projects** — per-project memory across conversations

### 🕵️ Research
- **Researches the web for you** — searches (DuckDuckGo, then Bing), reads the top pages, keeps the passages that answer the question and replies with **numbered citations** and a **Sources** list
- **Live weather** — *"do I need an umbrella tomorrow?"* (Open-Meteo, no API key)
- **Research reports** — *"research the best budget e-bikes and write me a Word doc"* → a `.docx` with its sources
- Scoped search: GitHub, Stack Overflow, Reddit, arXiv, YouTube

### 🤖 Intelligence
- **Auto-routing agents** (research, coding, media, vision…)
- **Agent teams** — build a team of AI agents on a canvas: say what each one does, give it skills (web research, making files) and connect them. You talk to one — say, a *main agent* — and it works out what's needed, writes a detailed brief for each agent it's connected to (*backend*, *frontend*, *marketing*, *market research*…), and brings their work together. Web pages they make go live straight away. Or just say *"ask my startup team to…"*
- **Multi-step task planner** with a live checklist
- **Custom Skills** — save prompts, invoke with `/name`, import/export
- **Self-improving** — logs what it can't do and can write its own tools
- **Multi-model** — assign models per task, benchmark them
- **Fast by design** — only the tools a request needs go into the prompt, so even a 14B model answers quickly
- **Honest by design** — it never says it sent, saved or booked something unless a tool actually did it, it respects a *"no"*, and it doesn't repeat itself
- **Built-in eval suite** — nearly 100 real requests replayed against fake tools to check every model change, and it **learns from real mistakes**: slips and *"that's wrong"* become new test cases
- **Long conversations** — older turns are summarized in the background so nothing falls out of the model's memory
- **Instant commands** — *"open YouTube"*, *"open Safari"*, *"pause"* run in well under a second, no model needed

</td>
</tr>
</table>

### 🖥️ Menu-bar Quick Command
Hit **⌥Space** from *any* app to summon a floating command bar — ask about what's on your screen, get an answer, and get back to work without switching windows. Inside Jarvis, **⌘K** jumps to any page, chat or action — or just asks.

### ☀️ Daily Briefing
*"Jarvis, give me my daily briefing"* → live weather, today's calendar, and your reminders, narrated.

### 📱 Text Jarvis from your phone
Message Jarvis on **Telegram** from anywhere. It does the work on your Mac and replies in the chat:
- *"Send me the lease PDF from my Downloads"* → finds the file and sends it to you
- *"Research the best budget e-bikes and send me a Word doc"* → searches, writes a `.docx` with sources, sends it
- 🎙 **Voice notes** in, voice notes back · send it files or photos to ask about · approve risky actions with one tap
- **"Send that to me"** at the Mac → the answer you just got arrives on your phone · *"send me the whole chat"* · *"put that in a document and send it to me"* → a Word file in Telegram
- A message cut off by a restart is offered back, so nothing you asked for gets lost

Two-minute setup — see [Phone setup](#-phone-setup-telegram).

---

## 🚀 Quick Start

```bash
# 1. Python 3.11+  —  macOS's built-in python3 is 3.9, which can't run Jarvis
brew install python@3.12          # skip if `python3 --version` already says 3.11+

# 2. Install Ollama and pull a model (https://ollama.com/download)
ollama pull qwen2.5:14b

# 3. Clone and run everything with one command
git clone https://github.com/Salahasfan02/Jarvis.git
cd Jarvis
chmod +x start.sh && ./start.sh
```

`start.sh` finds a Python 3.11+ on its own, installs everything on the first run (and again whenever a `git pull` changes the dependencies), and retries an install that was interrupted.

Your browser opens at **http://localhost:5173** and Jarvis is live. Press **Ctrl+C** (or `./stop.sh`) to turn it off. Nothing auto-starts; it only runs when you start it.

> 🔧 **Your model is picked for you.** If the configured model (`llama3.1` by default) isn't installed, Jarvis switches to one you have — `qwen2.5:14b` above. Change it anytime in **Settings → Model**.

> 🔐 **macOS will ask for permissions.** The first time Jarvis reads your screen, uses the camera, reads your calendar, or drives another app, macOS prompts for **Screen Recording**, **Camera**, **Microphone**, **Calendars**, **Automation** (Mail, Safari, Music) and **Accessibility**. Grant them in System Settings → Privacy & Security. Email features use the **Mail** app, so add your accounts (iCloud, Gmail, Outlook…) there.

<details>
<summary><b>Prefer the native desktop app?</b></summary>

The Electron shell is a **wrapper around the running stack**, not a standalone build — in dev it loads the Vite UI from `http://localhost:5173`, and it launches the backend using `backend/.venv`. So bring the stack up first:

```bash
./start.sh          # terminal 1 — leave this running

cd desktop          # terminal 2
npm install
npm start           # run it from the repo, or:
npm run install-app # build Jarvis.app, put it in Applications and open it
```

The desktop app adds a menu-bar icon, the **⌥Space** quick command, a **⌘⇧J** floating window, and "Open at Login."

Note that `npm run package` records the path to *this clone's* backend in `~/.jarvis/backend_path`. The resulting `Jarvis.app` still needs this repo on disk — a fully self-contained bundle is on the [roadmap](#️-roadmap).
</details>

<details>
<summary><b>Run each piece manually</b></summary>

```bash
# Terminal 1 — Ollama
ollama serve

# Terminal 2 — backend   (use an explicit 3.11+ interpreter, not bare `python3`)
cd backend && /opt/homebrew/bin/python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py            # → http://127.0.0.1:8765

# Terminal 3 — UI
cd frontend && npm install && npm run dev   # → http://localhost:5173
```

</details>

### Level up (optional, all local)

```bash
ollama pull nomic-embed-text   # semantic memory + smarter agent routing
ollama pull llama3.2:3b        # a small, fast helper for titles and background work
ollama pull qwen3.5            # camera & screen vision
```

Then open **Settings** to enable them, download the offline **Whisper** and human **Kokoro** voice models, pick your theme, and set your wake word.

### 🖥️ Install as a Mac app
`cd desktop && npm run install-app` builds **Jarvis.app** (with its own icon), signs it locally and
installs it in Applications. It starts Ollama if needed, only ever runs once, and can open at login
(Settings → Desktop app). It's a new app to macOS, so allow the microphone, camera, Accessibility,
Screen Recording, Calendars and Reminders once — **Setup check** lists anything still missing, with a
fix button for each (and a restart button when macOS needs one).

The installer signs with a certificate it makes once on your Mac (*Jarvis Local Signing*), so the
permissions you grant **survive every rebuild** — no re-allowing after an update.

### 📱 Phone setup (Telegram)

1. In Telegram, message **[@BotFather](https://t.me/BotFather)**, send `/newbot`, pick a name, and copy the token it gives you.
2. In Jarvis, open **Settings → Phone (Telegram)**, paste the token, and press **Connect**.
3. Send the `/pair 123456` code shown there to your new bot from your phone — or press **Open in Telegram** if Telegram is on your Mac. That's it.

Things to know:
- **Nothing is exposed to the internet.** Jarvis polls Telegram with outbound requests only — no port forwarding, tunnel, or public URL. Your Mac must be awake with Jarvis running (on power, enable *Prevent automatic sleeping* in System Settings → Battery/Energy).
- **Only paired accounts get answers;** everyone else is ignored. Anything that needs permission (sending a file, reading your messages…) asks with **Allow / Deny** buttons, or reply *yes* / *no*. Dangerous tools (shell, AppleScript, deleting files) are **blocked from the phone** unless you switch them on.
- **Privacy trade-off:** Telegram bot chats aren't end-to-end encrypted, so what you send and receive passes through Telegram's servers. The feature is off until you set it up.
- Telegram bots can't take phone calls — voice notes are the hands-free way in (needs the Whisper model; voice replies need Kokoro). Files: up to 50 MB to your phone, 20 MB from it.
- Word documents are saved in `~/Documents/Jarvis`; files you send Jarvis land in `~/Downloads/Jarvis`. `/new` starts a fresh conversation, `/stop` cancels.
- Once paired, *"send that to me"* at the Mac goes to this chat too.

### 💡 Smart lights setup (Tapo / Kasa)

1. Make sure your Mac is on the same Wi-Fi as the lights.
2. In Jarvis, open **Settings → Smart lights**, type your **Tapo account** email and password, and press **Connect**. Jarvis finds every light on the network and lists it with a switch, brightness and colours.
3. Say *"lights off"* — or put the lights in a routine.

Things to know:
- **Your password isn't saved.** It's used once to connect; Jarvis keeps only a key for each light (`~/.jarvis/lights.json`, readable only by you), which can't sign in to your Tapo account.
- Jarvis talks to the lights **directly on your Wi-Fi**, so Alexa and the Tapo app keep working. Cameras and other Tapo devices are left alone.
- If a light moves to a new address on your network, Jarvis finds it again by itself.
- Newer Tapo firmware only lets other apps in when **Third-Party Compatibility** is on in the Tapo app (**Me → Tapo Lab**, or **Me → Third-Party Services**). If Jarvis says your light *didn't accept* a correct password, turn that on.

---

## 🔧 Troubleshooting

<details>
<summary><b>"backend/.venv uses Python 3.9" / <code>ResolutionImpossible</code> for onnxruntime</b></summary>

An environment from an older setup was built with macOS's Python 3.9. Install a newer Python, delete the `backend/.venv` folder, and start again — `start.sh` rebuilds it with 3.11+:

```bash
brew install python@3.12
rm -rf backend/.venv && ./start.sh
```
</details>

<details>
<summary><b>"Jarvis" doesn't react to the wake word</b></summary>

- In a browser, click anywhere on the Jarvis page once after it opens — browsers keep audio off until you do (the Core says *"Click anywhere so I can hear you"*). The desktop app doesn't need this.
- Download the **Whisper** model in **Settings → Voice** (offline, and far more reliable than the browser's recognizer).
- Grant **Microphone** access to your browser / Jarvis.app in System Settings → Privacy & Security.
</details>

<details>
<summary><b>First message fails with a model error</b></summary>

The active model doesn't exist locally. Run `ollama list` to see what you actually have, then pick one of those in **Settings → Model**. The out-of-the-box default is `llama3.1`.
</details>

<details>
<summary><b>The desktop app opens a blank window</b></summary>

In dev mode it loads `http://localhost:5173`, so the Vite dev server has to be running — start the stack with `./start.sh` before `npm start`.
</details>

<details>
<summary><b>Replies feel slow</b></summary>

Simple commands (*"open YouTube"*, *"pause"*) skip the model entirely. For everything else, the local model is the cost:
- **Settings → Task models → Utility:** pick a small model (e.g. `ollama pull qwen2.5:1.5b`). Titles and background work then stop competing with your conversation.
- **Settings → Keep model in memory:** `-1` keeps the model loaded, so replies never wait for it to load (uses RAM while Jarvis runs).
- **Developer → Audit** shows a timing line per message: how many tokens the model had to read and how long that took. After the first message in a conversation, that number should drop to a few hundred — that's the prompt cache working.
</details>

<details>
<summary><b>Ctrl+C didn't stop everything</b></summary>

`./start.sh` cleans up when you interrupt it from the terminal it's running in. If you launched it detached (`nohup`, `&`, or from another script), the backend and UI survive — use `./stop.sh`, which kills by port instead. Add `--all` to stop Ollama too.
</details>

<details>
<summary><b>Screen reading, camera, or app automation does nothing</b></summary>

Missing macOS permissions. Open System Settings → Privacy & Security and grant **Screen Recording**, **Camera**, **Microphone**, and **Accessibility** to your terminal (or to Jarvis.app if you packaged it), then restart Jarvis. **Setup check** shows which ones are missing and opens the right page.
</details>

<details>
<summary><b>Smart lights: "No Tapo or Kasa lights answered" / "macOS is keeping Jarvis off your Wi-Fi"</b></summary>

- Check the light works in the Tapo app and your Mac is on the same Wi-Fi (not a guest network).
- macOS's **Local Network** privacy has to allow it. Jarvis talks to the lights through a small helper that macOS lists as **Python**: turn **Python** on in System Settings → Privacy & Security → Local Network (or press *Allow* when macOS asks). This works around a macOS bug that blocks some apps without ever asking or listing them.
- *"Your light didn't accept that Tapo email and password"* with the right details means **Third-Party Compatibility** is off in the Tapo app (Me → Tapo Lab, or Me → Third-Party Services).
</details>

<details>
<summary><b>"Play …" doesn't start the song</b></summary>

Playing from the Apple Music catalogue needs an **Apple Music subscription**, the **Music** app signed in, and **Accessibility** for Jarvis (it queues the song with *Play Next*). Songs already in your library play without either.
</details>

<details>
<summary><b>"FaceTime …" opens FaceTime but the call doesn't start</b></summary>

- macOS always asks before a call starts (a notification with a **Call** button). Jarvis presses it for you when it has **Accessibility** (System Settings → Privacy & Security → Accessibility); otherwise press *Call* yourself.
- FaceTime must be signed in with your Apple Account. FaceTime reaches iPhones and Apple IDs, not landlines — for those, ask for a phone call (*"phone the office through my iPhone"*), which needs **Calls from iPhone** turned on in the FaceTime app's settings.
- *"…has no work number saved"*: Jarvis never guesses which number you meant. Label the number in Contacts (work, mobile, home…), or say the number itself.
</details>

---

## 📋 Requirements

| | |
|---|---|
| **OS** | macOS on Apple Silicon (built & tested on an M-series Mac) |
| **[Ollama](https://ollama.com)** | with at least one model (e.g. `qwen2.5:14b`) |
| **Python** | **3.11+** — macOS's built-in `python3` is 3.9 and will not install the backend. `brew install python@3.12` |
| **Node.js** | 18+ |
| **RAM** | 16 GB minimum, 24 GB+ recommended for larger models |
| **Permissions** | Screen Recording, Camera, Microphone, Accessibility, Calendars, Reminders (prompted on first use) · Local Network for smart lights |
| **Optional** | Apple Music subscription (play any song) · Tapo / Kasa smart lights · Telegram (phone access) |

> 💡 **Model tip:** `qwen2.5:14b` is the sweet spot for tool-calling on a 16–24 GB Mac. The app is fully model-agnostic — switch models anytime in Settings, and even benchmark them on your hardware.

---

## 🔐 Security & Privacy

Jarvis is built to earn your trust:

- **Runs 100% locally** — the AI never leaves your Mac. The only things that go online are what you ask for: web research and weather (DuckDuckGo/Bing, the pages they find, Open-Meteo), song lookups for Apple Music (Apple's search API), and Telegram if you turn on the phone channel. Smart lights are controlled on your own Wi-Fi, not through the cloud.
- **No passwords kept** — your Tapo password is used once and forgotten; Jarvis keeps only a per-light key. The Telegram token is stored readable only by you.
- **Permission system** — every action has a risk level. Safe actions run instantly; anything that touches your system (shell, AppleScript, deleting files) asks first, every time.
- **Audit log** — every tool call, confirmation, and denial is recorded.
- **Nothing is sent behind your back** — iMessages are only drafted; an email goes out only when you say *send* and approve that exact message (this approval can't be switched off).
- **Websites can't drive it** — the local API only accepts changes and chat connections from Jarvis's own UI, so a page you visit can't talk to Jarvis behind your back.
- **Sandboxed code** — generated code runs with no network, can't read your keys, mail or messages, can't script other apps, and can only write to its own folder.
- **Agent teams stay in their lane** — team agents can only research the web and write files into their run's own workspace; the pages they publish are sandboxed too, so nothing they make can reach Jarvis or the rest of your Mac.
- **Calls show you who first** — before Jarvis rings anyone you see the person and the exact number it found; calls never start from the phone or a routine, when you're not at the Mac to talk.

---

## 🏗️ Tech Stack

**Backend:** FastAPI · Ollama · SQLite · faster-whisper (STT) · Kokoro (TTS) · Apple Vision (OCR) · pyobjc · trafilatura (reading web pages) · python-kasa (Tapo / Kasa lights) · Open-Meteo (weather)
**Frontend:** React · TypeScript · Vite · Vitest · [Lucide](https://lucide.dev) icons (ISC)
**Desktop:** Electron (tray, global hotkeys, floating window), signed locally so permissions persist

Modular by design — new tools, agents, models, and integrations drop in without touching the core. See [`docs/architecture.md`](docs/architecture.md).

---

## 🗺️ Roadmap

- [ ] Encrypted memory & conversation storage
- [ ] First-run setup wizard (auto-pulls the right models)
- [ ] Self-contained `.app` (bundled backend)
- [ ] Meeting transcription with speaker separation
- [ ] Git integration in the coding workspace
- [ ] Community skill & plugin packs

---

## 🤝 Contributing

PRs, ideas, and bug reports are welcome. Jarvis is designed to be extended — writing a new tool or plugin is a few lines of Python (see [`docs/architecture.md`](docs/architecture.md)).

Run the tests (no Ollama needed):

```bash
cd backend && .venv/bin/pip install pytest && .venv/bin/python -m pytest   # 240+ backend tests, any OS
cd frontend && npm test                                                    # interface helpers (Vitest)
```

Check how well a model handles real requests (needs Ollama; tools are faked, nothing on your Mac is touched): `cd backend && .venv/bin/python -m evals.run --model qwen2.5:14b` — prints pass/fail and timing for nearly 100 requests like *"email my CV to…"*, *"send the weather you just gave me to my phone"*, *"make the bedroom light blue"* and *"facetime mum"*.

## ⭐ Star it

If Jarvis is useful or just fun to poke at, **drop a star** — it helps other people find it and keeps the project going.

## ☕ Support

Jarvis is free and built in my spare time. If it saved you time or made you smile, you can [**buy me a coffee**](https://buymeacoffee.com/salahasfan) — it fuels the next late-night feature. Thank you! 🙏

<a href="https://buymeacoffee.com/salahasfan"><img src="https://img.shields.io/badge/☕_Buy_me_a_coffee-salahasfan-FFDD00?logo=buymeacoffee&logoColor=black&style=for-the-badge" alt="Buy me a coffee"></a>

## 📄 License

[PolyForm Noncommercial 1.0.0](LICENSE) — **free for any noncommercial use**: personal projects, hobby, research, education, and nonprofits. You can use, modify, and share it freely — just not sell it or use it commercially. Commercial use requires a separate license from the author.

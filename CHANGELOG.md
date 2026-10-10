# What changed

Everything added or fixed on branch `claude/trusting-wright-ojvok1`, since
commit `d719a39` ("Revise README for clarity and updated instructions").
That is 11 commits and 59 files (+5,518 / −523 lines). The short hashes in
brackets show which commit made each change.

---

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

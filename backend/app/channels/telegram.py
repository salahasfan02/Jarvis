"""Telegram channel: text Jarvis, send it files and voice notes from your phone.

- Long polling (getUpdates): the Mac only makes outbound requests, so nothing
  is exposed to the internet — no webhook, port forwarding or tunnel.
- Only paired Telegram accounts are served. Pairing: Settings → Phone shows a
  one-time code; the user sends `/pair <code>` to the bot from their phone.
- Each Telegram chat maps to one Jarvis conversation (/new starts another),
  so phone chats also show up in the desktop sidebar.
- Tools that need confirmation ask with Allow/Deny buttons (or a typed
  yes/no); dangerous tools are blocked from the phone unless Settings allows
  them (enforced in chat.service).
- Messages pass through Telegram's servers (bot chats are not end-to-end
  encrypted) — that is the trade-off for reaching the Mac from anywhere.
"""
from __future__ import annotations

import asyncio
import hmac
import html
import io
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

from .. import db
from ..chat import service as chat_service
from ..config import JARVIS_HOME, settings
from ..security import audit
from ..security.permissions import confirmations
from . import ChannelSession, current

API_BASE = "https://api.telegram.org"
TOKEN_FILE = JARVIS_HOME / "telegram_token"
STATE_FILE = JARVIS_HOME / "telegram_state.json"
INBOX_DIR = Path.home() / "Downloads" / "Jarvis"
MAX_DOWNLOAD = 20 * 1024 * 1024     # Bot API limit for files a bot can fetch
PAIRING_TTL = 600
PAIRING_MAX_ATTEMPTS = 5
CHUNK = 3800                        # Telegram caps messages at 4096 chars

HELP = (
    "Hi! I'm {name}, running on your Mac. Text me like you would at the desk:\n"
    "• “send me the lease PDF from my Downloads”\n"
    "• “research budget e-bikes and send me a Word doc”\n"
    "• 🎙 voice notes work too — I'll answer by voice\n"
    "• send me a file or photo and ask about it\n\n"
    "/new — start a fresh conversation\n"
    "/stop — stop what I'm doing\n"
    "/help — this message")

TOOL_LABELS = {
    "web_search": "🔎 Searching the web",
    "research": "🔎 Researching on the web",
    "research_report": "📝 Researching and writing your document",
    "weather": "🌤 Checking the weather",
    "web_fetch": "📖 Reading a page",
    "search_files": "🗂 Looking for files",
    "list_directory": "🗂 Looking in a folder",
    "read_file": "📄 Reading a file",
    "create_word_document": "📝 Writing the document",
    "send_file": "📤 Sending the file",
    "screen_read": "👁 Reading the screen",
    "screen_look": "👁 Looking at the screen",
    "youtube_play": "▶️ Starting it on YouTube",
    "browser_open": "🌐 Opening it in the browser",
    "open_app": "🚀 Opening the app",
    "draft_email": "✉️ Drafting the email",
    "send_email": "📨 Sending the email",
    "music_play": "🎵 Starting the music",
    "read_emails": "📬 Checking your inbox",
    "search_emails": "🔎 Searching your mail",
    "read_email": "📧 Reading the email",
    "draft_reply": "✉️ Drafting the reply",
    "send_reply": "📨 Sending the reply",
    "calendar_events": "📅 Checking your calendar",
    "calendar_today": "📅 Checking your calendar",
}

_YES = {"yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure", "allow", "approve",
        "go", "confirm", "👍", "✅"}
_NO = {"no", "n", "nope", "nah", "deny", "don't", "dont", "cancel", "❌", "👎"}


class TelegramError(Exception):
    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


# --- token, state, pairing ------------------------------------------------------

def read_token() -> str:
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError:
        return ""


def _write_token(token: str) -> None:
    # The token is a password for the bot: owner-only file, never in settings.json
    # (which the UI reads back) and never in logs.
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    os.chmod(TOKEN_FILE, 0o600)


def _redact(text: str) -> str:
    token = read_token()
    text = text.replace(token, "<token>") if token else text
    return re.sub(r"bot\d+:[\w-]+", "bot<token>", text)


def _load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        state = {}
    state.setdefault("offset", 0)
    state.setdefault("conversations", {})
    state.setdefault("unfinished", {})   # chat -> message being answered right now
    state.setdefault("resumable", {})    # id -> a message offered back after a restart
    return state


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


_pairing: dict[str, Any] = {"code": "", "expires": 0.0, "attempts": 0}


def new_pairing_code() -> dict:
    _pairing.update(code=f"{secrets.randbelow(10**6):06d}",
                    expires=time.time() + PAIRING_TTL, attempts=0)
    audit.log("telegram_pairing_started")
    return status()


def _pairing_active() -> bool:
    return bool(_pairing["code"]) and time.time() < _pairing["expires"]


def allowed_users() -> list[dict]:
    return list(settings.get("telegram.allowed_users", []) or [])


def is_allowed(user_id: int | None) -> bool:
    return user_id is not None and any(u.get("id") == user_id for u in allowed_users())


def unpair(user_id: int) -> dict:
    settings.update({"telegram": {"allowed_users":
                                  [u for u in allowed_users() if u.get("id") != user_id]}})
    audit.log("telegram_unpaired", user_id=user_id)
    return status()


# --- formatting -------------------------------------------------------------------

_INLINE = re.compile(
    r"\[(?P<link>[^\]]+)\]\((?P<url>https?://[^)\s\"]+)\)"
    r"|\*\*(?P<bold>[^*]+)\*\*"
    r"|`(?P<code>[^`]+)`")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")


def _inline_html(text: str) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        if m.group("link"):
            out.append(f'<a href="{html.escape(m.group("url"))}">'
                       f'{html.escape(m.group("link"), quote=False)}</a>')
        elif m.group("bold"):
            out.append(f"<b>{html.escape(m.group('bold'), quote=False)}</b>")
        else:
            out.append(f"<code>{html.escape(m.group('code'), quote=False)}</code>")
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def to_telegram_html(markdown: str) -> str:
    """The Markdown models write -> the small HTML subset Telegram renders.
    Every tag is generated here, so the output is always well-formed."""
    parts = re.split(r"```[^\n]*\n(.*?)```", markdown, flags=re.S)
    out = []
    for i, part in enumerate(parts):
        if i % 2:  # inside a code fence
            out.append(f"<pre>{html.escape(part.rstrip(), quote=False)}</pre>")
            continue
        lines = []
        for line in part.split("\n"):
            if m := _HEADING.match(line.strip()):
                lines.append(f"<b>{_inline_html(m.group(1))}</b>")
            elif m := _BULLET.match(line):
                lines.append(f"{m.group(1)}• {_inline_html(m.group(2))}")
            else:
                lines.append(_inline_html(line))
        out.append("\n".join(lines))
    return "".join(out).strip()


def _chunks(text: str, size: int = CHUNK) -> list[str]:
    """Split on paragraph, then line, boundaries so each piece fits a message."""
    chunks, buf = [], ""
    for para in re.split(r"(\n\n)", text):
        if len(buf) + len(para) <= size:
            buf += para
            continue
        if buf.strip():
            chunks.append(buf)
        buf = para
        while len(buf) > size:
            cut = buf.rfind("\n", 0, size)
            cut = cut if cut > size // 2 else size
            chunks.append(buf[:cut])
            buf = buf[cut:]
    if buf.strip():
        chunks.append(buf)
    return chunks or [text[:size]]


def _speakable(text: str) -> str:
    """Strip what shouldn't be read aloud: code, URLs, markup, the Sources list."""
    text = re.split(r"\n\s*(?:#+\s*)?\**sources:?\**\s*\n", text, flags=re.I)[0]
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s?\[\d+(?:[,–-]\s?\d+)*\]", "", text)     # citation markers
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _wav_to_ogg_opus(wav: bytes) -> bytes | None:
    """Telegram shows voice bubbles only for OGG/Opus. PyAV comes with
    faster-whisper; if it can't encode, the caller falls back to WAV."""
    try:
        import av
        out = io.BytesIO()
        with av.open(io.BytesIO(wav)) as src, av.open(out, "w", format="ogg") as dst:
            stream = dst.add_stream("libopus", rate=48000, layout="mono")
            stream.bit_rate = 32000
            resampler = av.AudioResampler(format="s16", layout="mono", rate=48000,
                                          frame_size=960)
            for frame in src.decode(audio=0):
                for f in resampler.resample(frame):
                    for packet in stream.encode(f):
                        dst.mux(packet)
            for f in resampler.resample(None):
                for packet in stream.encode(f):
                    dst.mux(packet)
            for packet in stream.encode(None):
                dst.mux(packet)
        return out.getvalue()
    except Exception:
        return None


def _yes_no(text: str) -> bool | None:
    """'yes', 'Yes, send it.', 'no thanks' -> True/False; anything longer or
    unclear -> None (it's a new request, not an answer)."""
    words = re.sub(r"[^\w\s'👍👎✅❌]", " ", text.lower()).split()
    if not words or len(words) > 3:
        return None
    return True if words[0] in _YES else False if words[0] in _NO else None


# --- Bot API client -------------------------------------------------------------

class TelegramAPI:
    def __init__(self, token: str, base: str = API_BASE,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._token = token
        self._base = base
        # read timeout > the 50 s long-poll so getUpdates isn't cut off
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30, read=70),
                                         transport=transport)

    async def call(self, method: str, files: dict | None = None, **params) -> Any:
        url = f"{self._base}/bot{self._token}/{method}"
        params = {k: v for k, v in params.items() if v is not None}
        if files:
            data = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                    for k, v in params.items()}
            r = await self._client.post(url, data=data, files=files, timeout=120)
        else:
            r = await self._client.post(url, json=params)
        try:
            body = r.json()
        except ValueError:
            raise TelegramError(f"HTTP {r.status_code}", r.status_code) from None
        if not body.get("ok"):
            raise TelegramError(body.get("description", f"HTTP {r.status_code}"),
                                body.get("error_code", r.status_code))
        return body["result"]

    async def download(self, file_id: str) -> bytes:
        info = await self.call("getFile", file_id=file_id)
        r = await self._client.get(f"{self._base}/file/bot{self._token}/{info['file_path']}")
        r.raise_for_status()
        return r.content

    async def aclose(self) -> None:
        await self._client.aclose()


# --- per-turn session -------------------------------------------------------------

class TelegramSession(ChannelSession):
    name = "Telegram"

    def __init__(self, bot: "TelegramBot", chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.sent_files: list[Path] = []

    @property
    def allow_dangerous(self) -> bool:  # type: ignore[override]
        return bool(settings.get("telegram.allow_dangerous", False))

    async def send_file(self, path: Path, caption: str = "") -> str:
        try:
            await self.bot.api.call("sendChatAction", chat_id=self.chat_id,
                                    action="upload_document")
            data = await asyncio.to_thread(path.read_bytes)
            await self.bot.api.call("sendDocument", chat_id=self.chat_id,
                                    caption=caption[:1024] or None,
                                    files={"document": (path.name, data)})
        except (TelegramError, httpx.HTTPError, OSError) as e:
            return f"Could not send {path.name}: {_redact(str(e))}"
        self.sent_files.append(path)
        audit.log("telegram_file_sent", path=str(path), bytes=len(data))
        return f"Sent {path.name} ({len(data) // 1024} KB) to the user's phone via Telegram."


# --- the bot ----------------------------------------------------------------------

class TelegramBot:
    def __init__(self, token: str, api: TelegramAPI | None = None) -> None:
        self.api = api or TelegramAPI(token)
        self.username = ""
        self.error = ""
        self.state = _load_state()
        self._poller: asyncio.Task | None = None
        self._queues: dict[int, asyncio.Queue] = {}
        self._workers: dict[int, asyncio.Task] = {}
        self._turns: dict[int, asyncio.Task] = {}
        self._pending: dict[int, dict] = {}       # chat -> open confirmation
        self._warned: set[int] = set()
        self._side_tasks: set[asyncio.Task] = set()
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._poller is not None and not self._poller.done()

    @property
    def connected(self) -> bool:
        return self.running and bool(self.username) and not self.error

    def start(self) -> None:
        self._poller = asyncio.create_task(self._poll())

    async def _connect(self) -> None:
        me = await self.api.call("getMe")
        await self.api.call("deleteWebhook")  # polling and webhooks are exclusive
        try:
            await self.api.call("setMyCommands", commands=[
                {"command": "new", "description": "Start a fresh conversation"},
                {"command": "stop", "description": "Stop what Jarvis is doing"},
                {"command": "help", "description": "What Jarvis can do"}])
        except TelegramError:
            pass  # cosmetic
        self.username = me.get("username", "")
        audit.log("telegram_started", bot=self.username)
        await self._offer_unfinished()

    async def _offer_unfinished(self) -> None:
        """Messages Jarvis was still answering when it quit or restarted. They
        aren't silently dropped — nor re-run blindly (half of it may already
        have happened, like an email sent): the user gets a button to run it."""
        unfinished, self.state["unfinished"] = self.state.get("unfinished", {}), {}
        for chat, item in unfinished.items():
            if time.time() - item.get("at", 0) > 24 * 3600:
                continue
            rid = secrets.token_hex(4)
            self.state["resumable"][rid] = {"chat": int(chat), "text": item["text"],
                                            "voice": item.get("voice", False)}
            quoted = item["text"] if len(item["text"]) <= 120 else item["text"][:117] + "…"
            try:
                await self.api.call(
                    "sendMessage", chat_id=int(chat),
                    text=f"↩️ I restarted before I finished answering:\n“{quoted}”",
                    reply_markup={"inline_keyboard": [[
                        {"text": "▶️ Answer it now", "callback_data": f"resume:{rid}"}]]})
            except (TelegramError, httpx.HTTPError):
                pass
        _save_state(self.state)

    async def stop(self) -> None:
        self._stopping = True    # turns cut short now stay "unfinished" for next time
        tasks = [t for t in (self._poller, *self._workers.values(), *self._turns.values(),
                             *self._side_tasks) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()
        self._queues.clear()
        await self.api.aclose()

    async def _poll(self) -> None:
        """Connect, then long-poll forever. Network trouble (no Wi-Fi at boot,
        Telegram down) is retried with backoff; only a revoked token stops it."""
        backoff = 1
        while True:
            try:
                if not self.username:
                    await self._connect()
                updates = await self.api.call(
                    "getUpdates", offset=self.state["offset"], timeout=50,
                    allowed_updates=["message", "callback_query"])
                backoff, self.error = 1, ""
            except TelegramError as e:
                if e.code == 401:
                    self.error = "Telegram rejected the bot token — paste a new one."
                    return
                self.error = ("Another program is reading this bot's messages."
                              if e.code == 409 else f"Telegram error: {_redact(str(e))}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            except httpx.HTTPError:
                self.error = "Can't reach Telegram — retrying."
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            for update in updates:
                # Confirm each update before acting on it, so a crash or
                # restart can never run the same request twice.
                self.state["offset"] = update["update_id"] + 1
                _save_state(self.state)
                try:
                    await self.handle(update)
                except Exception as e:  # one bad update must not stop the bot
                    audit.log("telegram_error", error=_redact(str(e)))

    # -- incoming ------------------------------------------------------------------

    async def handle(self, update: dict) -> None:
        """Route one update. Runs on the polling loop, so it stays fast: real
        work (downloads, transcription, the chat turn) goes to a worker."""
        if cq := update.get("callback_query"):
            await self._on_button(cq)
            return
        msg = update.get("message")
        if not msg or msg.get("chat", {}).get("type") != "private":
            return  # never act on group chats
        chat_id = msg["chat"]["id"]
        user = msg.get("from", {})
        text = (msg.get("text") or msg.get("caption") or "").strip()

        if text.lower().startswith("/start pair_"):  # t.me deep link from Settings
            text = "/pair " + text.split("pair_", 1)[1]
        if text.lower().startswith("/pair"):
            await self._pair(chat_id, user, text)
            return
        if not is_allowed(user.get("id")):
            audit.log("telegram_unauthorized", user_id=user.get("id"),
                      username=user.get("username", ""))
            if user.get("id") not in self._warned:
                self._warned.add(user.get("id"))
                await self.send_text(
                    chat_id, "🔒 This Jarvis is private. If it's yours: on your Mac "
                    "open Jarvis → Settings → Phone, tap “Pair a phone”, and send "
                    "me /pair followed by the code.")
            return

        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if command in ("/start", "/help"):
            await self.send_text(chat_id, HELP.format(name=settings.get("assistant.name", "Jarvis")))
            return
        if command == "/new":
            self.state["conversations"].pop(str(chat_id), None)
            _save_state(self.state)
            await self.send_text(chat_id, "🆕 Fresh conversation started.")
            return
        if command == "/stop":
            turn = self._turns.get(chat_id)
            if turn and not turn.done():
                turn.cancel()
                await self.send_text(chat_id, "⏹ Stopped.")
            else:
                await self.send_text(chat_id, "Nothing is running.")
            return

        if chat_id in self._pending:
            is_voice = bool(msg.get("voice") or msg.get("audio"))
            verdict = _yes_no(text) if text else None
            if verdict is not None:
                await self._resolve(chat_id, verdict)
                return
            if is_voice:  # "yes, send it" by voice: transcribe off the poll loop
                task = asyncio.create_task(self._voice_answer(chat_id, msg))
                self._side_tasks.add(task)  # keep a reference until it finishes
                task.add_done_callback(self._side_tasks.discard)
                return
            # Anything else while a question is open counts as "no" — the new
            # message is the user moving on.
            await self._resolve(chat_id, False)

        self._enqueue(chat_id, msg)

    def _enqueue(self, chat_id: int, msg: dict) -> None:
        if chat_id not in self._queues:
            self._queues[chat_id] = asyncio.Queue()
            self._workers[chat_id] = asyncio.create_task(self._worker(chat_id))
        self._queues[chat_id].put_nowait(msg)

    async def _worker(self, chat_id: int) -> None:
        """Messages from one chat run one at a time, in order."""
        queue = self._queues[chat_id]
        while True:
            msg = await queue.get()
            turn = asyncio.create_task(self._process(chat_id, msg))
            self._turns[chat_id] = turn
            try:
                await asyncio.wait({turn})
            except asyncio.CancelledError:
                turn.cancel()
                raise
            finally:
                self._turns.pop(chat_id, None)
            if not turn.cancelled() and (e := turn.exception()):
                audit.log("telegram_error", error=_redact(str(e)))
                try:
                    await self.send_text(chat_id, f"⚠️ Something went wrong: "
                                                  f"{_redact(str(e))[:300]}")
                except (TelegramError, httpx.HTTPError):
                    pass  # keep serving this chat even if Telegram is flaky

    async def _voice_answer(self, chat_id: int, msg: dict) -> None:
        text = await self._transcribe(chat_id, msg)
        if text is None:
            return
        verdict = _yes_no(text)
        if chat_id in self._pending:
            await self._resolve(chat_id, bool(verdict))
        if verdict is None:  # not an answer — it's a new request
            self._enqueue(chat_id, {**msg, "voice": None, "audio": None,
                                    "text": text, "_voice_in": True})

    async def _transcribe(self, chat_id: int, msg: dict) -> str | None:
        from ..speech import stt
        media = msg.get("voice") or msg.get("audio") or {}
        try:
            audio = await self.api.download(media["file_id"])
        except (TelegramError, httpx.HTTPError, KeyError) as e:
            await self.send_text(chat_id, f"⚠️ Couldn't download the voice note: {_redact(str(e))}")
            return None
        result = await stt.transcribe(audio)
        if result.get("error") or not result.get("text"):
            await self.send_text(
                chat_id, "⚠️ I couldn't understand that voice note"
                + (f" ({result['error']}). On the Mac, download Whisper under "
                   "Settings → Voice." if result.get("error") else "."))
            return None
        await self.send_text(chat_id, f"🎙 “{result['text']}”")
        return result["text"]

    async def _receive_file(self, chat_id: int, conv_id: str, msg: dict) -> str:
        """Save a file the user sent to ~/Downloads/Jarvis and attach it to the
        conversation. Returns a note for the model ('' if nothing usable)."""
        if msg.get("document"):
            media = msg["document"]
            name = Path(media.get("file_name") or "file").name
        elif msg.get("photo"):
            media = msg["photo"][-1]  # largest size
            name = time.strftime("photo-%Y%m%d-%H%M%S.jpg")
        else:
            return ""
        if (media.get("file_size") or 0) > MAX_DOWNLOAD:
            await self.send_text(chat_id, "⚠️ Telegram only lets bots download files up "
                                          "to 20 MB, so I couldn't get that one.")
            return ""
        try:
            data = await self.api.download(media["file_id"])
        except (TelegramError, httpx.HTTPError) as e:
            await self.send_text(chat_id, f"⚠️ Couldn't download the file: {_redact(str(e))}")
            return ""
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        path, n = INBOX_DIR / name, 2
        while path.exists():
            path = INBOX_DIR / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        path.write_bytes(data)
        audit.log("telegram_file_received", path=str(path), bytes=len(data))
        attached = ""
        try:
            from ..knowledge import attachments
            # A photo's caption is usually the question ("what plant is this?"):
            # let the vision model look for exactly that.
            await attachments.ingest(conv_id, path.name, data,
                                     question=(msg.get("caption") or "").strip())
            attached = " Its contents are attached to this conversation."
        except Exception:
            pass
        return (f"[The user sent the file “{path.name}” from their phone. It is saved "
                f"on the Mac at {path}.{attached}]")

    # -- a chat turn -----------------------------------------------------------------

    def _conversation(self, chat_id: int) -> str:
        conv_id = self.state["conversations"].get(str(chat_id))
        if conv_id and db.get_conversation(conv_id):
            return conv_id
        conv = db.create_conversation(title="📱 Phone chat")
        db.rename_conversation(conv["id"], folder="Phone")
        self.state["conversations"][str(chat_id)] = conv["id"]
        _save_state(self.state)
        return conv["id"]

    async def _process(self, chat_id: int, msg: dict) -> None:
        conv_id = self._conversation(chat_id)
        text = (msg.get("text") or msg.get("caption") or "").strip()
        voice_in = bool(msg.get("_voice_in"))
        if msg.get("voice") or msg.get("audio"):
            spoken = await self._transcribe(chat_id, msg)
            if spoken is None:
                return
            text, voice_in = spoken, True
        if note := await self._receive_file(chat_id, conv_id, msg):
            text = f"{text}\n\n{note}".strip() if text else (
                f"{note}\nAcknowledge it briefly and ask what they'd like done with it.")
        if text:
            audit.log("telegram_message", chars=len(text), voice=voice_in)
            self.state["unfinished"][str(chat_id)] = {"text": text, "voice": voice_in,
                                                      "at": time.time()}
            _save_state(self.state)
            try:
                await self._run_turn(chat_id, conv_id, text, voice_in)
            finally:
                if not self._stopping:    # answered (or stopped on purpose)
                    self.state["unfinished"].pop(str(chat_id), None)
                    _save_state(self.state)

    async def _run_turn(self, chat_id: int, conv_id: str, text: str, voice_in: bool) -> None:
        from .. import ui_bridge
        ui_bridge.track(asyncio.current_task())   # the emergency stop can cancel it
        session = TelegramSession(self, chat_id)
        token = current.set(session)
        typing = asyncio.create_task(self._keep_typing(chat_id))
        status: dict = {"message_id": None, "steps": []}
        final, failed = "", False
        try:
            async for event in chat_service.run_chat(conv_id, text, spoken=voice_in):
                kind = event.get("type")
                if kind == "tool_start":
                    await self._expire_pending(chat_id)
                    await self._progress(chat_id, status, event["name"])
                elif kind == "tool_result":
                    await self._expire_pending(chat_id)
                elif kind == "confirm_request":
                    await self._ask(chat_id, event)
                elif kind == "plan":
                    await self.send_text(chat_id, "📋 Plan:\n" + "\n".join(
                        f"{i + 1}. {s}" for i, s in enumerate(event["steps"])))
                elif kind == "error":
                    failed = True
                    await self.send_text(chat_id, f"⚠️ {event['message']}")
                elif kind == "done":
                    final = event.get("content", "")
        finally:
            current.reset(token)
            typing.cancel()
            await self._expire_pending(chat_id, "⏹ Cancelled")

        if final.strip():
            await self.send_markdown(chat_id, final)
            if voice_in and settings.get("telegram.voice_replies", True):
                await self._send_voice(chat_id, final)
        elif not failed and not session.sent_files:
            await self.send_text(chat_id, "✅ Done.")

    async def _keep_typing(self, chat_id: int) -> None:
        try:
            while True:
                try:
                    await self.api.call("sendChatAction", chat_id=chat_id, action="typing")
                except (TelegramError, httpx.HTTPError):
                    pass
                await asyncio.sleep(4.5)  # the indicator lasts ~5 s
        except asyncio.CancelledError:
            pass

    async def _progress(self, chat_id: int, status: dict, tool_name: str) -> None:
        """One status message, edited as tools run: 🔎 Searching → 📖 Reading…"""
        label = TOOL_LABELS.get(tool_name, f"⚙️ {tool_name}")
        if status["steps"] and status["steps"][-1] == label:
            return
        status["steps"].append(label)
        text = "\n".join(status["steps"][-8:])
        try:
            if status["message_id"] is None:
                sent = await self.api.call("sendMessage", chat_id=chat_id, text=text,
                                           disable_notification=True)
                status["message_id"] = sent["message_id"]
            else:
                await self.api.call("editMessageText", chat_id=chat_id,
                                    message_id=status["message_id"], text=text)
        except (TelegramError, httpx.HTTPError):
            pass

    # -- confirmations -------------------------------------------------------------

    async def _ask(self, chat_id: int, event: dict) -> None:
        args = json.dumps(event.get("arguments", {}), ensure_ascii=False, indent=1)
        if len(args) > 700:
            args = args[:700] + " …"
        icon = "⚠️" if event.get("risk") == "dangerous" else "🔐"
        text = (f"{icon} Jarvis wants to run <b>{html.escape(event['tool'])}</b>\n"
                f"<pre>{html.escape(args, quote=False)}</pre>\nAllow it?")
        buttons = {"inline_keyboard": [[
            {"text": "✅ Allow", "callback_data": f"ok:{event['id']}"},
            {"text": "❌ Deny", "callback_data": f"no:{event['id']}"}]]}
        sent = await self.api.call("sendMessage", chat_id=chat_id, text=text,
                                   parse_mode="HTML", reply_markup=buttons)
        self._pending[chat_id] = {"id": event["id"], "tool": event["tool"],
                                  "message_id": sent["message_id"]}

    async def _on_button(self, cq: dict) -> None:
        chat_id = cq.get("message", {}).get("chat", {}).get("id")
        verdict, _, confirm_id = (cq.get("data") or "").partition(":")
        note = None
        if not is_allowed(cq.get("from", {}).get("id")):
            note = "Not authorized"
        elif verdict == "resume":
            item = self.state["resumable"].pop(confirm_id, None)
            _save_state(self.state)
            if item and item["chat"] == chat_id:
                self._enqueue(chat_id, {"text": item["text"], "_voice_in": item["voice"]})
                note = "On it"
            else:
                note = "Already answered"
        elif self._pending.get(chat_id, {}).get("id") == confirm_id:
            await self._resolve(chat_id, verdict == "ok")
        else:
            note = "That request already expired"
        try:
            await self.api.call("answerCallbackQuery", callback_query_id=cq["id"], text=note)
        except (TelegramError, httpx.HTTPError):
            pass

    async def _resolve(self, chat_id: int, approved: bool) -> None:
        pending = self._pending.pop(chat_id, None)
        if pending is None:
            return
        live = confirmations.resolve(pending["id"], approved)
        label = ("✅ Allowed" if approved else "❌ Denied") if live else "⌛ Expired"
        await self._close_question(chat_id, pending, label)

    async def _expire_pending(self, chat_id: int, label: str = "⌛ No answer — skipped") -> None:
        """The turn moved past an open question (timed out or cancelled)."""
        pending = self._pending.pop(chat_id, None)
        if pending is not None:
            await self._close_question(chat_id, pending, label)

    async def _close_question(self, chat_id: int, pending: dict, label: str) -> None:
        try:
            await self.api.call("editMessageText", chat_id=chat_id,
                                message_id=pending["message_id"],
                                text=f"{label}: {pending['tool']}")
        except (TelegramError, httpx.HTTPError):
            pass

    async def _pair(self, chat_id: int, user: dict, text: str) -> None:
        user_id = user.get("id")
        code = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ""
        if is_allowed(user_id):
            await self.send_text(chat_id, "✅ This account is already paired.")
            return
        if not _pairing_active():
            await self.send_text(chat_id, "No pairing in progress. On your Mac open "
                                          "Jarvis → Settings → Phone → “Pair a phone”.")
            return
        if not hmac.compare_digest(code, _pairing["code"]):
            _pairing["attempts"] += 1
            audit.log("telegram_pair_failed", user_id=user_id,
                      username=user.get("username", ""))
            if _pairing["attempts"] >= PAIRING_MAX_ATTEMPTS:
                _pairing.update(code="", expires=0.0)
                await self.send_text(chat_id, "Too many wrong codes — create a new one on the Mac.")
            else:
                await self.send_text(chat_id, "❌ Wrong code.")
            return
        name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) \
            or user.get("username") or str(user_id)
        settings.update({"telegram": {"allowed_users": [
            *allowed_users(), {"id": user_id, "name": name,
                               "username": user.get("username", "")}]}})
        _pairing.update(code="", expires=0.0)
        self._warned.discard(user_id)
        audit.log("telegram_paired", user_id=user_id, username=user.get("username", ""))
        await self.send_text(chat_id, "🔗 Paired! " + HELP.format(
            name=settings.get("assistant.name", "Jarvis")))

    # -- outgoing ------------------------------------------------------------------

    async def send_text(self, chat_id: int, text: str) -> None:
        for chunk in _chunks(text):
            await self.api.call("sendMessage", chat_id=chat_id, text=chunk)

    async def send_markdown(self, chat_id: int, markdown: str) -> None:
        for chunk in _chunks(markdown):
            try:
                await self.api.call("sendMessage", chat_id=chat_id, parse_mode="HTML",
                                    text=to_telegram_html(chunk) or chunk,
                                    link_preview_options={"is_disabled": True})
            except TelegramError:  # formatting rejected — plain text always works
                await self.api.call("sendMessage", chat_id=chat_id, text=chunk)

    async def _send_voice(self, chat_id: int, text: str) -> None:
        from ..speech import engines
        speech = _speakable(text)[:1200]
        if not speech:
            return
        wav = await engines.synthesize(speech)
        if not wav:
            return  # browser-only TTS configured: text reply is enough
        try:
            await self.api.call("sendChatAction", chat_id=chat_id, action="record_voice")
            ogg = await asyncio.to_thread(_wav_to_ogg_opus, wav)
            if ogg:
                await self.api.call("sendVoice", chat_id=chat_id,
                                    files={"voice": ("reply.ogg", ogg)})
            else:
                await self.api.call("sendAudio", chat_id=chat_id,
                                    files={"audio": ("reply.wav", wav)})
        except (TelegramError, httpx.HTTPError):
            pass


# --- lifecycle (used by main.py and the API) -----------------------------------------

_bot: TelegramBot | None = None
_last_error = ""


async def start() -> None:
    """(Re)start the bot if it's enabled and has a token; otherwise stop it."""
    global _bot, _last_error
    await stop()
    token = read_token()
    if not token or not settings.get("telegram.enabled", False):
        return
    _bot, _last_error = TelegramBot(token), ""
    _bot.start()


async def stop() -> None:
    global _bot
    if _bot is not None:
        bot, _bot = _bot, None
        await bot.stop()


async def set_token(token: str) -> dict:
    token = token.strip()
    if not re.fullmatch(r"\d+:[\w-]{30,}", token):
        return {**status(), "token_error": "That doesn't look like a bot token "
                                           "(it looks like 123456789:AAH…)."}
    api = TelegramAPI(token)
    try:
        await api.call("getMe")
    except TelegramError as e:
        return {**status(), "token_error": f"Telegram rejected this token ({e})."}
    except httpx.HTTPError:
        return {**status(), "token_error": "Can't reach Telegram — check your internet connection."}
    finally:
        await api.aclose()
    _write_token(token)
    settings.update({"telegram": {"enabled": True}})
    if not allowed_users():
        new_pairing_code()
    audit.log("telegram_token_set")
    await start()
    return status()


async def forget_token() -> dict:
    await stop()
    TOKEN_FILE.unlink(missing_ok=True)
    settings.update({"telegram": {"enabled": False}})
    audit.log("telegram_token_removed")
    return status()


def status() -> dict:
    return {
        "configured": bool(read_token()),
        "enabled": bool(settings.get("telegram.enabled", False)),
        "running": bool(_bot and _bot.running),
        "connected": bool(_bot and _bot.connected),
        "bot_username": _bot.username if _bot else "",
        "error": (_bot.error if _bot else _last_error) if read_token() else "",
        "pairing_code": _pairing["code"] if _pairing_active() else "",
        "pairing_expires_in": max(0, int(_pairing["expires"] - time.time()))
        if _pairing_active() else 0,
        "allowed_users": allowed_users(),
        "allow_dangerous": bool(settings.get("telegram.allow_dangerous", False)),
        "voice_replies": bool(settings.get("telegram.voice_replies", True)),
    }

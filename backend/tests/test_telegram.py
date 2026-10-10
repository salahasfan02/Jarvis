"""End-to-end tests for the Telegram channel against a fake Bot API and a
scripted fake LLM: pairing, research -> Word doc -> send, confirmations by
button and by text, the phone's dangerous-tool block, files and voice in."""
from __future__ import annotations

import asyncio
import email.policy
import io
import json
import math
import struct
import wave
from email.parser import BytesParser
from pathlib import Path

import docx
import httpx
import pytest

from app.channels import telegram as tg
from app.config import settings
from app.llm import ollama_client
from app.tools.base import registry

USER = {"id": 42, "first_name": "Sam", "username": "sam"}
STRANGER = {"id": 666, "first_name": "Eve"}


class FakeTelegram:
    """Just enough of the Bot API, recording every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, dict]] = []
        self.files: dict[str, bytes] = {}
        self.updates: list[dict] = []
        self._next_id = 100

    def sent(self, method: str) -> list[dict]:
        return [p | {"_files": f} for m, p, f in self.calls if m == method]

    def texts(self) -> list[str]:
        return [p.get("text", "") for p in self.sent("sendMessage")]

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/file/"):
            return httpx.Response(200, content=self.files[path.rsplit("/", 1)[1]])
        method = path.rsplit("/", 1)[1]
        params, files = self._parse(request)
        self.calls.append((method, params, files))
        if method == "getUpdates":
            if not self.updates:
                await asyncio.sleep(0.02)
            result, self.updates = self.updates, []
        elif method == "getMe":
            result = {"id": 1, "is_bot": True, "username": "jarvis_test_bot"}
        elif method == "getFile":
            result = {"file_id": params["file_id"], "file_path": f"docs/{params['file_id']}"}
        elif method.startswith("send"):
            self._next_id += 1
            result = {"message_id": self._next_id}
        else:
            result = True
        return httpx.Response(200, json={"ok": True, "result": result})

    @staticmethod
    def _parse(request: httpx.Request) -> tuple[dict, dict]:
        ctype = request.headers.get("content-type", "")
        body = request.read()
        if ctype.startswith("application/json"):
            return json.loads(body or b"{}"), {}
        msg = BytesParser(policy=email.policy.HTTP).parsebytes(
            b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
        fields, files = {}, {}
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            payload = part.get_payload(decode=True)
            if part.get_filename():
                files[name] = (part.get_filename(), payload)
            else:
                fields[name] = payload.decode()
        return fields, files


class ScriptedLLM:
    """Stands in for Ollama: each round, the next step decides from the
    messages so far whether to call a tool or answer."""

    def __init__(self, steps) -> None:
        self.steps = list(steps)
        self.rounds: list[dict] = []

    async def chat_stream(self, messages, model=None, tools=None):
        self.rounds.append({"messages": [dict(m) for m in messages],
                            "tools": [t["function"]["name"] for t in tools or []]})
        kind, *rest = self.steps.pop(0)(messages) if self.steps else ("text", "(done)")
        if kind == "tool":
            name, args = rest
            yield {"message": {"content": "", "tool_calls": [
                {"function": {"name": name, "arguments": args}}]}, "done": True}
        else:
            yield {"message": {"content": rest[0]}, "done": True}


def tool(name, args):
    return lambda msgs: ("tool", name, args)


def answer(text):
    return lambda msgs: ("text", text)


def last_tool_output(messages) -> str:
    return next(m["content"] for m in reversed(messages) if m["role"] == "tool")


def message(text="", user=USER, **extra):
    return {"update_id": 0, "message": {"message_id": 1, "from": user,
                                        "chat": {"id": user["id"], "type": "private"},
                                        "text": text, **extra}}


def button(data, user=USER):
    return {"update_id": 0, "callback_query": {
        "id": "cb1", "from": user, "data": data,
        "message": {"message_id": 5, "chat": {"id": user["id"], "type": "private"}}}}


async def until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for the bot")
        await asyncio.sleep(0.01)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "STATE_FILE", tmp_path / "telegram_state.json")
    monkeypatch.setattr(tg, "INBOX_DIR", tmp_path / "inbox")
    settings.update({"telegram": {"allowed_users": [{"id": USER["id"], "name": "Sam"}],
                                  "allow_dangerous": False, "voice_replies": True}})
    fake = FakeTelegram()

    def make_bot():
        api = tg.TelegramAPI("123:" + "x" * 35, transport=httpx.MockTransport(fake.handler))
        return tg.TelegramBot("unused", api=api)

    def script(*steps):
        llm = ScriptedLLM(steps)
        monkeypatch.setattr(ollama_client, "chat_stream", llm.chat_stream)
        return llm

    return fake, make_bot, script


def run(coro):
    return asyncio.run(coro)


# --- access control -----------------------------------------------------------------

def test_strangers_are_turned_away_and_pairing_needs_the_code(env):
    fake, make_bot, script = env
    llm = script()
    settings.update({"telegram": {"allowed_users": []}})

    async def main():
        bot = make_bot()
        await bot.handle(message("hi", user=STRANGER))
        await bot.handle(message("hi again", user=STRANGER))
        assert len(fake.texts()) == 1 and "private" in fake.texts()[0]

        await bot.handle(message("/pair 123456"))
        assert "No pairing in progress" in fake.texts()[-1]

        code = tg.new_pairing_code()["pairing_code"]
        await bot.handle(message("/pair 000000" if code != "000000" else "/pair 111111"))
        assert "Wrong code" in fake.texts()[-1]
        await bot.handle(message(f"/pair {code}"))
        assert "Paired" in fake.texts()[-1]
        assert tg.is_allowed(USER["id"]) and not tg.is_allowed(STRANGER["id"])
        assert tg.status()["pairing_code"] == ""  # one-time

        # the t.me deep link from Settings pairs in one tap
        other = {"id": 7, "first_name": "Max"}
        code = tg.new_pairing_code()["pairing_code"]
        await bot.handle(message(f"/start pair_{code}", user=other))
        assert tg.is_allowed(7)
        await bot.stop()

    run(main())
    assert llm.rounds == []  # nobody unpaired ever reached the model


def test_group_chats_are_ignored(env):
    fake, make_bot, script = env
    script()

    async def main():
        bot = make_bot()
        update = message("run something")
        update["message"]["chat"]["type"] = "group"
        await bot.handle(update)
        await bot.stop()

    run(main())
    assert fake.calls == []


# --- the two headline flows ---------------------------------------------------------

def test_research_into_a_word_doc_sent_to_the_phone(env):
    fake, make_bot, script = env
    report = ("## Top picks\n- **Lectric XP** — $999\n- Aventon Pace — $1,399\n\n"
              "## Sources\n- [Review](https://example.com/review)")
    llm = script(
        tool("create_word_document", {"title": "Budget e-bikes", "content": report}),
        lambda msgs: ("tool", "send_file",
                      {"path": last_tool_output(msgs).split(" at ")[1].split(". If")[0]}),
        answer("Here's your **e-bike report** — 2 picks under $1,500."),
    )

    async def main():
        bot = make_bot()
        await bot.handle(message("research budget e-bikes and send me a word doc"))
        await until(lambda: any("reply_markup" in m for m in fake.sent("sendMessage")))
        ask = next(m for m in fake.sent("sendMessage") if "reply_markup" in m)
        assert "send_file" in ask["text"]
        allow = ask["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await bot.handle(button(allow))
        await until(lambda: any("e-bike report" in t for t in fake.texts()))
        await bot.stop()

    run(main())

    # every phone turn gets the remote kit, whatever agent was routed
    assert {"send_file", "search_files", "create_word_document",
            "web_search"} <= set(llm.rounds[0]["tools"])
    docs = fake.sent("sendDocument")
    assert len(docs) == 1
    name, data = docs[0]["_files"]["document"]
    assert name.endswith(".docx")
    body = "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    assert "Lectric XP — $999" in body and "Budget e-bikes" in body
    assert any(p.get("text") == "✅ Allowed: send_file" for p in fake.sent("editMessageText"))
    final = fake.sent("sendMessage")[-1]
    assert final["parse_mode"] == "HTML" and "<b>e-bike report</b>" in final["text"]


def test_send_me_a_file_from_the_mac_confirmed_by_typing_yes(env, tmp_path):
    fake, make_bot, script = env
    lease = tmp_path / "Lease 2026.pdf"
    lease.write_bytes(b"%PDF-1.7 lease")
    script(tool("send_file", {"path": str(lease)}), answer("Sent your lease."))

    async def main():
        bot = make_bot()
        await bot.handle(message("send me my lease pdf"))
        await until(lambda: any("reply_markup" in m for m in fake.sent("sendMessage")))
        await bot.handle(message("yes"))
        await until(lambda: "Sent your lease." in fake.texts())
        await bot.stop()

    run(main())
    assert fake.sent("sendDocument")[0]["_files"]["document"] == ("Lease 2026.pdf", b"%PDF-1.7 lease")


def test_new_message_while_asked_counts_as_no(env, tmp_path):
    fake, make_bot, script = env
    f = tmp_path / "a.txt"
    f.write_text("x")
    llm = script(tool("send_file", {"path": str(f)}), answer("OK, not sending it."),
                 answer("It's 3pm."))

    async def main():
        bot = make_bot()
        await bot.handle(message("send me a.txt"))
        await until(lambda: any("reply_markup" in m for m in fake.sent("sendMessage")))
        await bot.handle(message("actually what time is it"))
        await until(lambda: "It's 3pm." in fake.texts())
        await bot.stop()

    run(main())
    assert fake.sent("sendDocument") == []
    assert "DENIED" in last_tool_output(llm.rounds[1]["messages"])
    assert any(p.get("text") == "❌ Denied: send_file" for p in fake.sent("editMessageText"))


# --- safety --------------------------------------------------------------------------

def test_dangerous_tools_are_blocked_from_the_phone(env, monkeypatch):
    fake, make_bot, script = env
    ran = []
    monkeypatch.setattr(registry.get("run_command"), "handler", lambda **k: ran.append(k))
    llm = script(tool("run_command", {"command": "rm -rf ~/Documents"}),
                 answer("That has to be done at the Mac."))

    async def main():
        bot = make_bot()
        await bot.handle(message("delete my documents folder"))
        await until(lambda: "That has to be done at the Mac." in fake.texts())
        await bot.stop()

    run(main())
    assert ran == []
    assert not any("reply_markup" in m for m in fake.sent("sendMessage"))
    assert "blocked when the user messages from their phone" in last_tool_output(
        llm.rounds[1]["messages"])


def test_dangerous_tools_still_need_approval_when_allowed(env, monkeypatch):
    fake, make_bot, script = env
    settings.update({"telegram": {"allow_dangerous": True}})
    monkeypatch.setattr(registry.get("run_command"), "handler", lambda command: "exit code 0")
    script(tool("run_command", {"command": "uptime"}), answer("Uptime is fine."))

    async def main():
        bot = make_bot()
        await bot.handle(message("check uptime"))
        await until(lambda: any("reply_markup" in m for m in fake.sent("sendMessage")))
        ask = next(m for m in fake.sent("sendMessage") if "reply_markup" in m)
        assert ask["text"].startswith("⚠️")
        deny = ask["reply_markup"]["inline_keyboard"][0][1]["callback_data"]
        await bot.handle(button(deny))
        await until(lambda: "Uptime is fine." in fake.texts())
        await bot.stop()

    run(main())


def test_stale_buttons_do_nothing(env):
    fake, make_bot, script = env
    script()

    async def main():
        bot = make_bot()
        await bot.handle(button("ok:deadbeef"))
        await bot.stop()

    run(main())
    assert fake.sent("answerCallbackQuery")[0]["text"] == "That request already expired"


# --- files and voice in --------------------------------------------------------------

def test_files_sent_from_the_phone_are_saved_and_attached(env, tmp_path):
    fake, make_bot, script = env
    fake.files["F1"] = b"Rent is due on the 1st. Pets allowed."
    llm = script(answer("Rent is due on the 1st."))

    async def main():
        bot = make_bot()
        await bot.handle(message(caption="when is rent due?", document={
            "file_id": "F1", "file_name": "lease.txt", "file_size": 38}))
        await until(lambda: "Rent is due on the 1st." in fake.texts())
        await bot.stop()

    run(main())
    saved = tmp_path / "inbox" / "lease.txt"
    assert saved.read_bytes() == fake.files["F1"]
    prompt = llm.rounds[0]["messages"]
    assert any("ATTACHMENT: lease.txt" in m["content"] for m in prompt if m["role"] == "system")
    assert f"saved on the Mac at {saved}" in prompt[-1]["content"]


def _wav(seconds=0.5, rate=24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(i / 9)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


def test_voice_notes_are_transcribed_and_answered_by_voice(env, monkeypatch):
    fake, make_bot, script = env
    from app.speech import engines, stt

    async def transcribe(audio):
        assert audio == b"OggS-voice"
        return {"text": "what's on my calendar"}

    async def synthesize(text):
        assert "meetings" in text and "**" not in text
        return _wav()

    monkeypatch.setattr(stt, "transcribe", transcribe)
    monkeypatch.setattr(engines, "synthesize", synthesize)
    fake.files["V1"] = b"OggS-voice"
    llm = script(answer("You have **two** meetings today."))

    async def main():
        bot = make_bot()
        await bot.handle(message(voice={"file_id": "V1", "duration": 2}))
        await until(lambda: fake.sent("sendVoice") or fake.sent("sendAudio"))
        await bot.stop()

    run(main())
    assert "🎙 “what's on my calendar”" in fake.texts()
    assert llm.rounds[0]["messages"][-1]["content"] == "what's on my calendar"
    voice = (fake.sent("sendVoice") or fake.sent("sendAudio"))[0]["_files"]
    name, data = next(iter(voice.values()))
    assert data[:4] in (b"OggS", b"RIFF")


def test_a_spoken_yes_approves_the_open_question(env, monkeypatch, tmp_path):
    fake, make_bot, script = env
    from app.speech import stt

    async def transcribe(audio):
        return {"text": "Yes, send it."}

    monkeypatch.setattr(stt, "transcribe", transcribe)
    fake.files["V2"] = b"OggS"
    f = tmp_path / "notes.txt"
    f.write_text("hi")
    script(tool("send_file", {"path": str(f)}), answer("Sent."))

    async def main():
        bot = make_bot()
        await bot.handle(message("send me notes.txt"))
        await until(lambda: any("reply_markup" in m for m in fake.sent("sendMessage")))
        await bot.handle(message(voice={"file_id": "V2", "duration": 1}))
        await until(lambda: "Sent." in fake.texts())
        await bot.stop()

    run(main())
    assert fake.sent("sendDocument")[0]["_files"]["document"][0] == "notes.txt"


# --- polling --------------------------------------------------------------------------

def test_polling_connects_and_never_replays_an_update(env):
    fake, make_bot, script = env
    script()
    fake.updates = [{**message("/help"), "update_id": 7}]

    async def main():
        bot = make_bot()
        bot.start()
        await until(lambda: any("/new" in t for t in fake.texts()))
        assert bot.connected and bot.username == "jarvis_test_bot"
        await bot.stop()

    run(main())
    assert json.loads(Path(tg.STATE_FILE).read_text())["offset"] == 8
    polls = fake.sent("getUpdates")
    assert polls[0]["offset"] == 0 and polls[-1]["offset"] == 8
    assert [m for m, _, _ in fake.calls[:2]] == ["getMe", "deleteWebhook"]


# --- formatting -----------------------------------------------------------------------

def test_markdown_to_telegram_html_is_escaped_and_well_formed():
    out = tg.to_telegram_html("# Title\n- **a < b** & `x>1`\n[link](https://e.com/?a=1&b=2)\n"
                              "```py\nif a<b:\n    pass\n```")
    assert out.startswith("<b>Title</b>\n• <b>a &lt; b</b> &amp; <code>x&gt;1</code>")
    assert '<a href="https://e.com/?a=1&amp;b=2">link</a>' in out
    assert "<pre>if a&lt;b:\n    pass</pre>" in out


def test_long_replies_are_split_under_the_limit():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 150 for i in range(12))
    chunks = tg._chunks(text)
    assert len(chunks) > 1 and all(len(c) <= tg.CHUNK for c in chunks)
    assert "".join(chunks) == text


def test_bad_tokens_are_rejected_before_saving():
    result = run(tg.set_token("not-a-token"))
    assert "doesn't look like a bot token" in result["token_error"]
    assert not result["configured"] and not tg.TOKEN_FILE.exists()


def test_yes_no_and_speakable():
    assert tg._yes_no("Yes!") is True and tg._yes_no("nope") is False
    assert tg._yes_no("Yes, send it.") is True and tg._yes_no("no thanks") is False
    assert tg._yes_no("👍") is True
    assert tg._yes_no("what command?") is None
    assert tg._yes_no("ok what about the other file") is None
    assert tg._yes_no("no, send the pdf version instead") is None
    spoken = tg._speakable("**Done.** See [the doc](https://x.y).\n\nSources:\n- https://x.y")
    assert spoken == "Done. See the doc."

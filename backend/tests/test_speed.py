"""Speed work: instant commands, a cache-friendly prompt, fewer AppleScript
round-trips, and the small things that remove model calls."""
import asyncio
import json

import pytest

from app import db
from app.automation import context
from app.chat import quick, service
from app.llm import ollama_client
from app.tools.base import registry
from app.tools.builtin import browser

REAL_EMBED = ollama_client.embed  # captured before conftest's per-test stub


@pytest.fixture
def no_players(monkeypatch):
    monkeypatch.setattr(context, "app_running", lambda name: False)
    monkeypatch.setattr(context, "list_tabs", lambda browser=None: [])  # not the real Safari
    monkeypatch.setattr(quick, "_installed_apps", lambda: {"safari": "Safari",
                                                           "calendar": "Calendar"})


@pytest.mark.parametrize("text,tool,args", [
    ("open youtube", "browser_open", {"url": "https://www.youtube.com"}),
    ("Jarvis, open YouTube.", "browser_open", {"url": "https://www.youtube.com"}),
    ("can you open youtube please", "browser_open", {"url": "https://www.youtube.com"}),
    ("open safari", "open_app", {"name": "Safari"}),
    ("open the calendar app", "open_app", {"name": "Calendar"}),
    ("go to github.com", "browser_open", {"url": "github.com"}),
    ("open drake on youtube", "youtube_play", {"query": "drake"}),
    ("play lofi beats on youtube", "youtube_play", {"query": "lofi beats"}),
    ("search lofi on youtube", "browser_open",
     {"url": "https://www.youtube.com/results?search_query=lofi"}),
])
def test_simple_commands_are_instant(no_players, text, tool, args):
    action = quick.match(text)
    assert action and action.tool == tool and action.arguments == args


@pytest.mark.parametrize("text", [
    "open youtube and play lofi",          # compound -> the model
    "open main.py",                        # a file, not a website
    "open my downloads", "start a timer", "what's the weather",
    "stop",                                # could mean "stop talking"
    "continue",                            # could mean "continue your answer"
    "pause",                               # nothing is playing: never launch Music to pause it
])
def test_everything_else_goes_to_the_model(no_players, text):
    assert quick.match(text) is None


def test_media_commands_pick_the_player_in_use(monkeypatch):
    monkeypatch.setattr(context, "app_running", lambda name: name == "Music")
    monkeypatch.setattr(context, "music_state", lambda: {"running": True, "state": "playing"})
    monkeypatch.setattr(quick, "_youtube_tab_open", lambda: True)
    assert quick.match("pause").tool == "music_control"
    assert quick.match("next song").arguments == {"action": "next"}
    assert quick.match("pause the video").tool == "youtube_control"

    monkeypatch.setattr(context, "music_state", lambda: {"running": True, "state": "paused"})
    action = quick.match("pause")  # Music only paused, a YouTube tab is open -> YouTube
    assert action.tool == "youtube_control" and action.arguments == {"action": "pause"}


def test_instant_command_runs_without_the_model(monkeypatch, no_players):
    opened = []
    monkeypatch.setattr(registry.get("browser_open"), "handler",
                        lambda url, new_window=False: opened.append(url) or f"Opened {url}")

    async def no_model(*a, **k):
        raise AssertionError("the model must not be called")
        yield  # pragma: no cover

    monkeypatch.setattr(ollama_client, "chat_stream", no_model)
    monkeypatch.setattr(ollama_client, "chat_once", no_model)
    conv = db.create_conversation()

    async def main():
        return [e async for e in service.run_chat(conv["id"], "open youtube")]

    events = asyncio.run(main())
    assert opened == ["https://www.youtube.com"]
    done = next(e for e in events if e["type"] == "done")
    assert done["content"] == "Opening YouTube."
    assert {"type": "title", "title": "Open youtube"} in events  # no model call for it


def test_failed_instant_command_says_why(monkeypatch, no_players):
    monkeypatch.setattr(registry.get("browser_open"), "handler",
                        lambda url, new_window=False: "Failed: Safari is not responding")
    conv = db.create_conversation()

    async def main():
        return [e async for e in service.run_chat(conv["id"], "open youtube")]

    done = next(e for e in asyncio.run(main()) if e["type"] == "done")
    assert done["content"] == "Failed: Safari is not responding"


class RecordingLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat_stream(self, messages, model=None, tools=None):
        self.calls.append({"messages": json.loads(json.dumps(messages)),
                           "tools": [t["function"]["name"] for t in tools or []]})
        reply = self.replies.pop(0) if self.replies else {"content": "ok"}
        yield {"message": reply, "done": True, "prompt_eval_count": 42,
               "prompt_eval_duration": 5_000_000, "eval_count": 3, "eval_duration": 1_000_000}


def _turn(conv_id, text):
    async def main():
        return [e async for e in service.run_chat(conv_id, text)]
    return asyncio.run(main())


def test_the_prompt_prefix_stays_identical_between_messages(monkeypatch):
    """Everything before the newest message must be byte-identical across turns,
    or Ollama re-reads thousands of tokens of tool schemas every time."""
    llm = RecordingLLM([{"content": "Hello!"}, {"content": "Sure."}])
    monkeypatch.setattr(ollama_client, "chat_stream", llm.chat_stream)
    ticks = iter(["Monday 09:00", "Monday 09:07"])
    real_block = service._dynamic_block
    monkeypatch.setattr(service, "_dynamic_block",
                        lambda m, c, this="", role="": real_block(m, c, this, role)
                        + f"\nclock {next(ticks)}")
    conv = db.create_conversation()
    _turn(conv["id"], "tell me something interesting about owls")
    _turn(conv["id"], "tell me another interesting fact about owls")

    first, second = llm.calls[0]["messages"], llm.calls[1]["messages"]
    assert first[0] == second[0] and first[0]["role"] == "system"   # static system prompt
    assert "clock" not in first[0]["content"]                        # no clock in it
    assert llm.calls[0]["tools"] == llm.calls[1]["tools"]
    assert second[1]["content"] == "tell me something interesting about owls"  # raw history
    assert second[-1]["content"].startswith("<context>")
    assert second[-1]["content"].endswith("tell me another interesting fact about owls")


def test_tool_results_carry_into_the_next_turn(monkeypatch):
    path = "/Users/sam/Desktop/Screenshot 2026-10-09 at 23.55.30.png"
    monkeypatch.setattr(registry.get("search_files"), "handler",
                        lambda query, directory="": f"2026-10-09 23:55  {path}")
    llm = RecordingLLM([
        {"content": "", "tool_calls": [{"function": {"name": "search_files",
                                                     "arguments": {"query": "Screenshot"}}}]},
        {"content": "I found one from 23:55. Want it?"},
        {"content": "Sending it."},
    ])
    monkeypatch.setattr(ollama_client, "chat_stream", llm.chat_stream)
    conv = db.create_conversation()
    _turn(conv["id"], "find my screenshots")
    _turn(conv["id"], "yes, that one")
    replayed = [m for m in llm.calls[2]["messages"] if m["role"] == "tool"]
    assert replayed and path in replayed[0]["content"]


def test_short_answer_to_a_question_keeps_the_agent(monkeypatch):
    llm = RecordingLLM([{"content": "Which file do you want?"}, {"content": "ok"}])
    monkeypatch.setattr(ollama_client, "chat_stream", llm.chat_stream)
    conv = db.create_conversation()
    first = _turn(conv["id"], "organize the files on my desktop")
    second = _turn(conv["id"], "1. Screenshot 2026-10-09 at 23:55:30")  # "screen" would route to vision
    agent = lambda events: next(e["agent"]["id"] for e in events if e["type"] == "agent")  # noqa: E731
    assert agent(first) == "files" and agent(second) == "files"


def test_empty_replies_are_retried_then_answered_honestly(monkeypatch):
    llm = RecordingLLM([{"content": ""}, {"content": "Here it is."}])
    monkeypatch.setattr(ollama_client, "chat_stream", llm.chat_stream)
    conv = db.create_conversation()
    done = next(e for e in _turn(conv["id"], "hello there my friend") if e["type"] == "done")
    assert done["content"] == "Here it is."
    assert llm.calls[1]["messages"][-1]["content"] == service.EMPTY_NUDGE

    llm2 = RecordingLLM([{"content": ""}, {"content": ""}])
    monkeypatch.setattr(ollama_client, "chat_stream", llm2.chat_stream)
    done = next(e for e in _turn(conv["id"], "hello again my friend") if e["type"] == "done")
    assert done["content"] == service.EMPTY_FALLBACK


def test_turns_report_timing(monkeypatch):
    llm = RecordingLLM([{"content": "hi"}])
    monkeypatch.setattr(ollama_client, "chat_stream", llm.chat_stream)
    conv = db.create_conversation()
    done = next(e for e in _turn(conv["id"], "how are you doing today friend") if e["type"] == "done")
    assert done["timing"]["rounds"] == [{"prompt_tokens": 42, "prompt_ms": 5, "gen_tokens": 3,
                                         "gen_ms": 1, "load_ms": 0}]


def test_embeddings_are_computed_once(monkeypatch):
    from app.config import settings
    calls = []

    async def fake(model, text):
        calls.append(text)
        return [0.1, 0.2]

    monkeypatch.setattr(ollama_client, "embed", REAL_EMBED)
    monkeypatch.setattr(ollama_client, "_embed_uncached", fake)
    monkeypatch.setitem(settings._data["ollama"], "embedding_model", "nomic-embed-text")
    asyncio.run(ollama_client.embed("open the pod bay doors"))
    asyncio.run(ollama_client.embed("open the pod bay doors"))
    assert calls == ["open the pod bay doors"]


# --- browser_open: as few AppleScript launches as possible ---------------------------

@pytest.fixture
def fake_browser(monkeypatch):
    scripts, opened = [], []
    monkeypatch.setattr(context, "browser_name", lambda: "Safari")
    monkeypatch.setattr(context, "app_running", lambda name: True)
    monkeypatch.setattr(browser, "_osascript", lambda s, timeout=15: scripts.append(s) or (True, ""))
    monkeypatch.setattr(browser.subprocess, "run", lambda cmd, **k: opened.append(cmd))
    return scripts, opened


def test_open_youtube_when_its_already_open_just_switches_tab(monkeypatch, fake_browser):
    scripts, _ = fake_browser
    monkeypatch.setattr(context, "list_tabs", lambda b=None: [
        {"index": 1, "title": "Mail", "url": "https://mail.google.com"},
        {"index": 2, "title": "lofi", "url": "https://www.youtube.com/watch?v=abc"}])
    out = browser.browser_open("https://www.youtube.com")
    assert out.startswith("Switched to the existing youtube.com tab")
    assert len(scripts) == 1 and "set URL" not in scripts[0]  # don't reload the video


def test_new_site_opens_one_tab_in_one_script(monkeypatch, fake_browser):
    scripts, _ = fake_browser
    monkeypatch.setattr(context, "list_tabs", lambda b=None: [
        {"index": 1, "title": "Mail", "url": "https://mail.google.com"}])
    browser.browser_open("https://github.com")
    assert len(scripts) == 1 and "make new tab" in scripts[0] and "activate" in scripts[0]


def test_browser_not_running_skips_tab_scripting(monkeypatch, fake_browser):
    scripts, opened = fake_browser
    monkeypatch.setattr(context, "app_running", lambda name: False)
    monkeypatch.setattr(context, "list_tabs", lambda b=None: pytest.fail("no tab listing"))
    browser.browser_open("youtube.com")
    assert scripts == [] and opened == [["open", "-a", "Safari", "https://youtube.com"]]


def test_short_first_messages_title_themselves():
    assert service._short_title("open youtube") == "Open youtube"
    assert service._short_title("please write me a long essay about the history of rome") == ""


def test_mentioning_a_plan_doesnt_summon_the_planner():
    from app.agents import registry as agents
    assert asyncio.run(agents.route("draft an email to sam about the plan")).id == "messaging"
    assert asyncio.run(agents.route("plan my week")).id == "planner"
    assert asyncio.run(agents.route("open safari and then play lofi")).id == "planner"

"""Replay real requests through the real chat pipeline and score them.

Routing, prompts, the model, instant commands and tool-call recovery all run
for real against your local Ollama; only the TOOLS are fake (they record the
call and return a realistic result), so nothing on the Mac is touched.

    cd backend
    .venv/bin/python -m evals.run                      # current models
    .venv/bin/python -m evals.run --model qwen3.5:latest
    .venv/bin/python -m evals.run --only email --verbose
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

REAL_SETTINGS = Path.home() / ".jarvis" / "settings.json"
LEARNED = Path.home() / ".jarvis" / "evals" / "learned.json"   # saved from real mistakes

# Jarvis keeps everything under ~/.jarvis: point it at a throwaway home first.
_home = tempfile.mkdtemp(prefix="jarvis-eval-")
os.environ["HOME"] = _home
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAKE_HOME = "/Users/salah"
TABS = [
    {"index": 1, "title": "GitHub - salahasfan02/Jarvis", "url": "https://github.com/salahasfan02/Jarvis"},
    {"index": 2, "title": "Drake - Janice STFU - YouTube", "url": "https://www.youtube.com/watch?v=abc"},
    {"index": 3, "title": "Inbox (3) - Gmail", "url": "https://mail.google.com/mail/u/0/"},
]
DESKTOP = (f"{FAKE_HOME}/Desktop (6 items):\n[dir] Spain\nCV_Salah_Asfan.pdf\nlease.pdf\n"
           "notes.txt\nScreenshot 2026-10-10 at 23.55.30.png\nScreenshot 2026-10-11 at 00.12.04.png")
DESKTOP_RECENT = (f"{FAKE_HOME}/Desktop (6 items, newest first):\n"
                  f"2026-10-11 00:12  Screenshot 2026-10-11 at 00.12.04.png\n"
                  f"2026-10-10 23:55  Screenshot 2026-10-10 at 23.55.30.png\n"
                  f"2026-10-09 10:00  CV_Salah_Asfan.pdf\n2026-10-01 09:00  lease.pdf\n"
                  f"2026-09-20 18:00  notes.txt\n2026-09-01 12:00  [dir] Spain")


FACTS = [   # (words in the question, title, url, passage)
    (("mcp", "model context"), "What is the Model Context Protocol (MCP)?",
     "https://modelcontextprotocol.io/introduction",
     "MCP (Model Context Protocol) is an open-source standard for connecting AI applications "
     "to external systems: data sources, tools and workflows. An MCP server is a program that "
     "exposes tools, data or reusable workflows to an AI application through the protocol."),
    (("electric", "ev"), "Electric cars explained — Which?", "https://www.which.co.uk/ev",
     "Electric cars run on batteries charged from the grid. They cost more upfront but less to "
     "run; typical ranges are 200-300 miles and public rapid chargers add 100 miles in ~20 min."),
    (("champions league",), "Champions League final 2026 report — UEFA", "https://www.uefa.com/final",
     "Real Madrid won the 2026 Champions League final, beating Arsenal 2-1 in Budapest."),
    (("bitcoin", "btc"), "Bitcoin price today — CoinDesk", "https://www.coindesk.com/price/bitcoin",
     "Bitcoin was trading at about $98,000 on 11 October 2026, up 2% on the day."),
    (("ai news", "latest ai", "artificial intelligence"), "AI news this week — The Verge",
     "https://www.theverge.com/ai", "This week in AI: new open-weight models were released and "
     "regulators in the EU published guidance on AI transparency."),
    (("rest api", "rest"), "What is a REST API? — IBM", "https://www.ibm.com/topics/rest-apis",
     "A REST API is an interface that uses HTTP requests to read and change resources, "
     "identified by URLs, and is stateless: each request carries everything needed."),
]


def fake_research(topic: str) -> str:
    low = topic.lower()
    hits = [f for f in FACTS if any(w in low for w in f[0])] or [
        ((), f"{topic} — Wikipedia", "https://en.wikipedia.org/wiki/Topic",
         f"An overview of {topic}: what it is, how it works and recent developments.")]
    lines = [f"Web research for: {topic} (searched 11 October 2026)"]
    for n, (_, title, url, text) in enumerate(hits, 1):
        lines += [f"\n[{n}] {title} — {url.split('/')[2]}", url, f"> {text}"]
    lines.append("\nAnswer from the sources above ONLY. Put the source number right after each "
                 "fact it supports, like [1]. Finish with a 'Sources:' list (title — URL).")
    return "\n".join(lines)


def fake_output(name: str, args: dict) -> str:
    """What each tool would plausibly return."""
    q = json.dumps(args).lower()
    if name == "list_directory":
        return DESKTOP_RECENT if args.get("sort") == "recent" else DESKTOP
    if name == "search_files":
        if "cv" in q or "resume" in q:
            return f"2026-10-09 10:00  {FAKE_HOME}/Desktop/CV_Salah_Asfan.pdf"
        if "screenshot" in q:
            return f"2026-10-11 00:12  {FAKE_HOME}/Desktop/Screenshot 2026-10-11 at 00.12.04.png"
        if "tax" in q:
            return f"2026-04-02 09:00  {FAKE_HOME}/Documents/Tax_Return_2025.pdf"
        for f in ("lease.pdf", "notes.txt"):
            if f.split(".")[0] in q:
                return f"2026-10-01 09:00  {FAKE_HOME}/Desktop/{f}"
        return "No files found."
    if name == "ui_elements":
        return ("Google Chrome — 6 controls:\n1. button 'Back'\n2. text field 'Search'\n"
                "3. link 'Sign in'\n4. button 'Subscribe'\n5. link 'Home'\n6. button 'Menu'")
    if name in ("create_routine", "list_routines"):   # throwaway data: run for real
        from app.tools.builtin import routine_tools
        try:
            return getattr(routine_tools, name)(**args)
        except TypeError as e:
            return f"Error: {e}"
    if name in ("find_person", "remember_person"):   # harmless: Jarvis's own (throwaway) data
        from app.memory import people
        if name == "remember_person":
            return "Saved: " + people.describe(people.remember(**{k: v for k, v in args.items()
                                                                  if k in ("name", "relation", "email", "phone", "notes")}))
        found = people.known(args.get("query", ""))
        return ("\n".join(people.describe(x) for x in found) if found else
                f"I don't know anyone called '{args.get('query')}'. Ask the user for their details.")
    if name in ("open_file", "read_document"):
        return f"Opened {args.get('path')}" if name == "open_file" else "Lease: rent £1,200/month, 12 months."
    if name == "create_word_document":
        slug = re.sub(r"[^a-z0-9]+", "-", (args.get("title") or "document").lower()).strip("-")
        return (f"Created Word document '{args.get('title')}' at "
                f"{FAKE_HOME}/Documents/Jarvis/{slug}.docx. If the user wants it on their "
                "phone, call send_file with this path.")
    if name in ("send_reply", "draft_reply", "read_email"):
        if str(args.get("id")) not in ("101", "102", "103"):
            return f"Couldn't find an email with id {args.get('id')}."
        return "Reply sent." if name == "send_reply" else (
            "Reply draft opened in Mail." if name == "draft_reply" else "From: Sam Lee\nMeeting moved.")
    if name == "send_email":
        return f"Email sent to {args.get('to')}."
    if name == "draft_email":
        return "Draft saved in Mail and opened for review."
    if name == "browser_read_page":
        return "Electric cars use batteries and motors; they are cheaper to run but cost more upfront."
    if name == "browser_tabs":
        return "Google Chrome front window tabs:\n" + "\n".join(
            f"{t['index']}. {t['title']} — {t['url']}" for t in TABS)
    if name in ("read_emails", "search_emails"):
        return ("1. [id 101] From: Amazon <ship@amazon.co.uk> — Your order has shipped (today)\n"
                "2. [id 102] From: Sam Lee — Project meeting moved to Friday (today)\n"
                "3. [id 103] From: Landlord — Rent reminder (yesterday)")
    if name in ("calendar_today", "calendar_events"):
        return "Today 10:00–11:00 Standup\nToday 15:00–16:00 Dentist\nTomorrow 09:00 Gym"
    if name == "research":
        topic = args.get("question", "")
        return fake_research(topic)
    if name == "research_report":
        slug = re.sub(r"[^a-z0-9]+", "-", (args.get("topic") or "report").lower()).strip("-")
        return (f"Created Word document '{args.get('topic')}' (870 words) at "
                f"{FAKE_HOME}/Documents/Jarvis/{slug}.docx. If the user wants it on their "
                "phone, call send_file with this path. Written from 5 web sources.")
    if name == "weather":
        return ("Weather for London, England (local time 15:15):\nNow: 16°C, feels like 13°C, "
                "overcast, wind 5 mph, humidity 47%.\nRain likely from about 18:00 (70% chance)."
                "\nToday (Sun 11 Oct): 9–16°C, light rain, 70% chance of rain.\nTomorrow (Mon 12 "
                "Oct): 14–17°C, light drizzle, 45% chance of rain.\nSource: Open-Meteo — "
                "https://open-meteo.com")
    if name == "web_search":
        return ("1. Example result — https://example.com/a — relevant snippet about "
                + (args.get("query") or "") + "\n2. Another — https://example.com/b — more")
    if name == "web_fetch":
        return "Page text: relevant information for the question."
    if name in ("screen_read",):
        return "Visual Studio Code — main.py — def hello(): print('hi')"
    if name in ("screen_look", "camera_look"):
        return "A desk with a laptop, a coffee mug and a plant."
    if name == "calculator":
        try:
            from app.tools.builtin.system import _safe_eval  # type: ignore
            return str(_safe_eval(args.get("expression", "")))
        except Exception:
            expr = args.get("expression", "")
            try:
                return str(eval(expr, {"__builtins__": {}}, {}))
            except Exception:
                return "Error"
    if name == "current_datetime":
        return time.strftime("%A %d %B %Y, %H:%M")
    if name == "search_documents":    # the real tool also lists files whose NAMES match
        if "tax" in q:
            return ("No matching passages in the indexed documents.\n\nFiles whose names "
                    f"match:\n{FAKE_HOME}/Documents/Tax_Return_2025.pdf")
        return "No matching passages, and no files with that name."
    if name == "search_notes":
        return "No matching notes."
    if name == "send_file":
        return f"Sent {args.get('path')} to the user's phone."
    if name == "daily_briefing":
        return "Briefing: 2 meetings today, 3 unread emails, sunny 18°C."
    return "Done."


def matches(value, pattern: str) -> bool:
    text = value if isinstance(value, str) else json.dumps(value)
    return re.search(pattern, text, re.I) is not None


def score(case: dict, calls: list[tuple[str, dict]], reply: str) -> list[str]:
    """Problems with this run ([] = pass)."""
    if reply.startswith("ERROR:"):
        return [reply[:160]]
    problems: list[str] = []
    names = [n for n, _ in calls]
    if case.get("no_tools") and calls:
        problems.append(f"called tools in a chat-only turn: {names}")
    pos = 0
    for want in case.get("tools", []):
        options = want if isinstance(want, list) else [want]
        hit = next((i for i in range(pos, len(names)) if names[i] in options), None)
        if hit is None:
            problems.append(f"missing {'/'.join(options)} (called {names or 'nothing'})")
            break
        pos = hit + 1
    for tool, arg_rules in case.get("args", {}).items():
        first = next((a for n, a in calls if n == tool), None)
        if first is None:
            continue
        for arg, pattern in arg_rules.items():
            if not matches(first.get(arg, ""), pattern):
                problems.append(f"{tool}.{arg}={first.get(arg)!r} !~ /{pattern}/")
    for tool in case.get("forbid", []):
        if tool in names:
            problems.append(f"called forbidden {tool}")
    if case.get("reply") and not re.search(case["reply"], reply, re.I):
        problems.append(f"reply !~ /{case['reply']}/: {reply[:120]!r}")
    if case.get("reply_not") and re.search(case["reply_not"], reply):
        problems.append(f"reply claims success: {reply[:120]!r}")
    said = re.split(r"\n\s*(?:\*\*|#+\s*)?(?:Sources|References)\b", reply)[0]   # shown, not spoken
    if case.get("max_chars") and len(said) > case["max_chars"]:
        problems.append(f"spoken reply too long: {len(said)} chars > {case['max_chars']}")
    if re.search(r'\{\s*"(name|function)"\s*:', reply):
        problems.append("tool call leaked into the reply as text")
    return problems


async def run_case(case: dict, verbose: bool) -> dict:
    from app import channels, db
    from app.chat import service
    from app.tools import base as tools

    calls: list[tuple[str, dict]] = []

    async def fake_execute(name, arguments):
        calls.append((name, dict(arguments)))
        if name in case.get("fail", {}):
            return case["fail"][name]
        return fake_output(name, arguments)

    tools.execute = fake_execute
    from app.automation import selection
    selection.describe = lambda: case.get("this", "")   # what's on screen for this case
    from app.memory import people
    for p in people.all_people():          # each case starts with only its own people
        people.forget(p["name"])
    for person in case.get("people", []):
        people.remember(**person)
    conv = db.create_conversation()["id"]
    for m in case.get("history", []):     # earlier turns of the conversation
        db.add_message(conv, m["role"], m["content"], meta=m.get("meta", {}))
    token = None
    if case.get("phone"):
        class Phone:
            name, allow_dangerous = "Telegram", False
        token = channels.current.set(Phone())
    started = time.perf_counter()
    first_token = None
    reply, agent, timing = "", "?", {}
    try:
        async for ev in service.run_chat(conv, case["say"], spoken=bool(case.get("spoken"))):
            if ev["type"] == "token" and first_token is None:
                first_token = time.perf_counter() - started
            elif ev["type"] == "agent":
                agent = ev["agent"]["id"]
            elif ev["type"] == "done":
                reply, timing = ev["content"], ev.get("timing") or {}
                break
            elif ev["type"] == "error":
                reply = "ERROR: " + ev["message"]
                break
    finally:
        if token is not None:
            channels.current.reset(token)
    total = time.perf_counter() - started
    problems = score(case, calls, reply)
    prompt_tokens = sum(r.get("prompt_tokens", 0) for r in timing.get("rounds", []))
    result = {"say": case["say"], "ok": not problems, "problems": problems, "agent": agent,
              "calls": calls, "reply": reply, "seconds": round(total, 1),
              "first_token": round(first_token, 1) if first_token else None,
              "prompt_tokens": prompt_tokens}
    mark = "PASS" if result["ok"] else "FAIL"
    print(f"{mark} {total:5.1f}s {prompt_tokens:5d}tok [{agent:10s}] {case['say'][:58]}")
    if problems or verbose:
        for p in problems:
            print(f"       ✗ {p}")
        if verbose:
            print(f"       calls: {[(n, a) for n, a in calls]}")
            print(f"       reply: {reply[:200]!r}")
    return result


def setup(model: str | None, utility: str | None) -> None:
    jarvis = Path(_home) / ".jarvis"
    jarvis.mkdir(parents=True, exist_ok=True)
    if REAL_SETTINGS.exists():   # the user's models and names, nothing else
        real = json.loads(REAL_SETTINGS.read_text())
        keep = {k: real[k] for k in ("ollama", "assistant") if k in real}
        (jarvis / "settings.json").write_text(json.dumps(keep))

    import app.main  # noqa: F401  (registers the tools)
    from app import db
    from app.automation import context
    from app.chat import quick
    from app.config import settings
    from app.security.permissions import confirmations

    db.init_db()
    patch = {"context": {"enabled": False}, "memory": {"auto_capture": False},
             "gaps": {"enabled": False}}
    if model:
        patch["ollama"] = {"model": model, "task_models": {"coding": model}}
    if utility:
        patch.setdefault("ollama", {}).setdefault("task_models", {})["utility"] = utility
    settings.update(patch)

    async def approve(_id):
        return True
    confirmations.wait = approve                               # say yes to every confirmation
    context.browser_name = lambda: "Google Chrome"
    context.app_running = lambda name: name in ("Google Chrome", "Mail", "Music")
    context.list_tabs = lambda browser=None: TABS
    context.music_state = lambda: {"state": "paused"}
    quick._installed_apps = lambda: {"safari": "Safari", "spotify": "Spotify", "mail": "Mail",
                                      "calendar": "Calendar", "notes": "Notes", "music": "Music"}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="main chat model to test (default: your settings)")
    ap.add_argument("--utility", help="utility model (titles, memory capture)")
    ap.add_argument("--only", help="run cases whose text contains this (a|b for several)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", help="write JSON results here")
    a = ap.parse_args()

    setup(a.model, a.utility)
    from app.config import settings
    from evals.cases import CASES
    if LEARNED.exists():
        try:
            CASES = CASES + json.loads(LEARNED.read_text())
        except ValueError:
            pass

    picks = [s.strip().lower() for s in (a.only or "").split("|") if s.strip()]
    cases = [c for c in CASES if not picks or any(s in c["say"].lower() for s in picks)]
    print(f"model {settings.get('ollama.model')} · {len(cases)} cases\n")
    results = []
    for case in cases:
        results.append(await run_case(case, a.verbose))

    passed = sum(r["ok"] for r in results)
    secs = sorted(r["seconds"] for r in results)
    print(f"\n{passed}/{len(results)} passed · median {secs[len(secs)//2]}s · "
          f"total {sum(secs):.0f}s · model {settings.get('ollama.model')}")
    if a.out:
        Path(a.out).write_text(json.dumps({"model": settings.get("ollama.model"),
                                           "results": results}, indent=1))
    shutil.rmtree(_home, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())

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
        return "No files found."
    if name == "create_word_document":
        slug = re.sub(r"[^a-z0-9]+", "-", (args.get("title") or "document").lower()).strip("-")
        return (f"Created Word document '{args.get('title')}' at "
                f"{FAKE_HOME}/Documents/Jarvis/{slug}.docx. If the user wants it on their "
                "phone, call send_file with this path.")
    if name == "send_email":
        return f"Email sent to {args.get('to')}."
    if name == "draft_email":
        return "Draft saved in Mail and opened for review."
    if name == "browser_tabs":
        return "Google Chrome front window tabs:\n" + "\n".join(
            f"{t['index']}. {t['title']} — {t['url']}" for t in TABS)
    if name in ("read_emails", "search_emails"):
        return ("1. [id 101] From: Amazon <ship@amazon.co.uk> — Your order has shipped (today)\n"
                "2. [id 102] From: Sam Lee — Project meeting moved to Friday (today)\n"
                "3. [id 103] From: Landlord — Rent reminder (yesterday)")
    if name in ("calendar_today", "calendar_events"):
        return "Today 10:00–11:00 Standup\nToday 15:00–16:00 Dentist\nTomorrow 09:00 Gym"
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
    from app.memory import people
    for person in case.get("people", []):
        people.remember(**person)
    conv = db.create_conversation()["id"]
    token = None
    if case.get("phone"):
        class Phone:
            name, allow_dangerous = "Telegram", False
        token = channels.current.set(Phone())
    started = time.perf_counter()
    first_token = None
    reply, agent, timing = "", "?", {}
    try:
        async for ev in service.run_chat(conv, case["say"]):
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
    ap.add_argument("--only", help="run cases whose text contains this")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", help="write JSON results here")
    a = ap.parse_args()

    setup(a.model, a.utility)
    from app.config import settings
    from evals.cases import CASES

    cases = [c for c in CASES if not a.only or a.only.lower() in c["say"].lower()]
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

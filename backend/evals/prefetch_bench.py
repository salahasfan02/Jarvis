"""How much does warming up while the user speaks save?

    .venv/bin/python -m evals.prefetch_bench
"""
import asyncio
import time

from evals.run import setup

PAIRS = [  # (first words heard while still speaking, the full request)
    ("remind me to call", "remind me to call mum at 6pm"),
    ("email my CV to", "email my CV to asfansalah46@gmail.com"),
    ("create a note called", "create a note called Ideas with: build a robot arm"),
    ("what's on my", "what's on my screen"),
]
EVICT = "what's the latest AI news"   # a different agent: knocks the cache out
SPEAKING = 2.5                        # seconds between the partial and the final words


async def turn(text: str) -> tuple[float, float, int]:
    from app import db
    from app.chat import service
    conv = db.create_conversation()["id"]
    t0 = time.perf_counter()
    first, read = None, 0
    async for ev in service.run_chat(conv, text):
        if ev["type"] == "token" and first is None:
            first = time.perf_counter() - t0
        if ev["type"] == "done":
            rounds = (ev.get("timing") or {}).get("rounds") or [{}]
            read = rounds[0].get("prompt_tokens", 0)
        if ev["type"] in ("done", "error"):
            break
    return round(first or 0, 1), round(time.perf_counter() - t0, 1), read


async def main() -> None:
    setup(None, None)
    from app.chat import prefetch
    print(f"{'request':40s} {'normal':>22s} {'warmed':>22s}   (first word / done s, tokens read)")
    for partial, full in PAIRS:
        await turn(EVICT)
        cold = await turn(full)
        await turn(EVICT)
        await prefetch.warm(None, partial)
        await asyncio.sleep(SPEAKING)
        warm = await turn(full)
        print(f"{full[:40]:40s} {cold[0]:5.1f} / {cold[1]:5.1f} {cold[2]:6d}   "
              f"{warm[0]:5.1f} / {warm[1]:5.1f} {warm[2]:6d}")


asyncio.run(main())

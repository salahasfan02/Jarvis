"""Does tool selection keep the tools each case needs? (embeddings only, fast)

    .venv/bin/python -m evals.recall [--keep 10]
"""
import argparse
import asyncio
import json

from evals.run import setup  # isolated home + fakes


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=10)
    a = ap.parse_args()
    setup(None, None)
    from app.agents import registry as agents
    from app.chat import service, toolpick
    from evals.cases import CASES

    total = missed = 0
    sizes = []
    for case in CASES:
        want = [w if isinstance(w, list) else [w] for w in case.get("tools", [])]
        agent = await agents.route(case["say"])
        offered = service._tools_for(agent)
        if case.get("phone"):
            offered = __import__("app.tools.base", fromlist=["registry"]).registry.for_agent(
                [*agent.tool_tags, "remote"]) if agent.tool_tags else offered
        chosen = await toolpick.select(case["say"], offered, keep=a.keep)
        names = {t.name for t in chosen}
        tokens = round(len(json.dumps([t.to_ollama() for t in chosen])) / 3.7)
        sizes.append(tokens)
        for options in want:
            total += 1
            if not names & set(options):
                missed += 1
                where = "agent lacks it" if not {t.name for t in offered} & set(options) else "dropped"
                print(f"MISS [{agent.id:10s}] {case['say'][:55]:55s} needs {'/'.join(options)} ({where})")
    print(f"\nkept {total - missed}/{total} needed tools · keep={a.keep} · "
          f"median tool tokens {sorted(sizes)[len(sizes) // 2]} (max {max(sizes)})")


asyncio.run(main())

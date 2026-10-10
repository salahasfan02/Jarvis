import asyncio
import time

from app.tools import base


def test_sync_tools_run_off_the_event_loop():
    """A slow sync tool (AppleScript, shell) must not freeze the server."""
    def slow() -> str:
        time.sleep(0.5)
        return "done"

    tool = base.Tool(name="slow_test", description="", parameters={}, handler=slow)

    async def main():
        ticks = []

        async def heartbeat():
            start = time.monotonic()
            while time.monotonic() - start < 0.45:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)

        result, _ = await asyncio.gather(tool.run(), heartbeat())
        return result, ticks

    result, ticks = asyncio.run(main())
    assert result == "done"
    assert len(ticks) >= 5  # the loop kept ticking while the tool slept

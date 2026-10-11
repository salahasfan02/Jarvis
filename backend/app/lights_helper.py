"""Talks to the lights from a helper process macOS sees as Python, not Jarvis.

macOS's Local Network privacy keeps an app off the Wi-Fi until the user
allows it — and on recent macOS it can block Jarvis without ever asking or
listing it in System Settings (Apple's known bug; there's no supported reset).
Python itself (signed by the Python Software Foundation) is a separate entry
there, which the user can allow. So the lights' network traffic runs in a
small helper started as its own "responsible" process — the way Terminal
starts shells — and everything else (Calendar, Accessibility, …) stays
Jarvis's.

The helper reads one JSON request per line on stdin and answers on stdout;
it exits when Jarvis does (stdin closes). The Tapo password for a connect
passes through the pipe and is never written anywhere.

    python -m app.lights_helper
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import ctypes
import ctypes.util
import json
import os
import sys
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DIRECT = "JARVIS_LIGHTS_DIRECT"          # set: talk to the lights in this process
CALLS = ("connect_account", "control", "status")


def wanted() -> bool:
    return sys.platform == "darwin" and os.environ.get(DIRECT) != "1"


# --- starting it -------------------------------------------------------------------------

def _spawn_disclaimed(argv: list[str], env: dict[str, str]) -> tuple[int, int, int]:
    """posix_spawn argv as its own responsible process (macOS attributes its
    privacy checks to it, not to us). Returns (pid, its stdin, its stdout)."""
    libc = ctypes.CDLL(ctypes.util.find_library("System"), use_errno=True)
    to_child_r, to_child_w = os.pipe()
    from_child_r, from_child_w = os.pipe()
    attr, actions = ctypes.c_void_p(), ctypes.c_void_p()   # both are pointers on Darwin
    libc.posix_spawnattr_init(ctypes.byref(attr))
    libc.posix_spawn_file_actions_init(ctypes.byref(actions))
    try:
        if libc.responsibility_spawnattrs_setdisclaim(ctypes.byref(attr), 1) != 0:
            raise OSError("couldn't start the lights helper on its own")
        libc.posix_spawn_file_actions_adddup2(ctypes.byref(actions), to_child_r, 0)
        libc.posix_spawn_file_actions_adddup2(ctypes.byref(actions), from_child_w, 1)
        for fd in (to_child_r, to_child_w, from_child_r, from_child_w):
            libc.posix_spawn_file_actions_addclose(ctypes.byref(actions), fd)

        def strings(items):
            return (ctypes.c_char_p * (len(items) + 1))(*[s.encode() for s in items], None)

        pid = ctypes.c_int()
        rc = libc.posix_spawn(ctypes.byref(pid), argv[0].encode(), ctypes.byref(actions),
                              ctypes.byref(attr), strings(argv),
                              strings([f"{k}={v}" for k, v in env.items()]))
        if rc != 0:
            raise OSError(rc, os.strerror(rc))
    except BaseException:
        os.close(to_child_w)
        os.close(from_child_r)
        raise
    finally:
        libc.posix_spawn_file_actions_destroy(ctypes.byref(actions))
        libc.posix_spawnattr_destroy(ctypes.byref(attr))
        os.close(to_child_r)
        os.close(from_child_w)
    return pid.value, to_child_w, from_child_r


class _Helper:
    """One helper process, started when first needed and again if it stops."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pipe = None
        self.pending: dict[int, concurrent.futures.Future] = {}
        self.next_id = 0

    def _start(self) -> None:
        env = {**os.environ, DIRECT: "1",
               "PYTHONPATH": os.pathsep.join(filter(None, [str(BACKEND), os.environ.get("PYTHONPATH")]))}
        pid, to_helper, from_helper = _spawn_disclaimed(
            [sys.executable, "-m", "app.lights_helper"], env)
        self.pipe = os.fdopen(to_helper, "w", buffering=1)
        self.pending = pending = {}
        threading.Thread(target=self._read, args=(pid, os.fdopen(from_helper), pending),
                         daemon=True, name="lights-helper").start()

    def _read(self, pid: int, replies, pending: dict) -> None:
        for line in replies:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if fut := pending.pop(msg.get("id"), None):
                fut.set_result(msg)
        with self.lock:                                 # it stopped: fail what it had
            if self.pending is pending:
                self.pipe = None
            for fut in pending.values():
                fut.set_result({"error": "The lights helper stopped — try again."})
            pending.clear()
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    async def call(self, fn: str, kwargs: dict, timeout: float = 60):
        from .lights import LightsError
        fut: concurrent.futures.Future = concurrent.futures.Future()
        with self.lock:
            for attempt in (1, 2):
                if self.pipe is None:
                    self._start()
                self.next_id += 1
                rid = self.next_id
                self.pending[rid] = fut
                try:
                    self.pipe.write(json.dumps({"id": rid, "fn": fn, "kwargs": kwargs}) + "\n")
                    break
                except (BrokenPipeError, OSError):
                    self.pending.pop(rid, None)
                    self.pipe = None
                    if attempt == 2:
                        raise LightsError("Couldn't start the lights helper.")
        try:
            msg = await asyncio.wait_for(asyncio.wrap_future(fut), timeout)
        except asyncio.TimeoutError:
            raise LightsError("The lights took too long to answer.") from None
        if "error" in msg:
            raise LightsError(msg["error"])
        return msg["result"]


_helper = _Helper()


async def call(fn: str, **kwargs):
    return await _helper.call(fn, kwargs)


# --- being it ----------------------------------------------------------------------------

async def _serve() -> None:
    from . import lights
    loop = asyncio.get_running_loop()

    def reply(msg: dict) -> None:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    async def handle(req: dict) -> None:
        try:
            if req.get("fn") not in CALLS:
                raise lights.LightsError(f"Unknown request {req.get('fn')!r}")
            result = await getattr(lights, req["fn"])(**req.get("kwargs", {}))
            reply({"id": req.get("id"), "result": result})
        except lights.LightsError as e:
            reply({"id": req.get("id"), "error": str(e)})
        except Exception as e:
            reply({"id": req.get("id"), "error": f"Lights: {type(e).__name__}: {e}"})

    tasks = set()
    while line := await loop.run_in_executor(None, sys.stdin.readline):
        try:
            req = json.loads(line)
        except ValueError:
            continue
        task = asyncio.create_task(handle(req))
        tasks.add(task)
        task.add_done_callback(tasks.discard)


if __name__ == "__main__":
    os.environ[DIRECT] = "1"
    asyncio.run(_serve())

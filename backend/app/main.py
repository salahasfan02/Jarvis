"""Jarvis backend entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import PlainTextResponse

from . import db
from .api.routes import router
from .plugins import loader as plugin_loader

# Importing the builtin tool modules registers their tools.
from .tools.builtin import (  # noqa: F401
    browser, calendars, control, documents, filesystem, forms, imessage, macos, mail, music,
    office, people, research, routine_tools, screen_click, shortcuts, system, timer_tools,
    weather, web)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    plugin_loader.load_all()
    # resume background screen-memory if the user left it enabled
    from .config import settings
    if settings.get("screen_memory.enabled", False):
        from .vision import journal
        journal.start()
    from .channels import telegram
    await telegram.start()  # no-op unless the phone channel is set up
    from . import routines
    routines.start()   # scheduled routines and triggers
    from . import timers
    timers.restore()   # timers that were running before a restart
    from . import warmup
    warmup.schedule()  # load the chat model, Whisper and Kokoro in the background
    yield
    await telegram.stop()


app = FastAPI(title="Jarvis", version="0.1.0", lifespan=lifespan)

# Jarvis's own pages: the Vite dev server, and the built UI the backend serves
# at /app (the desktop app loads that — never file://, whose "null" origin any
# website can borrow with a sandboxed iframe).
UI_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173",
              "http://localhost:8765", "http://127.0.0.1:8765"}


class OriginGuard:
    """Websites you visit must not be able to drive Jarvis.

    Browsers can't read cross-origin responses (CORS), but they CAN send a
    cross-origin POST, and they apply no CORS at all to WebSockets — so any
    page could open the chat socket, ask for a shell command and approve it
    itself. Browsers always label those requests with an Origin header; only
    Jarvis's own origins may change anything or open a socket. Requests with
    no Origin (curl, scripts, the desktop shell) are local processes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            origin = dict(scope.get("headers") or []).get(b"origin", b"").decode()
            changes = scope["type"] == "websocket" or scope.get("method") not in (
                "GET", "HEAD", "OPTIONS")
            if origin and changes and origin not in UI_ORIGINS:
                from .security import audit
                audit.log("blocked_origin", origin=origin[:200], path=scope.get("path", ""))
                if scope["type"] == "websocket":
                    await receive()  # websocket.connect
                    await send({"type": "websocket.close", "code": 4403})
                else:
                    await PlainTextResponse("Forbidden origin", status_code=403)(
                        scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(OriginGuard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(UI_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# DNS rebinding (evil.com re-pointed at 127.0.0.1) arrives with a foreign Host.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

app.include_router(router)

# Persistent sandbox projects, served for live HTML/web previews.
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .config import JARVIS_HOME  # noqa: E402

_projects = JARVIS_HOME / "projects"
_projects.mkdir(exist_ok=True)
class SandboxedFiles(StaticFiles):
    """Live previews of generated HTML share this server's address, so they'd
    count as Jarvis's own UI. The CSP sandbox gives them an opaque origin
    instead: scripts still run, but can't reach the API."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Content-Security-Policy"] = (
            "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads")
        return response


app.mount("/projects", SandboxedFiles(directory=str(_projects), html=True), name="projects")


# The built UI (npm run build), served same-origin for the desktop app: the copy
# the app ships with, else the repo's build.
_ui = next((d for d in (Path(os.environ.get("JARVIS_UI_DIR") or "/nonexistent"),
                        Path(__file__).resolve().parents[2] / "frontend" / "dist")
            if (d / "index.html").is_file()), None)
if _ui:
    app.mount("/app", StaticFiles(directory=str(_ui), html=True), name="ui")


@app.get("/")
def root():
    return {"name": "Jarvis", "docs": "/docs"}

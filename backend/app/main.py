"""Jarvis backend entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .api.routes import router
from .plugins import loader as plugin_loader

# Importing the builtin tool modules registers their tools.
from .tools.builtin import (  # noqa: F401
    browser, documents, filesystem, imessage, macos, music, system, web)


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
    yield
    await telegram.stop()


app = FastAPI(title="Jarvis", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Local UI origins only (Vite dev server / packaged desktop shell).
    # "null" is what Chromium sends for file:// pages — the packaged app.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "app://jarvis", "tauri://localhost", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Persistent sandbox projects, served for live HTML/web previews.
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .config import JARVIS_HOME  # noqa: E402

_projects = JARVIS_HOME / "projects"
_projects.mkdir(exist_ok=True)
app.mount("/projects", StaticFiles(directory=str(_projects), html=True), name="projects")


@app.get("/")
def root():
    return {"name": "Jarvis", "docs": "/docs"}

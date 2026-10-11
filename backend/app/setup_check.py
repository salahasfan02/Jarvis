"""Setup check: is everything Jarvis needs actually allowed and installed?

macOS permissions fail silently (a missing Accessibility grant just means
clicks do nothing), so this checks each one WITHOUT triggering a prompt, says
in plain words what it's for, and offers a fix: show macOS's own prompt, or
open the exact System Settings pane. Camera and microphone belong to the
Jarvis window and are checked by the page itself.
"""
from __future__ import annotations

import asyncio
import ctypes
import struct
import subprocess
import time
from pathlib import Path

from .config import settings
from .llm import ollama_client

PANES = {
    "accessibility": "Privacy_Accessibility",
    "screen": "Privacy_ScreenCapture",
    "automation": "Privacy_Automation",
    "calendar": "Privacy_Calendars",
    "full_disk": "Privacy_AllFiles",
    "camera": "Privacy_Camera",
    "microphone": "Privacy_Microphone",
}

# Apps Jarvis drives with Apple Events: (bundle id, name, what for)
AUTOMATION = [
    ("com.apple.systemevents", "System Events", "knowing which app you're in, window control"),
    ("com.apple.finder", "Finder", "files you've selected, moving things to the Bin"),
    ("com.apple.mail", "Mail", "reading and sending email"),
    ("com.google.Chrome", "Google Chrome", "browser tabs, reading pages, clicking"),
    ("com.apple.Safari", "Safari", "browser tabs, reading pages, clicking"),
    ("com.apple.Music", "Music", "playing music"),
    ("com.apple.Notes", "Notes", "creating and reading notes"),
    ("com.apple.reminders", "Reminders", "creating reminders"),
    ("com.apple.AddressBook", "Contacts", "finding people's email addresses"),
]

# ---- Apple Events permission, checked without prompting ---------------------------

_CS = None


class _AEDesc(ctypes.Structure):
    _fields_ = [("descriptorType", ctypes.c_uint32), ("dataHandle", ctypes.c_void_p)]


def _fourcc(s: str) -> int:
    return struct.unpack(">I", s.encode())[0]


def _core_services():
    global _CS
    if _CS is None:
        cs = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreServices.framework/CoreServices")
        cs.AECreateDesc.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_long,
                                    ctypes.POINTER(_AEDesc)]
        cs.AEDeterminePermissionToAutomateTarget.argtypes = [
            ctypes.POINTER(_AEDesc), ctypes.c_uint32, ctypes.c_uint32, ctypes.c_bool]
        cs.AEDeterminePermissionToAutomateTarget.restype = ctypes.c_int32
        cs.AEDisposeDesc.argtypes = [ctypes.POINTER(_AEDesc)]
        _CS = cs
    return _CS


def automation_status(bundle: str, ask: bool = False) -> int:
    """0 allowed · -1743 denied · -1744 not asked yet · -600 app not running."""
    cs = _core_services()
    desc, raw = _AEDesc(), bundle.encode()
    cs.AECreateDesc(_fourcc("bund"), raw, len(raw), ctypes.byref(desc))
    try:
        return cs.AEDeterminePermissionToAutomateTarget(
            ctypes.byref(desc), _fourcc("****"), _fourcc("****"), ask)
    finally:
        cs.AEDisposeDesc(ctypes.byref(desc))


def _installed(bundle: str) -> bool:
    r = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{bundle}'"],
                       capture_output=True, text=True, timeout=10)
    return bool(r.stdout.strip())


# ---- individual checks -------------------------------------------------------------

def _item(cid: str, name: str, why: str, status: str, detail: str = "",
          fix: str = "", fix_label: str = "") -> dict:
    return {"id": cid, "name": name, "why": why, "status": status, "detail": detail,
            "fix": fix, "fix_label": fix_label}


def _accessibility() -> dict:
    try:
        import ApplicationServices as AS
        ok = bool(AS.AXIsProcessTrusted())
    except Exception:
        ok = False
    return _item("accessibility", "Accessibility", "pressing buttons, typing, scrolling, "
                 "reading what's selected", "ok" if ok else "missing",
                 "" if ok else "Jarvis can't press, type or click anything yet.",
                 "" if ok else "prompt", "Allow")


def _screen() -> dict:
    try:
        import Quartz
        ok = bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        ok = False
    return _item("screen", "Screen Recording", "reading your screen, finding things to "
                 "click, screen memory", "ok" if ok else "missing",
                 "" if ok else "Jarvis can't see the screen yet.",
                 "" if ok else "prompt", "Allow")


def _calendar() -> dict:
    try:
        import EventKit
        status = EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent)
    except Exception:
        return _item("calendar", "Calendar", "your events, meeting reminders", "unknown",
                     "EventKit unavailable")
    ok = status in (3, 4)          # authorized / full access
    denied = status in (1, 2)      # restricted / denied
    return _item("calendar", "Calendar", "your events, meeting reminders",
                 "ok" if ok else "missing" if denied else "ask",
                 "" if ok else "Turned off in System Settings." if denied
                 else "macOS hasn't asked yet.", "" if ok else "prompt" if not denied
                 else "settings", "Ask now" if not denied else "Open Settings")


def _full_disk() -> dict:
    db = Path.home() / "Library" / "Messages" / "chat.db"
    try:
        with open(db, "rb") as fh:
            fh.read(16)
        ok = True
    except PermissionError:
        ok = False
    except OSError:
        return _item("full_disk", "Full Disk Access", "reading your iMessages", "unknown",
                     "Messages isn't set up on this Mac.")
    return _item("full_disk", "Full Disk Access", "reading your iMessages",
                 "ok" if ok else "optional", "" if ok else "Only needed to read iMessages.",
                 "" if ok else "settings", "Open Settings")


def _automation() -> list[dict]:
    out = []
    for bundle, name, why in AUTOMATION:
        code = automation_status(bundle)
        if code == -600 and not _installed(bundle):
            continue                     # e.g. no Chrome on this Mac
        cid = f"automation:{bundle}"
        if code == 0:
            out.append(_item(cid, f"Control {name}", why, "ok"))
        elif code == -1743:
            out.append(_item(cid, f"Control {name}", why, "missing",
                             "Turned off in System Settings → Automation.", "settings",
                             "Open Settings"))
        elif code == -1744:
            out.append(_item(cid, f"Control {name}", why, "ask", "macOS hasn't asked yet.",
                             "prompt", "Ask now"))
        else:
            out.append(_item(cid, f"Control {name}", why, "unknown",
                             f"{name} isn't open, so macOS can't say yet.", "prompt",
                             "Check now"))
    return out


async def _models() -> list[dict]:
    out = []
    up = await ollama_client.is_up()
    out.append(_item("ollama", "Ollama (the AI engine)", "every reply", "ok" if up else "missing",
                     "" if up else "Ollama isn't running.", "" if up else "start", "Start Ollama"))
    if not up:
        return out
    try:
        installed = {m.get("name", "") for m in await ollama_client.list_models()}
    except Exception:
        installed = set()

    def have(name: str) -> bool:
        return bool(name) and (name in installed or f"{name}:latest" in installed
                               or any(i.split(":")[0] == name for i in installed))
    for key, label, why in (("ollama.model", "Chat model", "every reply"),
                            ("ollama.embedding_model", "Embedding model",
                             "routing, memory, picking tools"),
                            ("ollama.vision_model", "Vision model", "camera and screen descriptions")):
        name = settings.get(key, "")
        if not name:
            out.append(_item(f"model:{key}", label, why, "optional", "Not set."))
            continue
        ok = have(name)
        out.append(_item(f"model:{key}", f"{label}: {name}", why, "ok" if ok else "missing",
                         "" if ok else "Not downloaded.", "" if ok else "pull", "Download"))
    return out


def _voice() -> list[dict]:
    out = []
    try:
        from .speech import stt
        size = stt.configured_size()
        ok = stt.model_present(size)
        out.append(_item("whisper", f"Speech recognition ({size})", "understanding your voice",
                         "ok" if ok else "missing", "" if ok else "Model not downloaded.",
                         "" if ok else "whisper", "Download"))
    except Exception as e:
        out.append(_item("whisper", "Speech recognition", "understanding your voice", "unknown", str(e)))
    try:
        from .speech import stt as _stt
        if _stt.multilingual_enabled():
            ok = _stt.model_present("small")
            out.append(_item("whisper_multi", "Arabic speech recognition", "commands in Arabic",
                             "ok" if ok else "missing", "" if ok else "Model not downloaded.",
                             "" if ok else "whisper_multi", "Download"))
    except Exception:
        pass
    try:
        from .speech import engines
        k = engines.ENGINES.get("kokoro")
        ok = bool(k and k.available())
        out.append(_item("kokoro", "Natural voice (Kokoro)", "Jarvis speaking",
                         "ok" if ok else "optional", "" if ok else "Using the Mac's built-in voice."))
    except Exception:
        pass
    return out


def _phone() -> dict:
    try:
        from .channels import telegram
        bot = telegram._bot
        users = telegram.allowed_users()
        if bot is not None and bot.running and users:
            return _item("telegram", "Phone (Telegram)", "using Jarvis from your phone, routine "
                         "results", "ok", f"Paired with {len(users)} account(s).")
        why = "using Jarvis from your phone, routine results"
        if users:
            return _item("telegram", "Phone (Telegram)", why, "missing",
                         "Paired, but not connected right now — check the bot token or the "
                         "internet connection.", "settings_page", "Phone settings")
        configured = bool(telegram.read_token())
        return _item("telegram", "Phone (Telegram)", why, "optional",
                     "Set up, but no phone paired yet." if configured else "Not set up.",
                     "settings_page", "Set up")
    except Exception:
        return _item("telegram", "Phone (Telegram)", "using Jarvis from your phone", "optional")


async def run_all() -> dict:
    checks = await _models()
    system = await asyncio.to_thread(lambda: [_accessibility(), _screen(), _calendar(),
                                              _full_disk(), *_automation()])
    checks += system + await asyncio.to_thread(_voice) + [_phone()]
    problems = sum(c["status"] in ("missing", "ask") for c in checks)
    return {"checks": checks, "problems": problems, "checked_at": time.time()}


# ---- fixes ---------------------------------------------------------------------------

def open_pane(kind: str) -> None:
    anchor = PANES.get(kind, "")
    url = "x-apple.systempreferences:com.apple.preference.security" + (f"?{anchor}" if anchor else "")
    subprocess.run(["open", url], timeout=10)


async def fix(cid: str) -> dict:
    if cid == "accessibility":
        import ApplicationServices as AS
        AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True})
        open_pane("accessibility")
        return {"result": "macOS asked — switch Jarvis on in Accessibility, then re-check."}
    if cid == "screen":
        import Quartz
        Quartz.CGRequestScreenCaptureAccess()
        open_pane("screen")
        return {"result": "Switch Jarvis on in Screen Recording. macOS may ask to reopen Jarvis."}
    if cid == "calendar":
        from .tools.builtin import calendars
        import datetime
        try:
            now = datetime.datetime.now()
            await asyncio.to_thread(calendars._eventkit_events, now, now)
            return {"result": "Calendar access granted."}
        except Exception:
            open_pane("calendar")
            return {"result": "Turn Jarvis on under Calendars."}
    if cid == "full_disk":
        open_pane("full_disk")
        return {"result": "Add Jarvis under Full Disk Access (only needed for iMessages)."}
    if cid.startswith("automation:"):
        bundle = cid.split(":", 1)[1]
        code = automation_status(bundle)
        if code == -600:   # not running: open it quietly in the background so macOS can ask
            subprocess.run(["open", "-gj", "-b", bundle], timeout=15)
            for _ in range(20):
                await asyncio.sleep(0.5)
                if (code := automation_status(bundle)) != -600:
                    break
        if code in (-1744, -600):
            code = await asyncio.to_thread(automation_status, bundle, True)   # macOS prompt
        if code == 0:
            return {"result": "Allowed."}
        open_pane("automation")
        return {"result": "Turn it on for Jarvis in System Settings → Automation."}
    if cid == "ollama":
        subprocess.run(["open", "-a", "Ollama"], timeout=15)
        return {"result": "Starting Ollama…"}
    if cid.startswith("model:"):
        name = settings.get(cid.split(":", 1)[1], "")
        asyncio.get_running_loop().create_task(_pull(name))
        return {"result": f"Downloading {name} in the background — re-check in a few minutes."}
    if cid == "whisper_multi":
        from .speech import stt
        if stt.model_present("small"):
            return {"result": "The multilingual speech model is already here."}

        async def download_multi():
            async for _ in stt.download("small"):
                pass
        asyncio.get_running_loop().create_task(download_multi())
        return {"result": "Downloading the multilingual speech model (480 MB) in the background."}
    if cid == "whisper":
        from .speech import stt

        async def download():
            async for _ in stt.download(stt.configured_size()):
                pass
        asyncio.get_running_loop().create_task(download())
        return {"result": "Downloading the speech model in the background."}
    return {"result": "Nothing to do automatically for that one."}


async def _pull(name: str) -> None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{ollama_client._host()}/api/pull",
                                     json={"model": name}) as r:
                async for _ in r.aiter_lines():
                    pass
    except Exception:
        pass

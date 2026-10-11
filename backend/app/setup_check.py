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
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

from .config import settings
from .llm import ollama_client

PANES = {
    "accessibility": "Privacy_Accessibility",
    "screen": "Privacy_ScreenCapture",
    "automation": "Privacy_Automation",
    "calendar": "Privacy_Calendars",
    "reminders": "Privacy_Reminders",
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


# ---- which app the permissions belong to ------------------------------------------

def responsible_app() -> str:
    """The name to look for in System Settings. macOS gives permissions to
    the app that started Jarvis: "Jarvis" for the installed app, "Terminal"
    (or iTerm, VS Code…) when it was started with npm start / start.sh."""
    import os
    pid = os.getpid()
    for _ in range(12):
        try:
            out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except subprocess.TimeoutExpired:
            break
        if not out:
            break
        ppid_s, _, path = out.partition(" ")
        path = path.strip()
        if "Jarvis.app/" in path:
            return "Jarvis"
        if "/disclaimer" in path:          # started on its own behalf (e.g. by a tool)
            return "python3.12"
        if ".app/Contents/MacOS/" in path and "Python.app" not in path \
                and "Electron" not in path:
            return path.split(".app/Contents/MacOS/")[0].rsplit("/", 1)[-1]
        pid = int(ppid_s or 1)
        if pid <= 1:
            break
    return "python3.12"


# ---- individual checks -------------------------------------------------------------

def _item(cid: str, name: str, why: str, status: str, detail: str = "",
          fix: str = "", fix_label: str = "") -> dict:
    return {"id": cid, "name": name, "why": why, "status": status, "detail": detail,
            "fix": fix, "fix_label": fix_label}


_FRESH = ("import json, ApplicationServices as AS, Quartz;"
          "print(json.dumps([bool(AS.AXIsProcessTrusted()),"
          " bool(Quartz.CGPreflightScreenCaptureAccess())]))")


def _fresh_grants() -> tuple[bool, bool] | None:
    """(accessibility, screen) as a brand-new process sees them. Started by the
    backend it counts as the same app to macOS, but has no stale answer: a grant
    often reaches an already-running process only after it restarts."""
    try:
        out = subprocess.run([sys.executable, "-c", _FRESH], capture_output=True,
                             text=True, timeout=20).stdout
        ax, screen = json.loads(out.strip().splitlines()[-1])
        return bool(ax), bool(screen)
    except Exception:
        return None


def _grant(cid: str, name: str, why: str, now: bool, fresh: bool | None, missing: str) -> dict:
    if now:
        return _item(cid, name, why, "ok")
    if fresh:
        return _item(cid, name, why, "restart",
                     "It's switched on — Jarvis starts using it after a restart.",
                     "restart", "Restart Jarvis")
    return _item(cid, name, why, "missing",
                 f"{missing} Already switched on? Select Jarvis in that list, remove it "
                 "with −, then press Allow again.", "prompt", "Allow")


def _accessibility(fresh: bool | None = None) -> dict:
    try:
        import ApplicationServices as AS
        ok = bool(AS.AXIsProcessTrusted())
    except Exception:
        ok = False
    return _grant("accessibility", "Accessibility", "pressing buttons, typing, scrolling, "
                  "reading what's selected", ok, fresh,
                  "Jarvis can't press, type or click anything yet.")


def _screen(fresh: bool | None = None) -> dict:
    try:
        import Quartz
        ok = bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        ok = False
    return _grant("screen", "Screen Recording", "reading your screen, finding things to "
                  "click, screen memory", ok, fresh, "Jarvis can't see the screen yet.")


_EVENTKIT = {  # entity -> the macOS 14+ "full access" request
    "EKEntityTypeEvent": "requestFullAccessToEventsWithCompletion_",
    "EKEntityTypeReminder": "requestFullAccessToRemindersWithCompletion_",
}


def _eventkit_check(cid: str, name: str, why: str, entity: str) -> dict:
    try:
        import EventKit
        status = EventKit.EKEventStore.authorizationStatusForEntityType_(getattr(EventKit, entity))
    except Exception:
        return _item(cid, name, why, "unknown", "EventKit unavailable")
    if status == 3:                # full access (== the older "authorized")
        return _item(cid, name, why, "ok")
    if status == 4:                # write-only: can add, can't read
        return _item(cid, name, why, "missing", "Jarvis can add but not read — choose Full Access.",
                     "settings", "Open Settings")
    if status in (1, 2):           # restricted / denied
        return _item(cid, name, why, "missing", "Turned off in System Settings.",
                     "settings", "Open Settings")
    return _item(cid, name, why, "ask", "macOS hasn't asked yet.", "prompt", "Ask now")


def _calendar() -> dict:
    return _eventkit_check("calendar", "Calendar", "your events, meeting reminders",
                           "EKEntityTypeEvent")


def _reminders() -> dict:
    return _eventkit_check("reminders", "Reminders", "“remind me to…” in the Reminders app",
                           "EKEntityTypeReminder")


def ask_eventkit(entity: str) -> bool:
    """Show macOS's calendar/reminders prompt; True once allowed. macOS only
    shows it (and lists Jarvis) when the app declares why it wants access."""
    import threading
    import EventKit
    store = EventKit.EKEventStore.alloc().init()
    done, granted = threading.Event(), [False]

    def answered(ok, _error):
        granted[0] = bool(ok)
        done.set()

    if hasattr(store, _EVENTKIT[entity]):
        getattr(store, _EVENTKIT[entity])(answered)
    else:
        store.requestAccessToEntityType_completion_(getattr(EventKit, entity), answered)
    done.wait(60)
    return granted[0]


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
    fresh = await asyncio.to_thread(_fresh_grants) or (None, None)
    system = await asyncio.to_thread(lambda: [_accessibility(fresh[0]), _screen(fresh[1]),
                                              _calendar(), _reminders(), _full_disk(),
                                              *_automation()])
    checks += system + await asyncio.to_thread(_voice) + [_phone()]
    problems = sum(c["status"] in ("missing", "ask", "restart") for c in checks)
    owner = await asyncio.to_thread(responsible_app)
    return {"checks": checks, "problems": problems, "checked_at": time.time(), "grant_to": owner}


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
    if cid in ("calendar", "reminders"):
        entity = "EKEntityTypeEvent" if cid == "calendar" else "EKEntityTypeReminder"
        if await asyncio.to_thread(ask_eventkit, entity):
            return {"result": "Allowed."}
        open_pane(cid)
        where = "Calendars" if cid == "calendar" else "Reminders"
        return {"result": f"Switch Jarvis on under {where} (choose Full Access if asked)."}
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
    if cid == "voiceprint_model":
        from .speech import voiceprint

        async def fetch_model():
            import httpx
            voiceprint.MODEL.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                r = await client.get(voiceprint.MODEL_URL)
                if r.status_code == 200:
                    voiceprint.MODEL.write_bytes(r.content)
        asyncio.get_running_loop().create_task(fetch_model())
        return {"result": "Downloading the voice-lock model (28 MB) in the background."}
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

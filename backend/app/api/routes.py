"""REST + WebSocket API consumed by the desktop frontend."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import db, ui_bridge
from ..agents.registry import AGENTS
from ..chat import service as chat_service
from ..config import settings
from ..llm import ollama_client
from ..plugins import loader as plugin_loader
from ..security import audit
from ..security.permissions import confirmations
from ..tools import base as tools

router = APIRouter(prefix="/api")


# --- health / status ---------------------------------------------------------

@router.get("/status")
async def status():
    return {
        "ok": True,
        "ollama_up": await ollama_client.is_up(),
        "model": settings.get("ollama.model"),
        "assistant_name": settings.get("assistant.name"),
    }


# --- settings ----------------------------------------------------------------

class SettingsPatch(BaseModel):
    patch: dict


@router.get("/settings")
def get_settings():
    return settings.all()


@router.put("/settings")
async def put_settings(body: SettingsPatch):
    audit.log("settings_changed", patch=body.patch)
    updated = settings.update(body.patch)
    if (body.patch.get("proactive") or {}).get("enabled"):
        # Proactive help rides on screen memory's captures: make sure it runs.
        from ..vision import journal
        if not journal.status()["running"]:
            journal.start()
            settings.update({"screen_memory": {"enabled": True}})
    if "enabled" in (body.patch.get("telegram") or {}):
        from ..channels import telegram
        await telegram.start()  # starts or stops the bot to match
    from .. import warmup
    if warmup.affected_by(body.patch):
        warmup.schedule()  # e.g. a new model: load it now, not on the next message
    return updated


# --- models ------------------------------------------------------------------

@router.get("/models")
async def models():
    try:
        return {"models": await ollama_client.list_models(),
                "active": settings.get("ollama.model")}
    except Exception as e:
        return {"models": [], "active": settings.get("ollama.model"), "error": str(e)}


@router.delete("/models/{name:path}")
async def remove_model(name: str):
    await ollama_client.delete_model(name)
    audit.log("model_deleted", model=name)
    return {"ok": True}


@router.post("/models/benchmark")
async def benchmark_model(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        return {"error": "no model name"}
    try:
        result = await ollama_client.benchmark(name)
        audit.log("model_benchmark", **result)
        return result
    except Exception as e:
        return {"error": str(e)}


@router.post("/models/pull")
async def pull_model(body: dict):
    name = body.get("name", "").strip()

    async def stream():
        try:
            async for event in ollama_client.pull_model(name):
                yield json.dumps(event) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"
    audit.log("model_pull", model=name)
    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- conversations -----------------------------------------------------------

@router.get("/conversations")
def conversations(q: str = ""):
    return db.search_conversations(q) if q else db.list_conversations()


@router.post("/conversations")
def new_conversation(body: dict | None = None):
    return db.create_conversation(mode=(body or {}).get("mode", "chat"))


@router.get("/conversations/{conv_id}/messages")
def conversation_messages(conv_id: str):
    return db.get_messages(conv_id)


@router.patch("/conversations/{conv_id}")
def patch_conversation(conv_id: str, body: dict):
    db.rename_conversation(conv_id, title=body.get("title"), folder=body.get("folder"))
    if body.get("mode") in ("chat", "code"):
        db.set_conversation_mode(conv_id, body["mode"])
    if "project_id" in body:
        db.set_conversation_project(conv_id, body["project_id"] or None)
    return {"ok": True}


# --- projects --------------------------------------------------------------------

@router.get("/projects")
def projects_list():
    return db.list_projects()


@router.post("/projects")
def projects_create(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        return {"error": "project needs a name"}
    return db.create_project(name, body.get("description", ""))


@router.get("/projects/{proj_id}")
def project_get(proj_id: str):
    project = db.get_project(proj_id)
    if not project:
        return {"error": "not found"}
    project["conversations"] = db.conversations_in_project(proj_id)
    return project


@router.patch("/projects/{proj_id}")
def project_update(proj_id: str, body: dict):
    db.update_project(proj_id, body)
    return {"ok": True}


@router.delete("/projects/{proj_id}")
def project_delete(proj_id: str):
    db.delete_project(proj_id)
    return {"ok": True}


# --- conversation attachments ---------------------------------------------------

@router.get("/conversations/{conv_id}/attachments")
def get_attachments(conv_id: str):
    return db.list_attachments(conv_id)


@router.post("/conversations/{conv_id}/attachments")
async def upload_attachment(conv_id: str, request: Request, name: str = "file.txt"):
    from ..knowledge import attachments as attach
    data = await request.body()
    if not data:
        return {"error": "empty file"}
    if len(data) > 25 * 1024 * 1024:
        return {"error": "file too large (25 MB max)"}
    try:
        att = await attach.ingest(conv_id, name, data)
        audit.log("attachment_added", conversation=conv_id, name=name)
        return att
    except Exception as e:
        return {"error": f"could not read {name}: {e}"}


@router.delete("/attachments/{att_id}")
def remove_attachment(att_id: str):
    db.delete_attachment(att_id)
    return {"ok": True}


@router.delete("/conversations/{conv_id}")
def remove_conversation(conv_id: str):
    db.delete_conversation(conv_id)
    return {"ok": True}


class EditMessage(BaseModel):
    message_id: str


@router.post("/conversations/{conv_id}/truncate")
def truncate(conv_id: str, body: EditMessage):
    """Delete a message and everything after it (edit / regenerate support)."""
    db.delete_messages_after(conv_id, body.message_id)
    return {"ok": True}


# --- memory ------------------------------------------------------------------

@router.get("/memories")
def memories():
    return [{k: v for k, v in m.items() if k != "embedding"}
            for m in db.list_memories()]


@router.post("/memories")
async def create_memory(body: dict):
    from ..memory import store
    return await store.save(body.get("content", ""), body.get("category", "general"))


@router.put("/memories/{mem_id}")
async def edit_memory(mem_id: str, body: dict):
    from ..memory import store
    await store.update(mem_id, body.get("content", ""))
    return {"ok": True}


@router.delete("/memories/{mem_id}")
def remove_memory(mem_id: str):
    db.delete_memory(mem_id)
    return {"ok": True}


# --- tools / agents / plugins / audit (developer surface) ---------------------

@router.get("/tools")
def list_tools():
    return [{"name": t.name, "description": t.description, "risk": t.risk,
             "tags": t.agent_tags, "always_ask": t.always_ask,
             "permission": settings.get(f"permissions.{t.name}", "default")}
            for t in tools.registry.all()]


@router.get("/agents")
def list_agents():
    return [{"id": a.id, "name": a.name, "description": a.description}
            for a in AGENTS.values()]


@router.get("/plugins")
def list_plugins():
    return plugin_loader.loaded


@router.post("/plugins/reload")
def reload_plugins():
    return plugin_loader.load_all()


@router.get("/audit")
def audit_log(limit: int = 200):
    return audit.tail(limit)


# --- capability gaps (self-improvement registry) -------------------------------

@router.get("/gaps")
def get_gaps():
    from ..gaps import registry as gaps
    from .. import db as _db
    return [gaps.with_priority(g) for g in _db.list_gaps()]


@router.post("/gaps")
async def create_gap(body: dict):
    from ..gaps import registry as gaps
    return await gaps.record(body)


@router.patch("/gaps/{gap_id}")
def patch_gap(gap_id: str, body: dict):
    from .. import db as _db
    _db.update_gap(gap_id, body)
    return {"ok": True}


@router.delete("/gaps/{gap_id}")
def remove_gap(gap_id: str):
    from .. import db as _db
    _db.delete_gap(gap_id)
    return {"ok": True}


@router.get("/gaps/reports")
def gap_reports():
    from ..gaps import registry as gaps
    return gaps.list_reports()


@router.get("/gaps/reports/{report_id}")
def gap_report(report_id: str):
    from ..gaps import registry as gaps
    md = gaps.read_report(report_id)
    return {"id": report_id, "markdown": md or ""}


@router.post("/gaps/report")
async def generate_gap_report():
    from ..gaps import registry as gaps
    return await gaps.generate_report()


# --- system stats & context (dashboard) ----------------------------------------

@router.get("/stats")
async def system_stats():
    import psutil
    from ..tools.base import running_now
    vm = psutil.virtual_memory()
    loaded = await ollama_client.loaded_models()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0),
        "memory_percent": vm.percent,
        "memory_used_gb": round(vm.used / 1e9, 1),
        "memory_total_gb": round(vm.total / 1e9, 1),
        "ollama_up": await ollama_client.is_up(),
        "active_model": settings.get("ollama.model"),
        "loaded_models": [
            {"name": m.get("name"), "size_gb": round(m.get("size", 0) / 1e9, 1),
             "gpu_percent": round(100 * m.get("size_vram", 0) / m["size"]) if m.get("size") else 0}
            for m in loaded],
        "running_tools": list(running_now.keys()),
        # The Core's "Tool activity" panel: tool runs and approvals only, not
        # settings changes or warm-ups.
        "recent_activity": [e for e in audit.tail(80)
                            if e.get("event", "").startswith(("tool_", "confirmation_"))][:8],
    }


@router.get("/context")
async def app_context_endpoint():
    from ..automation import context as app_context
    return await app_context.snapshot()


# --- knowledge base (RAG) --------------------------------------------------------

@router.get("/knowledge")
def knowledge_list():
    return db.list_documents()


@router.post("/knowledge/upload")
async def knowledge_upload(request: Request, name: str = "document.txt"):
    from ..knowledge import store as knowledge
    data = await request.body()
    if not data:
        return {"error": "empty file"}
    result = await knowledge.ingest(name, data)
    audit.log("document_ingested", name=name,
              chunks=result.get("chunk_count", 0))
    return result


@router.delete("/knowledge/{doc_id}")
def knowledge_delete(doc_id: str):
    db.delete_document(doc_id)
    return {"ok": True}


@router.post("/knowledge/search")
async def knowledge_search(body: dict):
    from ..knowledge import store as knowledge
    return await knowledge.search(body.get("query", ""),
                                  int(body.get("limit", 5)))


# --- sandboxed code execution -----------------------------------------------------

@router.post("/code/run")
async def code_run(body: dict):
    from ..sandbox import runner
    result = await runner.run(
        code=body.get("code", ""),
        language=body.get("language", "python"),
        timeout=min(int(body.get("timeout", 30)), 120),
        files=body.get("files"),
        packages=body.get("packages"),
        project=body.get("project", ""),
        entry=body.get("entry", ""))
    audit.log("code_run", language=body.get("language"),
              exit_code=result.get("exit_code"), error=result.get("error"))
    return result


@router.get("/code/languages")
def code_languages():
    from ..sandbox import runner
    return runner.available_languages()


# --- skill installation (user-initiated from Code Studio) --------------------------

@router.post("/plugins/install")
def plugin_install(body: dict):
    from ..plugins import loader as plugins
    try:
        result = plugins.install_skill(body.get("name", ""), body.get("code", ""))
        audit.log("skill_installed", **{k: v for k, v in result.items() if k != "path"})
        return result
    except ValueError as e:
        return {"error": str(e)}


# --- custom skills (saved prompt templates) -------------------------------------

@router.get("/skills")
def skills_list():
    return db.list_skills()


@router.post("/skills")
def skills_create(body: dict):
    name = (body.get("name") or "").strip()
    template = (body.get("template") or "").strip()
    if not name or not template:
        return {"error": "a skill needs a name and a template"}
    return db.create_skill(name, template, body.get("description", ""))


@router.patch("/skills/{skill_id}")
def skills_update(skill_id: str, body: dict):
    db.update_skill(skill_id, body)
    return {"ok": True}


@router.delete("/skills/{skill_id}")
def skills_delete(skill_id: str):
    db.delete_skill(skill_id)
    return {"ok": True}


@router.post("/skills/import")
def skills_import(body: dict):
    """Import a skill pack. Accepts {"skills": [...]} or a bare list. Each item
    needs name + template; duplicates (by name) are skipped."""
    import re
    items = body.get("skills") if isinstance(body, dict) else body
    if not isinstance(items, list):
        return {"error": "expected a JSON array of skills or {\"skills\": [...]}"}
    existing = {s["name"] for s in db.list_skills()}
    added, skipped = [], []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        template = str(item.get("template") or "").strip()
        if not name or not template:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if slug in existing:
            skipped.append(slug)
            continue
        db.create_skill(name, template, str(item.get("description") or ""))
        existing.add(slug)
        added.append(slug)
    audit.log("skills_imported", added=len(added), skipped=len(skipped))
    return {"added": added, "skipped": skipped}


# --- background pictures ---------------------------------------------------------

@router.get("/backgrounds")
def backgrounds_list():
    from .. import backgrounds
    return backgrounds.list_all()


@router.post("/backgrounds")
async def backgrounds_upload(request: Request, name: str = "picture.jpg"):
    from .. import backgrounds
    result = backgrounds.save(name, await request.body())
    if "error" not in result:
        audit.log("background_added", name=result["name"])
    return result


@router.get("/backgrounds/file/{name}")
def backgrounds_file(name: str):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from .. import backgrounds
    path = backgrounds.path_for(name)
    if path is None:
        raise HTTPException(status_code=404)
    return FileResponse(path, headers={"Cache-Control": "max-age=31536000, immutable"})


@router.delete("/backgrounds/{name}")
def backgrounds_delete(name: str):
    from .. import backgrounds
    return backgrounds.delete(name)


# --- smart lights -------------------------------------------------------------------------

@router.get("/lights")
async def lights_list():
    from .. import lights
    if not lights.configured():
        return {"configured": False, "lights": []}
    return {"configured": True, "lights": await lights.status()}


@router.post("/lights/connect")
async def lights_connect(body: dict):
    """The Tapo email + password, typed by the user: used to connect, never stored."""
    from .. import lights
    email, password = str(body.get("email", "")).strip(), str(body.get("password", ""))
    if not email or not password:
        return {"error": "Enter the email and password of your Tapo account."}
    try:
        found = await lights.connect_account(email, password)
    except lights.LightsError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Couldn't connect: {e}"}
    audit.log("lights_connected", count=len(found))
    return {"ok": True, "lights": found}


@router.post("/lights/control")
async def lights_control(body: dict):
    from .. import lights
    try:
        text = await lights.control(str(body.get("light", "")), power=str(body.get("power", "")),
                                    brightness=body.get("brightness") or None,
                                    change=body.get("change") or None,
                                    color=str(body.get("color", "")))
    except lights.LightsError as e:
        return {"error": str(e)}
    return {"result": text}


@router.delete("/lights")
async def lights_forget():
    from .. import lights
    lights.forget()
    audit.log("lights_forgotten")
    return {"ok": True}


# --- phone channel (Telegram) ---------------------------------------------------

@router.get("/telegram/status")
def telegram_status():
    from ..channels import telegram
    return telegram.status()


@router.post("/telegram/token")
async def telegram_set_token(body: dict):
    from ..channels import telegram
    return await telegram.set_token(str(body.get("token") or ""))


@router.delete("/telegram/token")
async def telegram_forget_token():
    from ..channels import telegram
    return await telegram.forget_token()


@router.post("/telegram/pairing")
def telegram_pairing():
    from ..channels import telegram
    return telegram.new_pairing_code()


@router.delete("/telegram/users/{user_id}")
def telegram_unpair(user_id: int):
    from ..channels import telegram
    return telegram.unpair(user_id)


# --- screen activity frame -------------------------------------------------------

@router.post("/proactive/preview")
async def proactive_preview():
    """Show what an offer of help looks like (Settings → Offer help when I'm stuck)."""
    from .. import ui_bridge
    sent = await ui_bridge.announce(
        "💡 Want a hand?",
        "You've had “ModuleNotFoundError: No module named 'requests'” on screen for about "
        "10 minutes. (This is a preview.)", speak=False,
        action={"label": "Help me", "prompt": "Explain how to fix \"ModuleNotFoundError: No "
                "module named 'requests'\" in a Python project, briefly."})
    return {"shown": sent}


# --- setup check ------------------------------------------------------------------------

@router.get("/setup/check")
async def setup_check_all():
    from .. import setup_check
    return await setup_check.run_all()


@router.post("/setup/fix/{cid:path}")
async def setup_fix(cid: str):
    from .. import setup_check
    try:
        return await setup_check.fix(cid)
    except Exception as e:
        return {"result": f"Couldn't fix that automatically: {e}"}


@router.post("/setup/open/{kind}")
async def setup_open_pane(kind: str):
    """Open a System Settings privacy pane (camera, microphone, …)."""
    from .. import setup_check
    setup_check.open_pane(kind)
    return {"ok": True}


# --- activity log & undo --------------------------------------------------------------

@router.get("/activity")
async def activity_list(limit: int = 150):
    from .. import activity
    return activity.recent(limit)


@router.post("/activity/{aid}/undo")
async def activity_undo(aid: str):
    from .. import activity
    return {"result": activity.undo(aid)}


# --- learned test cases ----------------------------------------------------------------

@router.get("/learned")
async def learned_list():
    from .. import learned
    return {"candidates": learned.candidates(), "saved": len(learned.saved_cases())}


@router.post("/learned/{cid}")
async def learned_resolve(cid: str, body: dict):
    """{"expected": ["tool", ...]} to save as a test ([] = no tools), {"dismiss": true} to drop."""
    from .. import learned
    if body.get("dismiss"):
        return learned.resolve(cid, None)
    expected = [t.strip() for t in body.get("expected", []) if t and t.strip()]
    return learned.resolve(cid, expected)


# --- routines & triggers ------------------------------------------------------------

@router.get("/routines")
async def routines_list():
    from .. import routines
    return [{k: v for k, v in r.items() if k != "state"} for r in routines.all_routines()]


_TRIGGER_FIELDS = ("trigger", "at", "days", "every_minutes", "email_from", "email_subject",
                   "minutes_before")


def _trigger_from(body: dict):
    from ..tools.builtin.routine_tools import build_trigger
    args = {k: body[k] for k in _TRIGGER_FIELDS if body.get(k) not in (None, "")}
    for k in ("every_minutes", "minutes_before"):
        if k in args:
            args[k] = int(args[k])
    return build_trigger(**args)


@router.post("/routines")
async def routines_create(body: dict):
    from .. import routines
    spec, error = _trigger_from(body)
    if spec is None:
        return {"error": error}
    action = (body.get("action") or "").strip()
    name = (body.get("name") or "").strip() or (action[:40] or "Routine").capitalize()
    return routines.add(name, spec, action, body.get("deliver") or "auto")


@router.put("/routines/{rid}")
async def routines_update(rid: str, body: dict):
    """Pause/resume ({enabled}) or edit (name, action, deliver, trigger fields)."""
    from .. import routines
    fields: dict = {}
    if "enabled" in body:
        fields["enabled"] = bool(body["enabled"])
    for k in ("name", "action", "deliver"):
        if k in body:
            fields[k] = (body[k] or "").strip() or ("auto" if k == "deliver" else "")
    if any(k in body for k in _TRIGGER_FIELDS):
        spec, error = _trigger_from(body)
        if spec is None:
            return {"error": error}
        fields["trigger"] = spec
        fields["state"] = {}          # a new trigger starts fresh
    if fields:
        routines.update(rid, **fields)
    return routines.get(rid) or {"error": "no such routine"}


@router.delete("/routines/{rid}")
async def routines_delete(rid: str):
    from .. import routines
    routines.remove(rid)
    return {"ok": True}


@router.post("/routines/{rid}/run")
async def routines_run(rid: str):
    from .. import routines
    r = routines.get(rid)
    if r is None:
        return {"error": "no such routine"}
    return {"result": await routines.fire(r)}


@router.post("/chat/prefetch")
async def chat_prefetch(body: dict):
    """Voice: the first words of a request while the user is still speaking —
    warm the model up for the reply (see chat/prefetch.py)."""
    from ..chat import prefetch
    try:
        return await prefetch.warm(body.get("conversation_id"), body.get("text", ""))
    except Exception as e:
        return {"skipped": f"error: {e}"}


@router.post("/screen/stop")
async def screen_stop(body: dict | None = None):
    """Emergency stop: Esc while the frame is up, or "Jarvis stop"."""
    return {"cancelled": ui_bridge.stop_control((body or {}).get("reason", "Esc"))}


@router.get("/screen/activity")
async def screen_activity():
    """Polled by the desktop app to draw a frame while Jarvis reads/controls the screen."""
    return ui_bridge.current()


# --- live camera vision ----------------------------------------------------------

@router.post("/vision/ask")
async def vision_ask(body: dict):
    """Answer a question about a camera/image frame (base64). Streams the reply."""
    image_b64 = (body.get("image") or "").split(",")[-1]  # strip data: prefix
    question = (body.get("question") or "What do you see?").strip()
    if image_b64:   # smaller image, same answer, much faster
        import base64 as _b64
        from ..vision import ocr
        try:
            image_b64 = _b64.b64encode(await asyncio.to_thread(
                ocr.shrink_for_vision, _b64.b64decode(image_b64))).decode()
        except Exception:
            pass
    vision_model = settings.get("ollama.vision_model", "")
    if not vision_model:
        async def no_model():
            yield json.dumps({"error": "No vision model set. In Settings > AI model, "
                              "set a multimodal model like llava (pull it first)."}) + "\n"
        return StreamingResponse(no_model(), media_type="application/x-ndjson")

    messages = [{"role": "user", "content": question, "images": [image_b64]}]

    async def stream():
        try:
            async for chunk in ollama_client.chat_stream(messages, model=vision_model):
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield json.dumps({"token": content}) + "\n"
                if chunk.get("done"):
                    break
            yield json.dumps({"done": True}) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"

    audit.log("vision_ask", question=question[:120])
    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- quick command (menu-bar mini window) ---------------------------------------

@router.post("/quick")
async def quick_command(body: dict):
    """One-shot Q&A for the menu-bar bar. Optionally includes screen OCR so the
    user can ask about whatever app is in front. Streams the text answer; does
    not touch conversation history."""
    question = (body.get("question") or "").strip()
    include_screen = bool(body.get("include_screen"))

    # Prefer screen text captured by Electron (which hides the Jarvis panel
    # first); fall back to capturing here if the caller didn't provide it.
    screen_text = (body.get("screen_text") or "").strip()
    if include_screen and not screen_text:
        try:
            from ..vision import watcher
            screen_text = await watcher._capture_text()
        except Exception:
            screen_text = ""

    system = (
        "You are Jarvis, answering a quick question from a floating command bar. "
        "Be brief and direct — one or two sentences unless more is clearly needed. "
        "No greetings or sign-offs.")
    messages = [{"role": "system", "content": system}]
    if screen_text.strip():
        messages.append({"role": "system", "content":
            "The user is looking at this on their screen right now:\n"
            + screen_text[:4000]})
    messages.append({"role": "user", "content": question})

    async def stream():
        try:
            async for chunk in ollama_client.chat_stream(messages):
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield json.dumps({"token": content}) + "\n"
                if chunk.get("done"):
                    break
            yield json.dumps({"done": True}) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"

    audit.log("quick_command", question=question[:120], screen=include_screen)
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/screen-ocr")
async def screen_ocr():
    """Capture the screen and return its OCR text (used by the quick window,
    which hides its own panel first for a clean shot)."""
    from ..vision import watcher
    try:
        return {"text": await watcher._capture_text()}
    except Exception as e:
        return {"text": "", "error": str(e)}


@router.get("/watches")
def list_watches():
    from ..vision import watcher
    return watcher.active()


@router.get("/screen-memory")
def screen_memory_status():
    from ..vision import journal
    return journal.status()


@router.post("/screen-memory")
async def screen_memory_control(body: dict):
    from ..vision import journal
    if body.get("enabled"):
        interval = int(body.get("interval_seconds") or
                       settings.get("screen_memory.interval_seconds", 300))
        settings.update({"screen_memory": {"enabled": True, "interval_seconds": interval}})
        return journal.start(interval)
    settings.update({"screen_memory": {"enabled": False}})
    return journal.stop()


# --- offline speech recognition (whisper) ---------------------------------------

@router.get("/stt/status")
def stt_status():
    from ..speech import stt
    return stt.status()


@router.post("/stt/download")
async def stt_download(body: dict | None = None):
    from ..speech import stt

    size = (body or {}).get("model") or stt.configured_size()

    async def stream():
        async for event in stt.download(size):
            yield json.dumps(event) + "\n"

    audit.log("whisper_download_started", model=size)
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/stt/transcribe")
async def stt_transcribe(request: Request, hint: str = "", command: int = 0):
    from ..speech import stt, voiceprint
    audio = await request.body()
    if not audio:
        return {"error": "empty audio"}
    # Voice lock: someone else's voice (TV, visitors) is ignored.
    allowed, match = await asyncio.to_thread(voiceprint.check, audio)
    if not allowed:
        audit.log("voice_rejected", score=round(match or 0, 3))
        return {"text": "", "rejected": "voice", "score": match}
    result = await stt.transcribe(audio, hint=hint[:200], command=bool(command))
    if match is not None:
        result["voice_score"] = round(match, 3)
    return result


# --- voice lock (experimental) -------------------------------------------------------

@router.get("/voice/lock")
async def voice_lock_status():
    from ..speech import voiceprint
    vp = voiceprint.enrolled()
    return {"available": voiceprint.available(), "enrolled": vp is not None,
            "seconds": (vp or {}).get("seconds"), "enabled": voiceprint.locked(),
            "threshold": voiceprint.threshold()}


@router.post("/voice/enroll")
async def voice_enroll(request: Request, step: str = "add"):
    """step=add (body: a WAV phrase) · finish · reset"""
    from ..speech import voiceprint
    if step == "reset":
        voiceprint.enroll_reset()
        return {"ok": True}
    if step == "finish":
        return await asyncio.to_thread(voiceprint.enroll_finish)
    return await asyncio.to_thread(voiceprint.enroll_add, await request.body())


@router.post("/voice/test")
async def voice_test(request: Request):
    """How closely does this recording match the enrolled voice?"""
    from ..speech import voiceprint
    s = await asyncio.to_thread(voiceprint.score, await request.body())
    return {"score": None if s is None else round(s, 3), "threshold": voiceprint.threshold(),
            "would_pass": s is None or s >= voiceprint.threshold()}


# --- code studio ---------------------------------------------------------------

CODE_SYSTEM_PROMPT = (
    "You are Jarvis Code, an expert software engineer. You write complete, "
    "working, production-quality code.\n"
    "Rules:\n"
    "- Respond with exactly ONE fenced code block containing the full code.\n"
    "- Tag the fence with the language (```python, ```typescript, ...).\n"
    "- Include brief comments where they help understanding.\n"
    "- No prose before or after the block; if something must be explained, "
    "put it in code comments.\n"
    "- When asked to modify previous code, return the complete updated file, "
    "not a diff."
)


@router.post("/code/generate")
async def code_generate(body: dict):
    messages = body.get("messages", [])[-20:]
    language = (body.get("language") or "").strip()
    system = CODE_SYSTEM_PROMPT
    if language:
        system += f"\n- Write the code in {language} unless the request demands otherwise."

    async def stream():
        try:
            async for chunk in ollama_client.chat_stream(
                    [{"role": "system", "content": system}, *messages],
                    model=ollama_client.model_for("coding")):
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield json.dumps({"token": content}) + "\n"
                if chunk.get("done"):
                    break
            yield json.dumps({"done": True}) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"

    audit.log("code_generate", prompt=(messages[-1].get("content", "")[:200]
                                       if messages else ""))
    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- text to speech -------------------------------------------------------------

@router.get("/tts/engines")
def tts_engines():
    from ..speech import engines
    return engines.list_engines()


@router.get("/tts/voices")
def tts_voices():
    from ..speech.engines import KOKORO_VOICES
    return KOKORO_VOICES


@router.post("/tts/kokoro/download")
async def kokoro_download():
    from ..speech import engines

    async def stream():
        try:
            engine = engines.ENGINES["kokoro"]
            async for event in engine.download():  # type: ignore[attr-defined]
                yield json.dumps(event) + "\n"
            yield json.dumps({"done": True}) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"

    audit.log("kokoro_download_started")
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/tts/speak")
async def tts_speak(body: dict):
    from fastapi.responses import JSONResponse, Response
    from ..speech import engines
    wav = await engines.synthesize(body.get("text", "")[:3000])
    if wav is None:
        return JSONResponse({"engine": "browser"})
    return Response(content=wav, media_type="audio/wav")


# --- chat websocket ----------------------------------------------------------

@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    current_task: asyncio.Task | None = None

    async def run(conv_id: str, content: str, spoken: bool = False):
        try:
            async for event in chat_service.run_chat(conv_id, content, spoken=spoken):
                await ws.send_json(event)
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            try:
                await ws.send_json({"type": "stopped"})
            except Exception:
                pass
            raise

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "chat":
                if current_task and not current_task.done():
                    current_task.cancel()
                conv_id = (msg.get("conversation_id")
                           or db.create_conversation(
                               mode=msg.get("mode", "chat"))["id"])
                await ws.send_json({"type": "conversation", "conversation_id": conv_id})
                current_task = asyncio.create_task(
                    run(conv_id, msg.get("content", ""), bool(msg.get("voice"))))
                ui_bridge.track(current_task)

            elif mtype == "confirm":
                confirmations.resolve(msg.get("id", ""), bool(msg.get("approved")))
                if msg.get("remember") and msg.get("approved") and msg.get("tool"):
                    t = tools.registry.get(msg["tool"])
                    if t and t.risk == "confirm" and not t.always_ask:  # never remembered
                        settings.update({"permissions": {msg["tool"]: "always"}})

            elif mtype == "stop":
                if current_task and not current_task.done():
                    current_task.cancel()

            elif mtype == "hello" and msg.get("ui"):
                ui_bridge.register(ws)   # a Jarvis window: it can take camera photos

            elif mtype == "ui_response":
                ui_bridge.resolve(msg.get("id", ""), msg.get("data"))
    except WebSocketDisconnect:
        if current_task and not current_task.done():
            current_task.cancel()
    finally:
        ui_bridge.unregister(ws)

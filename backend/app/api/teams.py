"""Agent teams API: the canvas's teams, and runs — start one, follow it live
(NDJSON: what happened so far, then each event as it happens), stop it."""
from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from ..security import audit
from ..teams import engine, store

router = APIRouter(prefix="/api/teams")
# Routes that stop a run or read a live one are `async`: they must run on the
# event loop with it, never in the thread pool plain routes use.


def _missing(what: str = "team") -> JSONResponse:
    return JSONResponse({"error": f"no such {what}"}, status_code=404)


@router.get("")
def teams_list():
    return store.list_teams()


@router.post("")
def teams_create(body: dict | None = None):
    body = body or {}
    team = store.create(str(body.get("name") or ""), str(body.get("template") or ""))
    audit.log("team_created", team=team.get("name"), template=body.get("template") or "")
    return team


@router.get("/templates")
def teams_templates():
    return store.templates()


@router.get("/runs/active")
async def runs_active():
    run = engine.active()
    return run.detail() if run else {}


@router.get("/runs/{run_id}")
async def run_get(run_id: str):
    return engine.get(run_id) or _missing("run")


@router.get("/runs/{run_id}/stream")
async def run_stream(run_id: str):
    run = engine.RUNS.get(run_id)
    if run is None:
        return _missing("live run")

    async def lines():
        async for event in engine.follow(run):
            yield json.dumps(event) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.post("/runs/{run_id}/stop")
async def run_stop(run_id: str):
    return {"ok": engine.stop(run_id)}


@router.delete("/runs/{run_id}")
async def run_delete(run_id: str):
    live = engine.RUNS.get(run_id)
    if live is not None and live.status == "running":
        return {"ok": False, "error": "It's still running — stop it first."}
    engine.RUNS.pop(run_id, None)
    return {"ok": store.delete_run(run_id)}


@router.get("/{team_id}")
def team_get(team_id: str):
    return store.get(team_id) or _missing()


@router.put("/{team_id}")
def team_save(team_id: str, body: dict):
    return store.save(team_id, body) or _missing()


@router.delete("/{team_id}")
async def team_delete(team_id: str):
    run = engine.active()
    if run is not None and run.team["id"] == team_id:
        engine.stop(run.id)
    audit.log("team_deleted", team=team_id)
    return {"ok": store.delete(team_id)}


@router.get("/{team_id}/runs")
def team_runs(team_id: str, limit: int = 20):
    return store.runs(team_id, min(limit, 100))


@router.post("/{team_id}/runs")
async def team_run(team_id: str, body: dict):
    team = store.get(team_id)
    if team is None:
        return _missing()
    run = engine.start(team, str(body.get("task") or ""))
    if isinstance(run, str):
        return {"error": run}
    return run.detail()

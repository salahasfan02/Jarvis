"""The setup check lists every permission and model with a status."""
import asyncio

from app import setup_check


def test_setup_check_reports_every_area(monkeypatch):
    monkeypatch.setattr(setup_check, "automation_status", lambda b, ask=False: 0)

    async def up():
        return False
    monkeypatch.setattr(setup_check.ollama_client, "is_up", up)
    result = asyncio.run(setup_check.run_all())
    ids = {c["id"] for c in result["checks"]}
    assert {"ollama", "accessibility", "screen", "calendar", "telegram"} <= ids
    assert any(i.startswith("automation:") for i in ids)
    ollama = next(c for c in result["checks"] if c["id"] == "ollama")
    assert ollama["status"] == "missing" and ollama["fix"] == "start"
    for c in result["checks"]:
        assert c["status"] in ("ok", "missing", "ask", "unknown", "optional")
        assert c["why"]

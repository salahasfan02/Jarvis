"""The fixes from the first review: calculator escape, websites driving the
local API, web_fetch into the local network, sandbox reach, audit growth."""
import json

import pytest
from fastapi.testclient import TestClient

from app import main, warmup
from app.sandbox import runner
from app.security import audit
from app.tools.builtin import system, web

ESCAPE = ("[c for c in ().__class__.__base__.__subclasses__() if c.__name__=='_wrap_close'][0]"
          ".__init__.__globals__['popen']('echo PWNED').read()")


def test_calculator_does_math_but_not_python():
    assert system.calculator("2**10 + 5") == "1029"
    assert system.calculator("round(17.5 * 0.0825, 2)") == "1.44"
    assert system.calculator("sqrt(16) + pi") == str(4 + 3.141592653589793)
    assert system.calculator("max(3, 9, 4) - sum([1, 2])") == "6"
    for attack in (ESCAPE, "__import__('os').system('id')", "open('/etc/passwd').read()",
                   "(1).__class__", "9**9**9", "factorial(10**7)"):
        assert system.calculator(attack).startswith("Could not evaluate"), attack


@pytest.fixture
def client():
    # Not used as a context manager: no lifespan (Telegram, warm-up) in tests.
    return TestClient(main.app, base_url="http://127.0.0.1:8765")


def test_websites_cannot_change_anything(client):
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/memories", json={"content": "x"}, headers=evil).status_code == 403
    assert client.post("/api/plugins/install", json={"name": "x", "code": ""},
                       headers={"Origin": "null"}).status_code == 403  # sandboxed iframe
    ok = client.post("/api/memories", json={"content": "the UI may"},
                     headers={"Origin": "http://localhost:5173"})
    assert ok.status_code == 200
    assert client.post("/api/memories", json={"content": "curl may"}).status_code == 200


def test_websites_cannot_open_the_chat_socket(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/api/ws/chat", headers={
                "Origin": "https://evil.example", "Host": "127.0.0.1:8765"}):
            pass
    # closed before accept: a real server answers the handshake with HTTP 403;
    # the test client reports it as close code 4403
    assert getattr(closed.value, "status_code", None) == 403 or \
        getattr(closed.value, "code", None) == 4403
    with client.websocket_connect("/api/ws/chat", headers={
            "Origin": "http://localhost:5173", "Host": "127.0.0.1:8765"}) as ws:
        ws.send_json({"type": "stop"})  # Jarvis's own UI connects and talks fine


def test_dns_rebinding_host_is_refused():
    rebound = TestClient(main.app, base_url="http://evil.example:8765")
    assert rebound.get("/api/status").status_code == 400


def test_generated_previews_run_sandboxed(client):
    folder = runner.PROJECTS_DIR / "csp-test"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text("<script>fetch('/api/settings')</script>")
    r = client.get("/projects/csp-test/index.html")
    assert r.status_code == 200 and r.headers["content-security-policy"].startswith("sandbox")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.0.0.8", "192.168.1.1",
                                  "169.254.169.254", "100.100.100.100", "::1"])
def test_web_fetch_refuses_local_and_private_addresses(host):
    assert not web._is_public(host)


def test_web_fetch_reports_the_refusal():
    import asyncio
    out = asyncio.run(web.web_fetch("http://127.0.0.1:8765/api/memories"))
    assert out.startswith("Refused:") and "local or private" in out


def test_sandbox_closes_private_folders_and_apple_events():
    profile = runner._profile(runner.PROJECTS_DIR / "demo")
    assert "(deny appleevent-send)" in profile
    assert ".ssh" in profile and "Library/Messages" in profile and ".jarvis" in profile
    # the project folder (inside ~/.jarvis) is re-allowed after the deny
    assert profile.index("(deny file-read*") < profile.index("(allow file-read* file-write*")


def test_audit_reads_only_the_tail_and_rotates(monkeypatch, tmp_path):
    log = tmp_path / "audit.log"
    monkeypatch.setattr(audit, "AUDIT_FILE", log)
    monkeypatch.setattr(audit, "MAX_BYTES", 50_000)
    for i in range(2000):
        audit.log("tick", i=i)
    assert log.with_suffix(".log.1").exists() and log.stat().st_size < 60_000
    newest = audit.tail(5)
    assert [e["i"] for e in newest] == [1999, 1998, 1997, 1996, 1995]
    json.dumps(newest)


def test_a_missing_default_model_is_replaced_by_an_installed_one():
    installed = ["nomic-embed-text:latest", "llava:7b", "qwen2.5:14b"]
    assert warmup.pick_installed("llama3.1", installed) == "qwen2.5:14b"
    assert warmup.pick_installed("qwen2.5:14b", installed) is None
    assert warmup.pick_installed("llama3.1", ["llama3.1:latest"]) is None
    assert warmup.pick_installed("llama3.1", ["nomic-embed-text"]) is None


def test_an_updated_interface_is_never_served_stale(tmp_path):
    """The page is re-checked every load; its hashed scripts can be kept for good."""
    from fastapi import FastAPI
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<script src='assets/main-abc.js'></script>")
    (tmp_path / "assets" / "main-abc.js").write_text("console.log(1)")
    ui = FastAPI()
    ui.mount("/app", main.UIFiles(directory=str(tmp_path), html=True))
    client = TestClient(ui)
    assert client.get("/app/").headers["cache-control"] == "no-cache"
    assert "immutable" in client.get("/app/assets/main-abc.js").headers["cache-control"]

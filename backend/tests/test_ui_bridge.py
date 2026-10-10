"""Screen-activity frame state and camera requests to the Jarvis window."""
import asyncio

from app import ui_bridge


def setup_function():
    ui_bridge._active.update(controlling=0, reading=0)
    ui_bridge._hold_until.update(controlling=0.0, reading=0.0)
    ui_bridge.set_watching(0)
    ui_bridge._sockets.clear()


def test_frame_shows_while_reading_and_lingers_briefly(monkeypatch):
    monkeypatch.setattr(ui_bridge, "SHOW_DELAY", 0)
    assert ui_bridge.current()["mode"] is None

    async def read():
        async with ui_bridge.screen_activity("reading"):
            assert ui_bridge.current()["mode"] == "reading"
    asyncio.run(read())
    assert ui_bridge.current()["mode"] == "reading"        # held so it's noticed
    ui_bridge._hold_until["reading"] = 0
    assert ui_bridge.current()["mode"] is None


def test_controlling_wins_over_reading_and_watching(monkeypatch):
    monkeypatch.setattr(ui_bridge, "SHOW_DELAY", 0)
    ui_bridge.set_watching(1)
    assert ui_bridge.current()["mode"] == "watching"
    with ui_bridge.screen_activity_sync("controlling"):
        ui_bridge._active["reading"] += 1
        assert ui_bridge.current() == {"mode": "controlling",
                                       "label": "Jarvis is controlling your screen"}


def test_overlay_label_is_not_screen_content():
    assert ui_bridge.is_overlay_text("Jarvis is reading your screen")
    assert not ui_bridge.is_overlay_text("Jarvis is reading your screen and more")


def test_camera_request_without_a_window_says_so():
    assert asyncio.run(ui_bridge.request("camera_frame")) == {"error": "no_ui"}


def test_camera_request_gets_the_windows_answer():
    class FakeWindow:
        async def send_json(self, msg):
            assert msg["type"] == "ui_request" and msg["kind"] == "camera_frame"
            asyncio.get_running_loop().call_soon(
                ui_bridge.resolve, msg["id"], {"image": "data:image/jpeg;base64,AAAA"})

    ui_bridge.register(FakeWindow())
    reply = asyncio.run(ui_bridge.request("camera_frame", timeout=2))
    assert reply == {"image": "data:image/jpeg;base64,AAAA"}

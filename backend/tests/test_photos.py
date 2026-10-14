"""Photos: "take a picture" saves one in Pictures/Jarvis; "take a selfie and
send it to me" / "send me that picture" put it on the phone — as a picture
in the chat, not a file."""
import asyncio
import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from app import channels, db, ui_bridge
from app import main as app_main
from app.channels import telegram as tg
from app.chat import quick
from app.chat import service as chat_service
from app.security.permissions import confirmations
from app.tools.builtin import phone
from app.vision import photos
from test_telegram import FakeTelegram

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 64 + b"\xff\xd9"
DATA_URL = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


@pytest.fixture
def camera(monkeypatch, tmp_path):
    """A Jarvis window whose camera hands back JPEG; the requests it got."""
    monkeypatch.setattr(photos, "PHOTOS_DIR", tmp_path / "Pictures" / "Jarvis")
    asked: list[tuple[str, dict]] = []

    async def request(kind, payload=None, timeout=20):
        asked.append((kind, payload or {}))
        return {"image": DATA_URL}
    monkeypatch.setattr(ui_bridge, "request", request)
    return asked


class FakePhone(channels.ChannelSession):
    name = "Telegram"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_photo(self, path, caption=""):
        self.sent.append(("photo", path.name))
        return "Sent the photo to your phone on Telegram."

    async def send_file(self, path, caption=""):
        self.sent.append(("file", path.name))
        return f"Sent {path.name} to the user's phone via Telegram."

    async def send_text(self, text):
        self.sent.append(("text", text))
        return "Sent to your phone on Telegram."


@pytest.fixture
def my_phone(monkeypatch):
    fake = FakePhone()
    monkeypatch.setattr(phone, "_target", lambda: fake)
    return fake


def _turn(conv: str, text: str) -> list[dict]:
    async def main():
        events = []
        async for event in chat_service.run_chat(conv, text):
            events.append(event)
            if event["type"] == "confirm_request":
                confirmations.resolve(event["id"], True)
        return events
    return asyncio.run(main())


def _done(events) -> str:
    return next(e for e in events if e["type"] == "done")["content"]


def test_instant_commands():
    cases = {
        "take a picture": {},
        "Jarvis, take a photo of me please": {},
        "snap a pic": {},
        "take a selfie and send it to me": {"send_to_phone": True},
        "take a picture and then send it to my phone on telegram": {"send_to_phone": True},
    }
    for text, args in cases.items():
        a = quick.match(text)
        assert a and (a.tool, a.arguments) == ("take_photo", args), text
    for text in ("send me that picture", "send the photo to my phone", "send that selfie to me on telegram"):
        a = quick.match(text)
        assert a and (a.tool, a.arguments) == ("send_to_phone", {"what": "photo"}), text
    for text in ("take a picture of my screen", "take a screenshot", "take a picture and email it to Sam"):
        a = quick.match(text)
        assert a is None or a.tool != "take_photo", text


def test_take_a_picture_counts_down_and_saves_it(camera):
    conv = db.create_conversation()["id"]
    events = _turn(conv, "take a picture")
    assert camera == [("camera_photo", {"countdown": 3})]
    shots = photos.recent()
    assert len(shots) == 1 and shots[0].read_bytes() == JPEG
    assert shots[0].name.startswith("photo-") and " " not in shots[0].name
    assert _done(events) == f"Took a photo and saved it at {shots[0]}."
    # "undo that" would move it to the Bin
    from app import activity
    assert activity.recent(1)[0]["undo"] == {"kind": "remove_created", "path": str(shots[0])}


def test_take_a_selfie_and_send_it_to_me(camera, my_phone):
    conv = db.create_conversation()["id"]
    reply = _done(_turn(conv, "take a selfie and send it to me on telegram"))
    shot = photos.recent()[0]
    assert my_phone.sent == [("photo", shot.name)]
    assert reply.endswith("Sent the photo to your phone on Telegram.")


def test_send_me_that_picture_later(camera, my_phone):
    conv = db.create_conversation()["id"]
    _turn(conv, "take a picture")
    _turn(conv, "what's 2 plus 2")          # something else in between
    assert _done(_turn(conv, "send me that picture")) == "Sent the photo to your phone on Telegram."
    assert my_phone.sent == [("photo", photos.recent()[0].name)]


def test_send_it_to_me_right_after_sends_the_photo(camera, my_phone):
    conv = db.create_conversation()["id"]
    _turn(conv, "take a photo")
    _turn(conv, "send it to me")
    assert my_phone.sent == [("photo", photos.recent()[0].name)]


def test_no_photo_yet(camera, my_phone):
    out = asyncio.run(phone.send_to_phone(what="photo"))
    assert "no photo" in out and my_phone.sent == []


def test_without_a_window_or_camera_it_says_how_to_fix_it(monkeypatch, tmp_path):
    from app.tools.builtin import system
    monkeypatch.setattr(photos, "PHOTOS_DIR", tmp_path / "shots")

    async def request(kind, payload=None, timeout=20):
        return {"error": "camera access was refused"}
    monkeypatch.setattr(ui_bridge, "request", request)
    out = asyncio.run(system.take_photo())
    assert out == "Couldn't use the camera: camera access was refused"
    assert photos.recent() == []


# --- Telegram: a picture in the chat --------------------------------------------------------

def _session(fake: FakeTelegram) -> tg.TelegramSession:
    api = tg.TelegramAPI("123:" + "x" * 35, transport=httpx.MockTransport(fake.handler))
    return tg.TelegramSession(tg.TelegramBot("unused", api=api), 42)


def test_camera_photos_go_as_pictures_and_other_files_as_files(camera, tmp_path):
    from app.tools.builtin.documents import send_file
    shot = photos.save(JPEG)
    lease = tmp_path / "lease.pdf"
    lease.write_bytes(b"%PDF-1.7")
    fake = FakeTelegram()
    token = channels.current.set(_session(fake))
    try:
        assert asyncio.run(send_file(str(shot))) == "Sent the photo to your phone on Telegram."
        asyncio.run(send_file(str(lease)))
    finally:
        channels.current.reset(token)
    assert fake.sent("sendPhoto")[0]["_files"]["photo"] == (shot.name, JPEG)
    assert [d["_files"]["document"][0] for d in fake.sent("sendDocument")] == ["lease.pdf"]


def test_a_photo_telegram_refuses_goes_as_a_file(camera):
    shot = photos.save(JPEG)
    fake = FakeTelegram()
    original = fake.handler

    async def handler(request):
        if request.url.path.endswith("/sendPhoto"):
            return httpx.Response(400, json={"ok": False, "description": "PHOTO_INVALID_DIMENSIONS"})
        return await original(request)
    fake.handler = handler
    out = asyncio.run(_session(fake).send_photo(shot))
    assert out.startswith(f"Sent {shot.name}")
    assert fake.sent("sendDocument")[0]["_files"]["document"][0] == shot.name


# --- the Camera page's API -----------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app_main.app, base_url="http://127.0.0.1:8765")


def test_photos_api(camera, client, my_phone):
    saved = client.post("/api/photos", json={"image": DATA_URL}).json()
    assert saved["name"].startswith("photo-") and saved["bytes"] == len(JPEG)
    assert client.post("/api/photos", json={"image": "data:text/plain;base64,aGk="}).json()["error"]
    listed = client.get("/api/photos").json()
    assert [p["name"] for p in listed] == [saved["name"]]
    assert client.get(listed[0]["url"]).content == JPEG
    # nothing outside the folder, however it's asked for
    assert client.get("/api/photos/file/..%2F..%2Fjarvis.db").status_code == 404
    assert client.get("/api/photos/file/.hidden.jpg").status_code == 404
    res = client.post(f"/api/photos/{saved['name']}/send").json()
    assert res == {"ok": True, "result": "Sent the photo to your phone on Telegram."}
    assert my_phone.sent == [("photo", saved["name"])]
    assert client.delete(f"/api/photos/{saved['name']}").json() == {"ok": True}

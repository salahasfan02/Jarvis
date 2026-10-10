"""Background pictures: real images only, safe names, HEIC handled."""
import struct
import zlib

from app import backgrounds
from app.config import settings


def _png() -> bytes:
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30")) + chunk(b"IEND", b""))


def test_pictures_are_saved_listed_and_deleted():
    saved = backgrounds.save("My Wallpaper!.png", _png())
    assert saved["name"].endswith("-my-wallpaper.png")
    assert saved in backgrounds.list_all()
    settings.update({"ui": {"background": f"image:{saved['name']}"}})
    backgrounds.delete(saved["name"])
    assert backgrounds.path_for(saved["name"]) is None
    assert settings.get("ui.background") == ""  # no pointer to a missing file


def test_non_pictures_and_tricky_names_are_refused():
    assert "isn't a picture" in backgrounds.save("x.png", b"<script>alert(1)</script>")["error"]
    assert "empty" in backgrounds.save("x.png", b"")["error"]
    assert backgrounds.path_for("../settings.json") is None
    assert backgrounds.path_for("../../.ssh/id_rsa") is None


def test_heic_without_sips_explains_itself(monkeypatch):
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32
    monkeypatch.setattr(backgrounds, "_to_jpeg", lambda data: None)  # not on a Mac
    assert "HEIC" in backgrounds.save("IMG_0001.HEIC", heic)["error"]
    monkeypatch.setattr(backgrounds, "_to_jpeg", lambda data: b"\xff\xd8\xff\xe0jpegdata")
    assert backgrounds.save("IMG_0001.HEIC", heic)["name"].endswith("-img_0001.jpg")

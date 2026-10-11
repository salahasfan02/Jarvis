"""Smart lights (against a fake Tapo bulb) and Apple Music catalogue playback
(without touching the real Music app)."""
from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest
from kasa import AuthenticationError, Module

from app import lights
from app.chat import quick
from app.tools.builtin import lights_tools, music


def run(coro):
    return asyncio.run(coro)


# --- a fake bulb ----------------------------------------------------------------------

class FakeLight:
    def __init__(self):
        self.brightness, self.color_temp, self.hsv = 80, 2700, (0, 0, 80)

    def has_feature(self, name):
        return name in ("brightness", "color_temp", "hsv")

    async def set_brightness(self, b):
        self.brightness = b

    async def set_color_temp(self, k):
        self.color_temp = k

    async def set_hsv(self, h, s, v):
        self.hsv, self.color_temp, self.brightness = (h, s, v), 0, v


class FakeConfig:
    def __init__(self, host):
        self.host = host

    def to_dict_control_credentials(self, credentials_hash=None, exclude_credentials=False):
        return {"host": self.host, "credentials_hash": credentials_hash,
                "connection_type": {"device_family": "SMART.TAPOBULB"}}


class FakeKind:
    def __init__(self, value):
        self.value = value


class FakeBulb:
    instances: dict[str, "FakeBulb"] = {}

    def __init__(self, host, mac="AA:BB:CC:00:00:01", alias="Bedroom", kind="bulb", password_ok=True):
        self.host, self.mac, self.alias, self.model = host, mac, alias, "L530B"
        self.device_type, self.config = FakeKind(kind), FakeConfig(host)
        self.credentials_hash, self.is_on = "a2xhcC1oYXNo", True
        self.modules = {Module.Light: FakeLight()}
        self.password_ok = password_ok
        FakeBulb.instances[mac] = self

    async def update(self):
        if not self.password_ok:
            raise AuthenticationError("Device response did not match our challenge")

    async def turn_on(self):
        self.is_on = True

    async def turn_off(self):
        self.is_on = False


@pytest.fixture
def home_network(monkeypatch):
    """One bulb and one camera on the Wi-Fi; Device.connect returns the bulb."""
    from kasa import Discover
    bulb = FakeBulb("192.168.0.48")
    camera = FakeBulb("192.168.0.91", mac="CA:ME:RA", alias="Camera", kind="camera")
    network = {"192.168.0.48": bulb, "192.168.0.91": camera}

    async def discover(credentials=None, timeout=5, **kw):
        return dict(network)

    async def connect(light):
        return network[light["host"]] if light["host"] in network else (_ for _ in ()).throw(OSError("timeout"))

    monkeypatch.setattr(Discover, "discover", discover)
    monkeypatch.setattr(lights, "_connect", connect)
    lights._devices.clear()
    lights.forget()
    yield network
    lights.forget()


def test_connecting_keeps_a_key_not_the_password(home_network):
    found = run(lights.connect_account("me@example.com", "s3cret-pass"))
    assert [x["name"] for x in found] == ["Bedroom"]            # the camera is left alone
    text = lights.STORE.read_text()
    assert "s3cret-pass" not in text and "a2xhcC1oYXNo" in text
    assert stat.S_IMODE(os.stat(lights.STORE).st_mode) == 0o600


def test_a_wrong_password_says_so(home_network):
    home_network["192.168.0.48"].password_ok = False
    with pytest.raises(lights.LightsError, match="didn't accept"):
        run(lights.connect_account("me@example.com", "wrong"))
    assert not lights.configured()


def test_on_off_brightness_colour_and_warmth(home_network):
    run(lights.connect_account("me@example.com", "pw"))
    bulb = home_network["192.168.0.48"]
    assert run(lights.control(power="off")) == "Bedroom: off."
    assert bulb.is_on is False
    out = run(lights.control(brightness=30))
    assert bulb.is_on and bulb.modules[Module.Light].brightness == 30 and "30%" in out
    run(lights.control(change=-50))
    assert bulb.modules[Module.Light].brightness == 1               # never below 1
    out = run(lights.control("bedroom light", color="blue"))
    assert bulb.modules[Module.Light].hsv[0] == 225 and "blue" in out
    out = run(lights.control(color="warm white"))
    assert bulb.modules[Module.Light].color_temp == 2700 and "2700K" in out
    with pytest.raises(lights.LightsError, match="colour"):
        run(lights.control(color="sparkly"))


def test_a_bulb_that_moved_address_is_found_again(home_network):
    run(lights.connect_account("me@example.com", "pw"))
    bulb = home_network.pop("192.168.0.48")
    bulb.host = "192.168.0.77"
    home_network["192.168.0.77"] = bulb
    lights._devices.clear()
    assert run(lights.control(power="on")) == "Bedroom: on, 80%, white 2700K."
    assert json.loads(lights.STORE.read_text())["lights"][0]["host"] == "192.168.0.77"


def test_the_lights_tool_without_setup_explains_where_to_connect(home_network):
    assert "Settings → Smart lights" in run(lights_tools.lights_tool(power="off"))


def test_light_commands_are_instant_once_set_up(home_network, monkeypatch):
    assert quick.match("lights off") is None                      # nothing set up yet
    run(lights.connect_account("me@example.com", "pw"))
    cases = {
        "lights off": {"power": "off", "light": ""},
        "turn on the bedroom light": {"power": "on", "light": "bedroom"},
        "lights to 30%": {"brightness": 30, "light": ""},
        "dim the lights": {"change": -30, "light": ""},
        "make the lights blue": {"color": "blue", "light": ""},
    }
    for said, args in cases.items():
        action = quick.match(said)
        assert action and action.tool == "lights" and action.arguments == args, said
    assert quick.match("turn off the lights at 11pm") is None      # a routine, for the model


def test_colour_words():
    assert lights.parse_color("warm") == ("temp", 2700)
    assert lights.parse_color("3000k") == ("temp", 3000)
    assert lights.parse_color("make it hot pink please") == ("hsv", (325, 85))
    assert lights.parse_color("#ff0000") == ("hsv", (0, 100))
    assert lights.parse_color("sparkly") is None


# --- Apple Music -------------------------------------------------------------------------

HITS = [
    {"trackName": "Janice STFU (Remix)", "artistName": "Oishi Manko", "trackId": 2, "collectionId": 20},
    {"trackName": "Janice STFU", "artistName": "Drake", "trackId": 1, "collectionId": 10},
    {"trackName": "Something Else", "artistName": "Drake", "trackId": 3, "collectionId": 30},
]


def test_the_asked_for_song_wins_over_remixes_and_namesakes():
    assert music.best_match("janice stfu by drake", HITS)["trackId"] == 1
    assert music.best_match("completely different", HITS) is None


def test_play_x_goes_to_apple_music_unless_youtube():
    assert quick.match("play janice stfu by drake").tool == "music_play"
    assert quick.match("play last christmas by wham").arguments == {"query": "last christmas by wham"}
    assert quick.match("play lofi on youtube").tool == "youtube_play"
    assert quick.match("play next song") is None


def test_a_song_not_in_the_library_is_played_from_the_catalogue(monkeypatch):
    opened, queued = [], []

    async def search(query, limit=10):
        return HITS

    monkeypatch.setattr(music, "catalog_search", search)
    monkeypatch.setattr(music, "_osascript", lambda s, timeout=20: "NOTFOUND")
    monkeypatch.setattr(music.subprocess, "run", lambda cmd, **kw: opened.append(cmd))
    monkeypatch.setattr(music, "_queue_and_play", lambda title, wait=15.0: queued.append(title) or "OK")
    out = run(music.music_play("janice stfu by drake"))
    assert out == "Playing Janice STFU by Drake from Apple Music."
    assert opened[0][:2] == ["open", "-g"] and "album/10?i=1" in opened[0][2]
    assert queued == ["Janice STFU"]


def test_without_accessibility_it_says_what_to_do(monkeypatch):
    async def search(query, limit=10):
        return HITS
    monkeypatch.setattr(music, "catalog_search", search)
    monkeypatch.setattr(music.subprocess, "run", lambda cmd, **kw: None)
    monkeypatch.setattr(music, "_queue_and_play", lambda title, wait=15.0: "NEEDS_ACCESSIBILITY")
    assert "Accessibility" in run(music.play_from_catalog("janice stfu by drake"))


def test_music_requests_go_to_apple_music_unless_youtube_is_asked_for():
    from app.chat.service import _music_service
    assert _music_service("put on some relaxing jazz", "youtube_play", {"query": "relaxing jazz"}) == \
        ("music_play", {"query": "relaxing jazz"})
    assert _music_service("play the drake video on youtube", "youtube_play", {"query": "drake"})[0] == "youtube_play"

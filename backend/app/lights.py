"""Smart lights (TP-Link Tapo / Kasa) on the home Wi-Fi.

Jarvis talks to the bulbs directly on the local network (python-kasa), so it
works alongside Alexa without going through it. Newer Tapo firmware wants
the Tapo account to sign every connection: the user types their email and
password once (Settings → Smart lights); Jarvis connects, keeps only the
per-device key the bulb derives from them (a hash — not the password, and
not usable to sign in to the Tapo account) and forgets the password.

Saved in ~/.jarvis/lights.json (owner-only): name, model, address and that
key for each light. If the router gives a bulb a new address, it's found
again by its hardware address.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

from .config import JARVIS_HOME

STORE = JARVIS_HOME / "lights.json"
LIGHT_TYPES = {"bulb", "lightstrip", "dimmer", "plug", "wallswitch"}

# Colour words -> (hue, saturation); white shades are colour temperatures.
COLORS = {
    "red": (0, 100), "orange": (28, 100), "amber": (38, 100), "yellow": (55, 100),
    "lime": (90, 100), "green": (120, 100), "teal": (170, 100), "cyan": (185, 100),
    "turquoise": (175, 90), "blue": (225, 100), "navy": (235, 100), "indigo": (255, 100),
    "purple": (275, 100), "violet": (280, 90), "magenta": (300, 100), "pink": (330, 60),
    "hot pink": (325, 85), "rose": (345, 70),
}
WHITES = {"warm": 2700, "warm white": 2700, "candle": 2500, "soft white": 3000,
          "neutral": 4000, "white": 4000, "natural": 4000, "cool": 5500,
          "cool white": 5500, "daylight": 6500, "cold": 6500}

_devices: dict[str, object] = {}       # light id -> connected kasa Device
_locks: dict[str, asyncio.Lock] = {}
_unreachable: dict[str, float] = {}    # light id -> when it last failed to answer
CONNECT_SECONDS = 4                    # a bulb that's off at the wall shouldn't stall Jarvis


class LightsError(Exception):
    pass


# --- storage ---------------------------------------------------------------------------

def _load() -> dict:
    try:
        return json.loads(STORE.read_text())
    except (OSError, ValueError):
        return {"lights": []}


def _save(data: dict) -> None:
    fd = os.open(STORE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.chmod(STORE, 0o600)


def saved() -> list[dict]:
    return _load().get("lights", [])


def configured() -> bool:
    return bool(saved())


def forget() -> None:
    _devices.clear()
    try:
        STORE.unlink()
    except FileNotFoundError:
        pass


# --- connecting --------------------------------------------------------------------------

def _kind(dev) -> str:
    kind = str(getattr(getattr(dev, "device_type", None), "value", "")).lower()
    if kind not in ("", "unknown"):
        return kind
    # A Tapo device only knows its type once signed in; until then go by the
    # family it announces (SMART.TAPOBULB, SMART.IPCAMERA, …).
    family = str(getattr(getattr(getattr(getattr(dev, "config", None), "connection_type", None),
                                 "device_family", None), "value", "")).upper()
    for word, k in (("BULB", "bulb"), ("PLUG", "plug"), ("SWITCH", "wallswitch")):
        if word in family:
            return k
    return "unknown"


async def connect_account(email: str, password: str, timeout: int = 6) -> list[dict]:
    """Find the lights on this network with the user's Tapo account and save
    a key for each. The password itself is never stored."""
    from kasa import AuthenticationError, Credentials, Discover
    creds = Credentials(email.strip(), password)
    found = await Discover.discover(credentials=creds, timeout=timeout)
    lights, rejected, failed = [], 0, []
    for host, dev in found.items():
        if _kind(dev) not in LIGHT_TYPES:
            continue                                   # cameras, hubs, vacuums…
        try:
            await dev.update()
        except AuthenticationError:
            rejected += 1
            continue
        except Exception as e:
            failed.append(f"{dev.model or host}: {e}")
            continue
        if _kind(dev) not in LIGHT_TYPES:
            continue                                   # signed in, and it isn't a light after all
        config = dev.config.to_dict_control_credentials(credentials_hash=dev.credentials_hash)
        lights.append({"id": dev.mac, "name": dev.alias or dev.model, "model": dev.model,
                       "kind": _kind(dev), "host": host, "config": config})
        _devices[dev.mac] = dev
    for dev in found.values():
        if dev not in _devices.values():
            try:
                await dev.disconnect()       # don't leave a connection open to each one skipped
            except Exception:
                pass
    if not lights:
        if rejected:
            raise LightsError(
                "Your light didn't accept that Tapo email and password (both are case-sensitive). "
                "If they're right, turn on Third-Party Compatibility in the Tapo app "
                "(Me → Tapo Lab, or Me → Third-Party Services) and try again.")
        if failed:
            raise LightsError("Found your light but couldn't connect — " + "; ".join(failed))
        raise LightsError("No Tapo or Kasa lights answered on this Wi-Fi network.")
    _save({"lights": lights, "connected_at": time.time()})
    return [_public(x) for x in lights]


def _public(light: dict) -> dict:
    return {k: light[k] for k in ("id", "name", "model", "kind")}


async def _connect(light: dict):
    from kasa import Device, DeviceConfig
    cfg = DeviceConfig.from_dict(light["config"])
    cfg.timeout = 3
    # python-kasa retries an unreachable bulb for ~25 s; one short try is enough.
    return await asyncio.wait_for(Device.connect(config=cfg), CONNECT_SECONDS)


async def _rediscover(light: dict) -> bool:
    """The router moved the bulb to a new address: find it by its MAC."""
    from kasa import Discover
    found = await Discover.discover(timeout=4)
    for host, dev in found.items():
        if str(getattr(dev, "mac", "")).lower() == light["id"].lower() and host != light["host"]:
            data = _load()
            for x in data.get("lights", []):
                if x["id"] == light["id"]:
                    x["host"] = host
                    x["config"]["host"] = host
            _save(data)
            light["host"], light["config"]["host"] = host, host
            return True
    return False


async def _device(light: dict, quick: bool = False):
    """A connected, freshly-updated device for this light. quick: don't retry a
    light that failed in the last minute (status checks shouldn't wait on it)."""
    if quick and time.time() - _unreachable.get(light["id"], 0) < 60:
        raise LightsError(f"{light['name']} isn't answering — is it switched on at the wall?")
    dev = _devices.get(light["id"])
    if dev is not None:
        try:
            await dev.update()
            return dev
        except Exception:
            _devices.pop(light["id"], None)
    try:
        dev = await _connect(light)
    except Exception:
        if not await _rediscover(light):
            _unreachable[light["id"]] = time.time()
            raise LightsError(f"Couldn't reach {light['name']} — is it switched on and on this Wi-Fi?")
        try:
            dev = await _connect(light)
        except Exception as e:
            _unreachable[light["id"]] = time.time()
            raise LightsError(f"Couldn't reach {light['name']}: {e}") from e
    _unreachable.pop(light["id"], None)
    _devices[light["id"]] = dev
    return dev


# --- what the user means ------------------------------------------------------------------

def pick(name: str = "") -> list[dict]:
    """The lights a name refers to: '' / 'all' / 'lights' = every light."""
    lights = saved()
    n = (name or "").strip().lower()
    if not n or n in ("all", "lights", "the lights", "all lights", "everything", "light", "the light"):
        return lights
    n = re.sub(r"\b(?:the|light|lights|lamp|bulb)\b", "", n).strip()
    hits = [x for x in lights if n and (n in x["name"].lower() or x["name"].lower() in n)]
    if not hits and len(lights) == 1:
        return lights          # only one light: "the bedroom light" can only mean it
    return hits


def parse_color(text: str) -> tuple[str, object] | None:
    """'blue' -> ('hsv', (225, 100)); 'warm' -> ('temp', 2700); '#ff8800' -> ('hsv', …)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in WHITES:
        return "temp", WHITES[t]
    if m := re.fullmatch(r"(\d{4})\s*k?", t):
        return "temp", max(2500, min(6500, int(m.group(1))))
    if t in COLORS:
        return "hsv", COLORS[t]
    if m := re.fullmatch(r"#?([0-9a-f]{6})", t):
        import colorsys
        r, g, b = (int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))
        h, s, _v = colorsys.rgb_to_hsv(r, g, b)
        return "hsv", (round(h * 360), round(s * 100))
    for word, value in sorted(COLORS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{word}\b", t):
            return "hsv", value
    for word, value in sorted(WHITES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{word}\b", t):
            return "temp", value
    return None


def _describe(light: dict, dev) -> str:
    if not dev.is_on:
        return f"{light['name']}: off"
    from kasa import Module
    lm = dev.modules.get(Module.Light)
    if lm is None:
        return f"{light['name']}: on"
    parts = [f"{light['name']}: on"]
    if lm.has_feature("brightness"):
        parts.append(f"{lm.brightness}%")
    temp = lm.color_temp if lm.has_feature("color_temp") else 0
    if temp:
        parts.append(f"white {temp}K")
    elif lm.has_feature("hsv"):
        h, s, _v = lm.hsv
        name = min(COLORS, key=lambda c: min(abs(COLORS[c][0] - h), 360 - abs(COLORS[c][0] - h)))
        parts.append(name if s > 25 else "white")
    return ", ".join(parts)


# --- doing it ---------------------------------------------------------------------------

async def control(light_name: str = "", power: str = "", brightness: int | None = None,
                  change: int | None = None, color: str = "") -> str:
    """power: on | off | toggle | ''. brightness 1-100; change: +/- percent.
    color: a colour, a white shade ('warm') or a temperature."""
    from kasa import Module
    if not configured():
        raise LightsError("No lights are set up yet — connect your Tapo account in Settings → Smart lights.")
    targets = pick(light_name)
    if not targets:
        names = ", ".join(x["name"] for x in saved())
        raise LightsError(f"There's no light called “{light_name}”. Your lights: {names}.")
    wanted = parse_color(color) if color else None
    if color and wanted is None:
        raise LightsError(f"I don't know the colour “{color}”.")
    results = []
    for light in targets:
        lock = _locks.setdefault(light["id"], asyncio.Lock())
        async with lock:
            dev = await _device(light)
            lm = dev.modules.get(Module.Light)
            if power == "off" or (power == "toggle" and dev.is_on):
                await dev.turn_off()
            else:
                if power in ("on", "toggle") or brightness or change or wanted:
                    if not dev.is_on:
                        await dev.turn_on()
                if lm is not None and wanted:
                    kind, value = wanted
                    if kind == "temp" and lm.has_feature("color_temp"):
                        await lm.set_color_temp(int(value))
                    elif kind == "hsv" and lm.has_feature("hsv"):
                        h, s = value
                        level = brightness or (lm.brightness if lm.has_feature("brightness") else 100)
                        await lm.set_hsv(int(h), int(s), int(level or 100))
                if lm is not None and lm.has_feature("brightness") and (brightness or change):
                    level = brightness if brightness else (lm.brightness or 0) + int(change or 0)
                    await lm.set_brightness(max(1, min(100, int(level))))
            await dev.update()
            results.append(_describe(light, dev))
    return "; ".join(results) + "."


async def status() -> list[dict]:
    """Every light at once (in parallel), not waiting on ones that just failed."""
    return list(await asyncio.gather(*(_status_one(light) for light in saved())))


async def _status_one(light: dict) -> dict:
    from kasa import Module
    entry = _public(light)
    try:
        dev = await _device(light, quick=True)
    except Exception as e:
        return {**entry, "reachable": False, "on": False, "text": str(e)}
    entry.update(reachable=True, on=bool(dev.is_on), text=_describe(light, dev))
    lm = dev.modules.get(Module.Light)
    if lm is not None and lm.has_feature("brightness"):
        entry["brightness"] = lm.brightness
    return entry

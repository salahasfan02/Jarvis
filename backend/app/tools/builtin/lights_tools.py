"""The lights tool: Tapo / Kasa smart lights on the home network (see app/lights.py)."""
from __future__ import annotations

from ... import lights
from ..base import tool


@tool(
    name="lights",
    description="Control the user's smart lights: on/off, brightness, colour, or warm/cool "
                "white. 'lights off', 'dim the bedroom light', 'make the lights blue', 'warm "
                "white at 40%'. Leave light empty for all lights; call with nothing to hear "
                "how they are.",
    parameters={
        "type": "object",
        "properties": {
            "power": {"type": "string", "enum": ["on", "off", "toggle"]},
            "brightness": {"type": "integer", "description": "1-100 percent"},
            "change": {"type": "integer", "description": "relative change in percent, e.g. 20 or -20"},
            "color": {"type": "string",
                      "description": "a colour (blue, red, pink…), a white (warm, neutral, cool, "
                                     "daylight) or a temperature like 3000K"},
            "light": {"type": "string", "description": "which light, by name; empty = all"},
        },
    },
)
async def lights_tool(power: str = "", brightness: int = 0, change: int = 0, color: str = "",
                      light: str = "") -> str:
    try:
        if not (power or brightness or change or color):
            if not lights.configured():
                return ("No lights are set up yet — connect your Tapo account in Settings → "
                        "Smart lights.")
            return "; ".join(x["text"] for x in await lights.status()) + "."
        return await lights.control(light, power=power, brightness=brightness or None,
                                    change=change or None, color=color)
    except lights.LightsError as e:
        return str(e)

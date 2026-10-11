"""Weather from Open-Meteo: free, no API key, real numbers.

Weather pages don't survive web search — their snippets say "14-day forecast
for London" and their pages are drawn by JavaScript — so this asks a weather
service directly. Where: the place the user names, else the town in their
profile (Settings → About you), else where the internet connection is.
"""
from __future__ import annotations

import datetime
import time

import httpx

from ...config import settings
from ..base import tool

SOURCE = "Open-Meteo — https://open-meteo.com"
WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog",
    48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
    82: "heavy showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorms",
    96: "thunderstorms with hail", 99: "thunderstorms with hail",
}
_ip_place: tuple[float, dict] | None = None    # (when, place) — cached for 6 hours


async def _geocode(client: httpx.AsyncClient, name: str) -> dict | None:
    """'Paris, France' / 'Haringey' / 'N8' -> the best matching place."""
    parts = [p.strip() for p in name.split(",") if p.strip()]
    if not parts:
        return None
    r = await client.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": parts[0], "count": 10, "language": "en"})
    r.raise_for_status()
    results = r.json().get("results") or []
    if len(parts) > 1:   # "Paris, Texas": prefer results that mention the rest
        hint = " ".join(parts[1:]).lower()
        matching = [x for x in results if hint in " ".join(
            str(x.get(k, "")) for k in ("country", "country_code", "admin1", "admin2")).lower()]
        results = matching or results
    if not results:
        return None
    x = results[0]
    label = ", ".join(dict.fromkeys(v for v in (x.get("name"), x.get("admin1"), x.get("country")) if v))
    return {"lat": x["latitude"], "lon": x["longitude"], "label": label,
            "country": x.get("country_code", "")}


async def _from_connection(client: httpx.AsyncClient) -> dict | None:
    global _ip_place
    if _ip_place and time.time() - _ip_place[0] < 6 * 3600:
        return _ip_place[1]
    r = await client.get("https://ipinfo.io/json")
    r.raise_for_status()
    d = r.json()
    lat, lon = (float(v) for v in d["loc"].split(","))
    place = {"lat": lat, "lon": lon, "country": d.get("country", ""), "guessed": True,
             "label": ", ".join(v for v in (d.get("city"), d.get("region")) if v)}
    _ip_place = (time.time(), place)
    return place


async def _where(client: httpx.AsyncClient, place: str) -> dict | None:
    if place.strip():
        return await _geocode(client, place)
    from ...memory import profile
    me = profile.get()
    for guess in (", ".join(v for v in (me.get("city"), me.get("country")) if v),
                  me.get("postcode", "")):
        if guess and (found := await _geocode(client, guess)):
            return found
    return await _from_connection(client)


def _units(country: str) -> dict:
    if country == "US":
        return {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "t": "°F", "w": "mph"}
    if country == "GB":
        return {"temperature_unit": "celsius", "wind_speed_unit": "mph", "t": "°C", "w": "mph"}
    return {"temperature_unit": "celsius", "wind_speed_unit": "kmh", "t": "°C", "w": "km/h"}


def _rain_soon(hourly: dict, now: datetime.datetime) -> str:
    """When rain is likely in the next 12 hours, if at all."""
    for t, p in zip(hourly.get("time", []), hourly.get("precipitation_probability", [])):
        when = datetime.datetime.fromisoformat(t)
        if now - datetime.timedelta(hours=1) < when <= now + datetime.timedelta(hours=12):
            if (p or 0) >= 50:
                return f"Rain likely from about {when:%H:%M} ({p}% chance)."
    return "Dry for the next 12 hours."


@tool(
    name="weather",
    description="Current weather and the forecast for a place — temperature, rain, wind, "
                "sunrise/sunset. Use for ANY weather question (today, tomorrow, this week, "
                "'do I need an umbrella', 'is it cold'). Leave place empty for where the "
                "user is.",
    parameters={
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "town or city (optional; empty = here)"},
            "days": {"type": "integer", "description": "days of forecast, 1-7 (default 3)"},
        },
    },
)
async def weather(place: str = "", days: int = 3) -> str:
    days = max(1, min(int(days or 3), 7))
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            where = await _where(client, place or settings.get("weather.location", ""))
        except (httpx.HTTPError, KeyError, ValueError) as e:
            return f"Couldn't work out the location: {e}"
        if where is None:
            return f"Couldn't find a place called '{place}'. Ask the user which town they mean."
        u = _units(where.get("country", ""))
        try:
            r = await client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": where["lat"], "longitude": where["lon"], "timezone": "auto",
                "forecast_days": days, "temperature_unit": u["temperature_unit"],
                "wind_speed_unit": u["wind_speed_unit"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                           "weather_code,wind_speed_10m",
                "hourly": "precipitation_probability",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                         "precipitation_probability_max,sunrise,sunset",
            })
            r.raise_for_status()
            w = r.json()
        except (httpx.HTTPError, ValueError) as e:
            return f"Couldn't get the weather: {e}"

    cur, daily = w.get("current", {}), w.get("daily", {})
    now = datetime.datetime.fromisoformat(cur["time"]) if cur.get("time") else datetime.datetime.now()
    t, wu = u["t"], u["w"]
    lines = [f"Weather for {where['label']} (local time {now:%H:%M}):",
             f"Now: {round(cur.get('temperature_2m', 0))}{t}, feels like "
             f"{round(cur.get('apparent_temperature', 0))}{t}, "
             f"{WMO.get(cur.get('weather_code'), 'unknown conditions')}, wind "
             f"{round(cur.get('wind_speed_10m', 0))} {wu}, humidity "
             f"{cur.get('relative_humidity_2m', '?')}%.",
             _rain_soon(w.get("hourly", {}), now)]
    for i, day in enumerate(daily.get("time", [])):
        d = datetime.date.fromisoformat(day)
        name = "Today" if i == 0 else "Tomorrow" if i == 1 else d.strftime("%A")
        sunrise = daily["sunrise"][i][-5:] if daily.get("sunrise") else "?"
        sunset = daily["sunset"][i][-5:] if daily.get("sunset") else "?"
        lines.append(
            f"{name} ({d:%a %d %b}): {round(daily['temperature_2m_min'][i])}–"
            f"{round(daily['temperature_2m_max'][i])}{t}, "
            f"{WMO.get(daily['weather_code'][i], 'mixed')}, "
            f"{daily['precipitation_probability_max'][i] or 0}% chance of rain, "
            f"sunrise {sunrise}, sunset {sunset}.")
    if where.get("guessed"):
        lines.append("(Location guessed from the internet connection — the user can set "
                     "their town under Settings → About you.)")
    lines.append(f"Source: {SOURCE}")
    return "\n".join(lines)

"""Web research, weather, and how answers carry their sources — all against
fake network responses (no internet needed)."""
from __future__ import annotations

import asyncio
import base64

import httpx

from app.chat import service
from app.tools.builtin import research as R
from app.tools.builtin import weather as W


def run(coro):
    return asyncio.run(coro)


# --- research ------------------------------------------------------------------------

def test_pages_are_taken_apart_one_at_a_time(monkeypatch):
    """Two threads parsing with trafilatura's shared lxml parser can crash the
    backend: pages download together but are parsed one by one, on one thread."""
    import threading
    import time
    real, busy, most, threads = R._extract, [0], [0], set()
    lock = threading.Lock()

    def extract(*args):
        with lock:
            busy[0] += 1
            most[0] = max(most[0], busy[0])
        threads.add(threading.current_thread().name)
        time.sleep(0.02)
        try:
            return real(*args)
        finally:
            with lock:
                busy[0] -= 1

    monkeypatch.setattr(R, "_extract", extract)
    page = (b"<html><head><title>MCP</title></head><body><p>"
            + b"Servers expose tools to the model. " * 20 + b"</p></body></html>")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=page, headers={"content-type": "text/html"}))

    async def main():
        async with httpx.AsyncClient(transport=transport) as client:
            return await asyncio.gather(*(R.read_page(client, f"https://example.com/{i}")
                                          for i in range(6)))

    assert all(r and r[1] == "MCP" for r in run(main()))
    assert most[0] == 1 and len(threads) == 1

def test_pages_are_split_into_passages_of_a_readable_size():
    text = "Intro line about MCP servers and what they do.\n" + ("Sentence about tools. " * 80)
    parts = R.passages(text, target=300)
    assert len(parts) > 3 and all(len(p) <= 450 for p in parts)
    assert parts[0].startswith("Intro line")


def test_bing_click_links_are_unwrapped():
    real = "https://example.com/mcp?a=1"
    u = "a1" + base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
    assert R._bing_target(f"https://www.bing.com/ck/a?!&&p=x&u={u}&ntb=1") == real
    assert R._bing_target("https://example.com/plain") == "https://example.com/plain"


def test_search_falls_back_to_the_next_engine(monkeypatch):
    async def refused(client, q):
        raise httpx.ConnectError("challenge page")

    async def empty(client, q):
        return []

    async def bing(client, q):
        return [R.Hit("A", "https://a.com/x"), R.Hit("A again", "https://a.com/x/"),
                R.Hit("Ad", "https://duckduckgo.com/y.js?ad"), R.Hit("B", "https://b.org")]

    monkeypatch.setattr(R, "_duckduckgo", refused)
    monkeypatch.setattr(R, "_duckduckgo_lite", empty)
    monkeypatch.setattr(R, "_bing", bing)
    hits = run(R.search("mcp"))
    assert [h.url for h in hits] == ["https://a.com/x", "https://b.org"]


def _fake_web(monkeypatch, pages: dict, hits: list):
    async def search(q, n=8):
        return hits

    async def read_page(client, url):
        return pages.get(url)

    async def rank(question, candidates):   # shared words, no embedding model needed
        q = R._words(question)
        return [len(q & R._words(c)) / len(q) for c in candidates]

    monkeypatch.setattr(R, "search", search)
    monkeypatch.setattr(R, "read_page", read_page)
    monkeypatch.setattr(R, "rank", rank)


def test_research_keeps_relevant_passages_and_numbers_the_sources(monkeypatch):
    on_topic = ("MCP servers expose tools and resources to AI applications.\n\n"
                "An MCP server is a program speaking the Model Context Protocol.\n\n" + "Footer. " * 40)
    _fake_web(monkeypatch, {
        "https://mcp.io/intro": ("https://mcp.io/intro", "What is MCP", on_topic, "2026-07-28"),
        "https://cooking.com/soup": ("https://cooking.com/soup", "Soup", "Boil the onions slowly. " * 30, ""),
    }, [R.Hit("What is MCP", "https://mcp.io/intro"),
        R.Hit("Soup", "https://cooking.com/soup"),
        R.Hit("MCP guide", "https://blocked.example/mcp", "MCP servers connect AI apps to tools."),
        R.Hit("Video", "https://www.youtube.com/watch?v=1", "a video")])
    out = run(R.research("what is an MCP server"))
    found = R.sources_in(out)
    urls = [u for _, _, u in found]
    assert urls[0] == "https://mcp.io/intro"
    assert "https://blocked.example/mcp" in urls         # unreadable: its snippet still counts
    assert all("youtube" not in u for u in urls)          # no readable text there
    assert [n for n, _, _ in found] == list(range(1, len(found) + 1))
    assert "Model Context Protocol" in out and "2026-07-28" in out
    assert "[1]" in out and "Sources" in out              # tells the model how to cite


def test_research_says_so_when_nothing_turns_up(monkeypatch):
    _fake_web(monkeypatch, {}, [])
    assert "Couldn't find anything" in run(R.research("zxqv"))


# --- weather -------------------------------------------------------------------------

def _weather_web(monkeypatch, geocode_results):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        if "geocoding" in request.url.host:
            return httpx.Response(200, json={"results": geocode_results})
        if request.url.host == "ipinfo.io":
            return httpx.Response(200, json={"city": "London", "region": "England",
                                             "country": "GB", "loc": "51.5,-0.12"})
        return httpx.Response(200, json={
            "current": {"time": "2026-10-11T15:00", "temperature_2m": 15.6,
                        "apparent_temperature": 13.2, "relative_humidity_2m": 60,
                        "weather_code": 3, "wind_speed_10m": 7.4},
            "hourly": {"time": ["2026-10-11T15:00", "2026-10-11T18:00"],
                       "precipitation_probability": [10, 70]},
            "daily": {"time": ["2026-10-11", "2026-10-12"], "weather_code": [61, 2],
                      "temperature_2m_max": [16.2, 18.0], "temperature_2m_min": [9.1, 11.0],
                      "precipitation_probability_max": [70, 5],
                      "sunrise": ["2026-10-11T07:17", "2026-10-12T07:19"],
                      "sunset": ["2026-10-11T18:16", "2026-10-12T18:13"]}})

    real = httpx.AsyncClient
    monkeypatch.setattr(W.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(W, "_ip_place", None)
    return calls


def test_weather_for_a_named_place(monkeypatch):
    calls = _weather_web(monkeypatch, [
        {"name": "Paris", "admin1": "Texas", "country": "United States", "country_code": "US",
         "latitude": 33.6, "longitude": -95.5},
        {"name": "Paris", "admin1": "Île-de-France", "country": "France", "country_code": "FR",
         "latitude": 48.85, "longitude": 2.35}])
    out = run(W.weather("Paris, France", days=2))
    assert out.startswith("Weather for Paris, Île-de-France, France")
    assert "Now: 16°C" in out and "overcast" in out and "km/h" in out
    assert "Rain likely from about 18:00 (70% chance)" in out
    assert "Today (Sun 11 Oct): 9–16°C, light rain, 70% chance of rain" in out
    assert "Source: Open-Meteo" in out
    assert not any(u.host == "ipinfo.io" for u in calls)


def test_weather_here_uses_the_profile_town_then_the_connection(monkeypatch):
    from app.config import settings
    settings.update({"profile": {}})
    _weather_web(monkeypatch, [])
    out = run(W.weather())
    assert "Weather for London, England" in out and "mph" in out   # UK: mph, °C
    assert "guessed from the internet connection" in out


def test_weather_for_a_place_that_doesnt_exist(monkeypatch):
    _weather_web(monkeypatch, [])
    assert "Couldn't find a place called 'Qwertyzzz'" in run(W.weather("Qwertyzzz"))


# --- how replies are tidied ------------------------------------------------------------

def test_lead_ins_before_tools_are_dropped_but_facts_kept():
    reply = ("Sure, I'll create that now. Give me a moment.\n\nI've created 'MCP Servers' "
             "and saved it in Documents.")
    assert service._without_lead_ins(reply, ["Sure, I'll create that now. Give me a moment."]) \
        == "I've created 'MCP Servers' and saved it in Documents."
    mixed = "Paris is the capital of France. Let me check the weather."
    assert service._without_lead_ins(mixed + "\n\nIt's 16°C.", [mixed]).startswith("Paris")


def test_sources_are_appended_once_with_real_links():
    src = [(1, "What is MCP", "https://mcp.io/intro"), (2, "Guide", "https://g.dev/mcp")]
    out = service._with_sources("MCP links AI apps to tools [1].\n\n**Sources:** [1] What is MCP", src)
    assert out.endswith("Sources:\n[1] [What is MCP](https://mcp.io/intro)")
    assert out.count("Sources") == 1
    already = "MCP links AI apps to tools [1].\n\nSources:\n1. https://mcp.io/intro"
    assert service._with_sources(already, src) == already


def test_claims_must_match_a_tool_that_did_it():
    listed = [{"name": "list_directory", "result": "/Users/me/Desktop (3 items)"}]
    assert service._unbacked_claim("I've sent you the latest 3 files.", listed)
    sent = listed + [{"name": "send_file", "result": "Sent a.png to the user's phone"}]
    assert not service._unbacked_claim("I've sent you the latest 3 files.", sent)
    denied = listed + [{"name": "send_file", "result": "The user DENIED permission to run this tool."}]
    assert service._unbacked_claim("I've sent it.", denied)
    assert not service._unbacked_claim("Here are the 3 newest files.", listed)
    # denied the send, then claimed a draft that was never made
    refused = [{"name": "send_email", "result": "The user DENIED permission to run this tool."}]
    assert service._unbacked_claim("I couldn't send it, but I've prepared a draft for you in Mail.", refused)
    researched = [{"name": "research", "result": "Web research for: x"}]
    assert not service._unbacked_claim("I've prepared a summary of what I found below.", researched)
    assert service._unbacked_claim("I've prepared a Word document for you.", researched)
    drafted = refused + [{"name": "draft_email", "result": "Draft saved in Mail and opened for review."}]
    assert not service._unbacked_claim("I've prepared a draft for you in Mail.", drafted)


def test_a_folder_listed_only_to_find_something_isnt_shown():
    listing = "/Users/me/Desktop (2 items, newest first):\n2026-10-11  a.png\n2026-10-10  b.png"
    shown, _ = service.listing_for_display("list_directory", listing, "list all the files on my desktop")
    assert shown.startswith("```listing")
    hidden, for_model = service.listing_for_display("list_directory", listing, "send me the latest 3 files")
    assert hidden == "" and "a.png" in for_model


def test_a_research_report_is_written_from_the_sources_and_lists_them(monkeypatch):
    from app.llm import ollama_client
    from app.tools.builtin import documents
    sources = [R.Source("What is MCP", "https://mcp.io/intro", "mcp.io", "2026-07-28",
                        ["MCP is the Model Context Protocol."])]

    async def gather(topic, depth="quick"):
        return sources

    seen = {}

    async def chat_once(messages, model=None, format=None):
        seen["prompt"] = messages[-1]["content"]
        return ("# MCP Servers Explained\n\n## What they are\nMCP servers expose tools [1].\n\n"
                "## References\n- something the model made up")

    made = {}
    monkeypatch.setattr(R, "gather", gather)
    monkeypatch.setattr(ollama_client, "chat_once", chat_once)
    monkeypatch.setattr(documents, "create_word_document",
                        lambda title, content: made.update(title=title, content=content) or "Created it.")
    out = run(R.research_report("mcp servers"))
    assert "Model Context Protocol" in seen["prompt"]          # written from the sources
    assert made["title"] == "MCP Servers Explained"
    assert "made up" not in made["content"]                     # its own list replaced…
    assert made["content"].endswith("## Sources\n1. [What is MCP](https://mcp.io/intro) — mcp.io, 2026-07-28")
    assert "1 web sources" in out


def test_an_answer_given_twice_around_a_tool_call_is_said_once():
    first = "The latest in AI includes new generative models [1]. Want the details?"
    final = "The latest in AI: new generative models [1] and the MCP standard [2]."
    assert service._without_lead_ins(f"{first}\n\n{final}", [first], final) == final
    files = "Here are the latest files:\n1. a.png\n2. b.pdf\n\nI'll send them now."
    out = service._without_lead_ins(f"{files}\n\nSent both to your phone.", [files],
                                    "Sent both to your phone.")
    assert "1. a.png" in out and "I'll send" not in out


def test_an_email_meant_to_carry_a_file_must_attach_it():
    no_file = {"to": "a@b.com", "subject": "CV", "body": "Attached."}
    assert service._missing_attachment("email my CV to a@b.com", "send_email", no_file, []) == "CV"
    assert service._missing_attachment("send the lease to my landlord", "draft_email", no_file, []) == "lease"
    made = [{"name": "create_word_document", "result": "Created … at /x.docx"}]
    assert service._missing_attachment("write a shopping list doc and email it to me",
                                       "send_email", no_file, made) == "the file you just made"
    assert not service._missing_attachment("email my landlord that the boiler is broken",
                                           "send_email", no_file, [])
    assert not service._missing_attachment("email my CV to a@b.com", "send_email",
                                           {**no_file, "attachments": ["CV"]}, [])


def test_a_reminder_time_is_found_in_english_or_arabic():
    import datetime
    from app.chat.timeparse import find_when
    now = datetime.datetime(2026, 10, 11, 15, 0)
    assert find_when("ذكرني بالاتصال بأمي الساعة السادسة مساء", now) == datetime.datetime(2026, 10, 11, 18, 0)
    assert find_when("ذكرني غدا الساعة ٧ صباحا بالرياضة", now) == datetime.datetime(2026, 10, 12, 7, 0)
    assert find_when("ذكرني الساعة الثامنة والنصف مساء", now) == datetime.datetime(2026, 10, 11, 20, 30)
    assert find_when("remind me tomorrow at 9:30 to stretch", now) == datetime.datetime(2026, 10, 12, 9, 30)
    assert find_when("remind me to buy milk", now) is None
    assert find_when("send me 3 files", now) is None

"""Internet tools: search and page reading. No API keys required —
search uses DuckDuckGo's HTML endpoint."""
from __future__ import annotations

import asyncio
import html as html_lib
import ipaddress
import re
import socket

import httpx

from ..base import tool

def _strip_html(html: str, limit: int = 8000) -> str:
    html = re.sub(r"(?is)<(script|style|nav|footer|header|noscript).*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    text = html_lib.unescape(html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:limit]


@tool(
    name="web_search",
    description="Search the web. Returns result titles, URLs and snippets — always cite "
                "these URLs when you use the information. Use for current events, facts, "
                "weather, prices, news. Optional `site` scopes the search: github.com, "
                "stackoverflow.com, reddit.com, youtube.com, arxiv.org, or any domain.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "search query"},
            "site": {"type": "string", "description": "optional domain to restrict to"},
        },
        "required": ["query"],
    },
    agent_tags=["research"],
)
async def web_search(query: str, site: str = "") -> str:
    from .research import search   # DuckDuckGo, then fallbacks if it's refusing
    if site:
        query = f"site:{site.strip()} {query}"
    hits = await search(query, n=8)
    return "\n".join(f"- {h.title}\n  {h.url}\n  {h.snippet[:300]}" for h in hits) \
        or "No results found."


class PrivateAddress(httpx.RequestError):
    pass


def _is_public(host: str) -> bool:
    """True if every address `host` resolves to is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # unresolvable: let the request fail with a normal DNS error
    return all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in infos)


async def _only_public(request: httpx.Request) -> None:
    """Runs before every request, redirects included. web_fetch reads pages the
    model chose, often because a page it read told it to — it must not be a
    way into this Mac (Jarvis's own API on 127.0.0.1 holds memories and
    settings) or the home network (router admin pages, NAS)."""
    host = request.url.host
    if not await asyncio.to_thread(_is_public, host):
        raise PrivateAddress(f"{host} is a local or private network address", request=request)


@tool(
    name="web_fetch",
    description="Fetch a URL and return the readable text content of the page. "
                "Use to read articles, documentation, or any webpage.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "full URL including https://"}},
        "required": ["url"],
    },
    agent_tags=["research"],
)
async def web_fetch(url: str) -> str:
    from .research import read_page   # the page's main text, not its menus
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 event_hooks={"request": [_only_public]}) as client:
        if not await asyncio.to_thread(_is_public, httpx.URL(url).host):
            return (f"Refused: {httpx.URL(url).host} is a local or private network address. "
                    "web_fetch only reads public websites.")
        page = await read_page(client, url)
    if page is None:
        return "Couldn't read that page (it refused, isn't a web page, or didn't answer)."
    final, title, text, date = page
    head = f"{title}\n{final}" + (f"\nPublished: {date}" if date else "")
    return f"{head}\n\n{text[:8000]}" if text.strip() else "Page had no readable text."

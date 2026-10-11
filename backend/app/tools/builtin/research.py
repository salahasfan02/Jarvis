"""Research on the internet: search, read the best pages, keep the passages
that answer the question, and hand the model numbered sources to cite.

A 14B local model with an 8k context can't read five whole web pages, and
search snippets alone are too thin to answer from (a weather site's snippet
is "14-day forecast for London"). So this does the reading: it fetches the
top results in parallel, pulls each page's main text out of the menus and
adverts (trafilatura), splits it into passages and keeps the few closest in
meaning to the question (the local embedding model Jarvis uses for memory).
The model gets a short numbered digest and writes the answer with [n]
citations; the chat service makes sure a Sources list ends up under it.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import html as html_lib
import io
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import httpx

from ...llm import ollama_client
from ..base import tool
from .web import PrivateAddress, _only_public, _strip_html

BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
# Some sites (Wikipedia) turn away anything posing as a browser but welcome
# an honest client that says who it is.
HONEST_UA = {"User-Agent": "Jarvis/1.0 (personal research assistant; "
                           "https://github.com/Salahasfan02/Jarvis)"}

MAX_PAGE_BYTES = 3_000_000
PASSAGE_CHARS = 700
# Video and social pages have no readable text without a logged-in browser.
SKIP_SITES = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com",
              "x.com", "twitter.com", "pinterest.", "linkedin.com")
DEPTH = {   # pages read, passages kept per page, characters of passages in total
    "quick": {"pages": 4, "per_page": 2, "budget": 3200, "seconds": 18},
    "deep": {"pages": 7, "per_page": 3, "budget": 5200, "seconds": 30},
}


@dataclass
class Hit:
    title: str
    url: str
    snippet: str = ""


@dataclass
class Source:
    title: str
    url: str
    site: str
    date: str = ""
    passages: list[str] = field(default_factory=list)


# --- search -----------------------------------------------------------------------

def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"(?s)<[^>]+>", " ", fragment))).strip()


async def _duckduckgo(client: httpx.AsyncClient, query: str) -> list[Hit]:
    r = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
    r.raise_for_status()
    hits = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', r.text, re.S):
        url, title, snippet = m.groups()
        if "uddg=" in url:
            url = parse_qs(urlparse(html_lib.unescape(url)).query).get("uddg", [url])[0]
        hits.append(Hit(_text(title), url, _text(snippet)))
    return hits


async def _duckduckgo_lite(client: httpx.AsyncClient, query: str) -> list[Hit]:
    r = await client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
    r.raise_for_status()
    links = re.findall(r"<a[^>]+href=\"([^\"]+)\"[^>]+class=['\"]result-link['\"][^>]*>(.*?)</a>",
                       r.text, re.S)
    snippets = re.findall(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", r.text, re.S)
    hits = []
    for i, (url, title) in enumerate(links):
        if "uddg=" in url:
            url = parse_qs(urlparse(html_lib.unescape(url)).query).get("uddg", [url])[0]
        hits.append(Hit(_text(title), url, _text(snippets[i]) if i < len(snippets) else ""))
    return hits


def _bing_target(url: str) -> str:
    """Bing wraps results in a click-tracking link; the real URL is base64 in `u`."""
    url = html_lib.unescape(url)
    if "bing.com/ck/" not in url:
        return url
    u = parse_qs(urlparse(url).query).get("u", [""])[0]
    if u.startswith("a1"):
        try:
            return base64.urlsafe_b64decode(u[2:] + "=" * (-len(u[2:]) % 4)).decode()
        except (ValueError, UnicodeDecodeError):
            pass
    return url


async def _bing(client: httpx.AsyncClient, query: str) -> list[Hit]:
    r = await client.get("https://www.bing.com/search", params={"q": query, "setlang": "en"})
    r.raise_for_status()
    hits = []
    for block in re.findall(r'<li class="b_algo"(.*?)</li>', r.text, re.S):
        a = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        p = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        hits.append(Hit(_text(a.group(2)), _bing_target(a.group(1)), _text(p.group(1)) if p else ""))
    return hits


def _usable(hit: Hit) -> bool:
    host = urlparse(hit.url).hostname or ""
    return (hit.url.startswith(("http://", "https://")) and "duckduckgo.com" not in host
            and "bing.com" not in host)


async def search(query: str, n: int = 8) -> list[Hit]:
    """Web results, trying the next engine when one fails or comes back empty
    (DuckDuckGo sometimes answers automated searches with a challenge page)."""
    async with httpx.AsyncClient(timeout=12, headers=BROWSER_UA, follow_redirects=True) as client:
        for engine in (_duckduckgo, _duckduckgo_lite, _bing):
            try:
                hits = await engine(client, query)
            except (httpx.HTTPError, ValueError):
                continue
            seen, unique = set(), []
            for h in hits:
                key = h.url.split("#")[0].rstrip("/")
                if _usable(h) and key not in seen:
                    seen.add(key)
                    unique.append(h)
            if unique:
                return unique[:n]
    return []


# --- reading pages -------------------------------------------------------------------

def _site(url: str) -> str:
    host = urlparse(url).hostname or url
    return host[4:] if host.startswith("www.") else host


# trafilatura parses every page with one shared lxml parser, and an lxml parser
# used from two threads at once can corrupt memory and abort the whole backend
# (it did, mid-research). Pages still download in parallel; they're taken
# apart one at a time, always on this one thread.
_PAGE_READER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="page-reader")


def _extract(raw: bytes, ctype: str, encoding: str, url: str) -> tuple[str, str, str]:
    """(title, main text, date) of a page or PDF."""
    if "pdf" in ctype:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        text = "\n\n".join((p.extract_text() or "") for p in reader.pages[:20])
        title = str((reader.metadata or {}).get("/Title") or "")
        return title, text, ""
    html = raw.decode(encoding or "utf-8", errors="replace")
    if "json" in ctype or "text/plain" in ctype:    # an API answer or plain text: as it is
        return "", html[:20000], ""
    title, text, date = "", "", ""
    try:
        import trafilatura
        doc = trafilatura.bare_extraction(html, url=url, with_metadata=True,
                                          include_comments=False, include_tables=True)
        d = doc.as_dict() if hasattr(doc, "as_dict") else (doc or {})
        title, text, date = d.get("title") or "", d.get("text") or "", d.get("date") or ""
    except Exception:
        pass
    if len(text) < 200:      # extraction found no article: fall back to all the text
        text = _strip_html(html, limit=20000)
    if not title:
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        title = _text(m.group(1)) if m else ""
    return title, text, date


async def read_page(client: httpx.AsyncClient, url: str) -> tuple[str, str, str, str] | None:
    """(final url, title, text, date), or None when it can't be read."""
    for headers in (BROWSER_UA, HONEST_UA):
        try:
            async with client.stream("GET", url, headers=headers) as r:
                if r.status_code in (401, 403, 429, 503) and headers is BROWSER_UA:
                    continue
                if r.status_code >= 400:
                    return None
                ctype = r.headers.get("content-type", "").lower()
                if not any(k in ctype for k in ("html", "text", "pdf", "xml", "json")):
                    return None
                chunks, size = [], 0
                async for chunk in r.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        break
                final, encoding = str(r.url), r.encoding or "utf-8"
        except (PrivateAddress, httpx.HTTPError):
            return None
        title, text, date = await asyncio.get_running_loop().run_in_executor(
            _PAGE_READER, _extract, b"".join(chunks), ctype, encoding, final)
        return final, title, text, date
    return None


# --- choosing passages -----------------------------------------------------------------

def passages(text: str, target: int = PASSAGE_CHARS) -> list[str]:
    """Split page text into passages of roughly `target` characters along
    paragraph (then sentence) boundaries."""
    pieces: list[str] = []
    for para in (p.strip() for p in re.split(r"\n+", text)):
        if not para:
            continue
        if len(para) <= target * 1.5:
            pieces.append(para)
            continue
        sentence_run = ""
        for s in re.split(r"(?<=[.!?])\s+", para):
            if sentence_run and len(sentence_run) + len(s) > target:
                pieces.append(sentence_run)
                sentence_run = s
            else:
                sentence_run = f"{sentence_run} {s}".strip()
        if sentence_run:
            pieces.append(sentence_run)
    out, cur = [], ""
    for p in pieces:
        # a short line (a heading, a one-line definition) joins what follows
        if cur and len(cur) + len(p) + 1 > target and len(cur) >= target // 3:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        out.append(cur)
    return [x for x in out if len(x) >= 80 or re.search(r"\d", x)]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


async def rank(question: str, candidates: list[str]) -> list[float]:
    """How well each passage answers the question: meaning (embeddings) when
    the embedding model is there, shared words otherwise."""
    query = await ollama_client.embed(question[:400])
    vectors = await ollama_client.embed_many([c[:1500] for c in candidates]) if query else None
    if query and vectors:
        return [_cos(query, v) for v in vectors]
    q = _words(question)
    return [len(q & _words(c)) / (len(q) or 1) for c in candidates]


# --- the tool --------------------------------------------------------------------------

async def gather(question: str, depth: str = "quick") -> list[Source]:
    plan = DEPTH.get(depth, DEPTH["quick"])
    hits = [h for h in await search(question, n=10)
            if not any(s in (urlparse(h.url).hostname or "") for s in SKIP_SITES)]
    hits = hits[:plan["pages"]]
    if not hits:
        return []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                 event_hooks={"request": [_only_public]}) as client:
        tasks = [asyncio.create_task(read_page(client, h.url)) for h in hits]
        done, pending = await asyncio.wait(tasks, timeout=plan["seconds"])
        for t in pending:
            t.cancel()
    pages = []
    for hit, task in zip(hits, tasks):
        page = task.result() if task in done and not task.cancelled() and not task.exception() else None
        if page and len(page[2]) >= 200:
            final, title, text, date = page
            pages.append((Source(title or hit.title, final, _site(final), date or ""),
                          passages(text)[:40]))
        elif hit.snippet:   # couldn't read it: the search snippet still says something
            pages.append((Source(hit.title, hit.url, _site(hit.url)), [hit.snippet]))
    if not pages:
        return []

    flat = [(i, j, p) for i, (_, ps) in enumerate(pages) for j, p in enumerate(ps)]
    scores = await rank(question, [p for _, _, p in flat])
    by_page: dict[int, list[tuple[float, int, str]]] = {}
    for (i, j, p), s in zip(flat, scores):
        by_page.setdefault(i, []).append((s + (0.02 if j == 0 else 0.0), j, p))
    best = {i: max(s for s, _, _ in items) for i, items in by_page.items()}
    top = max(best.values())
    # Pages close to the best match; at least two when there are two, the
    # most relevant first — an off-topic page doesn't get in on search rank.
    keep = {i for i, b in best.items() if b >= top - 0.15}
    keep |= set(sorted(best, key=lambda i: -best[i])[:2])
    sources, used = [], 0
    for i, (src, _) in enumerate(pages):
        if i not in keep:
            continue    # off-topic page
        chosen = sorted(by_page[i], key=lambda x: -x[0])[:plan["per_page"]]
        for _, _, p in sorted(chosen, key=lambda x: x[1]):     # keep the page's order
            if used + len(p) > plan["budget"] and src.passages:
                break
            src.passages.append(p)
            used += len(p)
        if src.passages:
            sources.append(src)
        if used >= plan["budget"]:
            break
    return sources


def digest(question: str, sources: list[Source], instructions: bool = True) -> str:
    today = datetime.date.today().strftime("%d %B %Y")
    lines = [f"Web research for: {question} (searched {today})"]
    for n, s in enumerate(sources, 1):
        lines.append(f"\n[{n}] {s.title} — {s.site}" + (f", {s.date}" if s.date else ""))
        lines.append(s.url)
        lines.extend("> " + p.replace("\n", "\n> ") for p in s.passages)
    if not instructions:
        return "\n".join(lines)
    # Last, where the model reads it just before writing: these pages are
    # current; its own memory may be stale or about something else entirely.
    lines.append("\nAnswer from the sources above ONLY — not from memory, which may be out of "
                 "date or about something else with the same name. Put the source number "
                 "right after each fact it supports, like [1] or [2]. If they don't answer "
                 "the question, say so. Finish with a 'Sources:' list of the numbers you "
                 "cited (title — URL).")
    return "\n".join(lines)


_SOURCE_LINE = re.compile(r"^\[(\d+)\] (.+?) — [^\n]*\n(https?://\S+)", re.M)


def sources_in(output: str) -> list[tuple[int, str, str]]:
    """(number, title, url) of each source in a research() result."""
    return [(int(n), title, url) for n, title, url in _SOURCE_LINE.findall(output)]


@tool(
    name="research",
    description="Look something up on the internet: searches, reads the best pages and "
                "returns the passages that answer the question as numbered sources. Use it "
                "for anything you aren't certain of — news and current events, prices, "
                "products, people, sports, technical topics, 'what is X', comparisons, "
                "how-tos — and to gather facts BEFORE writing a document about a real "
                "topic. Answer from what it returns and cite [1], [2].",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string",
                         "description": "what to find out, as a clear search question"},
            "depth": {"type": "string", "enum": ["quick", "deep"],
                      "description": "deep reads more pages: for 'research X', reports "
                                     "and documents. quick for a single fact."},
        },
        "required": ["question"],
    },
    agent_tags=["research"],
)
async def research(question: str, depth: str = "quick") -> str:
    question = (question or "").strip()
    if not question:
        return "Error: say what to research."
    try:
        sources = await gather(question, depth)
    except httpx.HTTPError as e:
        return f"Couldn't reach the internet: {e}"
    if not sources:
        return ("Couldn't find anything readable about that on the web. Tell the user, "
                "and suggest a different way to phrase it.")
    return digest(question, sources)


# --- a researched document -----------------------------------------------------------

REPORT_SYSTEM = (
    "You write clear, well-organised reports for a busy reader. Use ONLY the sources you "
    "are given — they are current, and your own memory may be wrong or about something "
    "else with the same name. Put the source number in brackets after each fact, like [1]. "
    "Write Markdown: start with one '# ' title line, then ## section headings, short "
    "paragraphs, - bullet points, and a | table | where it helps. Don't write a Sources or "
    "References section — it is added for you.")
_THEIR_SOURCES = re.compile(r"\n#{1,6}\s*(?:Sources|References)\b.*\Z|\n\**(?:Sources|References)"
                            r"\**:?\s*\n.*\Z", re.S | re.I)


@tool(
    name="research_report",
    description="Research a topic on the internet and write it up as a Word document with "
                "its sources — for 'write a document/report about X', 'research X and send me "
                "a doc'. Does the searching, reading and writing itself; returns the file path "
                "(deliver it with send_file).",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "what the document is about"},
            "detail": {"type": "string", "enum": ["brief", "detailed"],
                       "description": "detailed (default) for 'deep explanation', reports"},
        },
        "required": ["topic"],
    },
    agent_tags=["research"],
)
async def research_report(topic: str, detail: str = "detailed") -> str:
    topic = (topic or "").strip()
    if not topic:
        return "Error: say what the document should be about."
    try:
        sources = await gather(topic, "deep")
    except httpx.HTTPError as e:
        return f"Couldn't reach the internet: {e}"
    if not sources:
        return ("Couldn't find anything readable about that on the web, so no document was "
                "made. Tell the user and suggest another way to put it.")
    length = ("about 400 words" if detail == "brief"
              else "about 900 words, in several sections, explaining it in depth")
    text = await ollama_client.chat_once([
        {"role": "system", "content": REPORT_SYSTEM},
        {"role": "user", "content": f"{digest(topic, sources, instructions=False)}\n\n"
                                    f"Write a report of {length} about: {topic}"}])
    text = _THEIR_SOURCES.sub("", text.strip()).strip()
    title = topic[:1].upper() + topic[1:]
    if text.startswith("# "):
        first, _, text = text.partition("\n")
        title = first[2:].strip() or title
    text += "\n\n## Sources\n" + "\n".join(
        f"{n}. [{s.title}]({s.url}) — {s.site}" + (f", {s.date}" if s.date else "")
        for n, s in enumerate(sources, 1))
    from .documents import create_word_document
    made = await asyncio.to_thread(create_word_document, title, text)
    return f"{made} Written from {len(sources)} web sources."


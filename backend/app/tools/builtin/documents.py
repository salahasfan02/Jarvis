"""Document tools: write Word documents, and send files to the user's phone.

create_word_document turns the Markdown the model naturally writes (headings,
lists, tables, links, code) into a real .docx in ~/Documents/Jarvis — never
overwriting anything. send_file delivers a file or folder over the channel
the user is chatting from (Telegram); at the Mac it just reveals the file.
"""
from __future__ import annotations

import asyncio
import datetime
import difflib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ... import channels
from ...config import settings
from ..base import tool

DOCS_DIR = Path.home() / "Documents" / "Jarvis"

_INLINE = re.compile(
    r"\[(?P<link>[^\]]+)\]\((?P<url>https?://[^)\s]+)\)"   # [text](url)
    r"|\*\*(?P<bold>[^*]+)\*\*"                            # **bold**
    r"|`(?P<code>[^`]+)`"                                  # `code`
    r"|(?<![\w*])\*(?P<italic>[^*\s][^*]*?)\*(?![\w*])")   # *italic*
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "document"


def _unique_path(folder: Path, stem: str) -> Path:
    path = folder / f"{stem}.docx"
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}.docx"
        n += 1
    return path


def _add_hyperlink(paragraph, url: str, text: str) -> None:
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    r_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    props.append(color)
    props.append(underline)
    run.append(props)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def _add_inline(paragraph, text: str) -> None:
    """Markdown inline formatting -> runs (bold, italic, code, links)."""
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        if m.group("link"):
            _add_hyperlink(paragraph, m.group("url"), m.group("link"))
        elif m.group("bold"):
            paragraph.add_run(m.group("bold")).bold = True
        elif m.group("code"):
            paragraph.add_run(m.group("code")).font.name = "Menlo"
        else:
            paragraph.add_run(m.group("italic")).italic = True
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def _styled(doc, style: str):
    try:
        return doc.add_paragraph(style=style)
    except KeyError:  # style missing from the template
        return doc.add_paragraph()


def _add_table(doc, rows: list[str]) -> None:
    cells = [[c.strip() for c in row.strip().strip("|").split("|")] for row in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-{2,}:?", c) for c in r if c)]
    if not cells:
        return
    width = max(len(r) for r in cells)
    table = doc.add_table(rows=len(cells), cols=width)
    try:
        table.style = "Table Grid"
    except (KeyError, ValueError):
        pass
    for i, row in enumerate(cells):
        for j in range(width):
            paragraph = table.cell(i, j).paragraphs[0]
            _add_inline(paragraph, row[j] if j < len(row) else "")
            if i == 0:
                for run in paragraph.runs:
                    run.bold = True


def markdown_to_docx(title: str, markdown: str, path: Path) -> int:
    """Write `markdown` to a .docx at `path`. Returns the word count."""
    import docx
    from docx.shared import Pt, RGBColor

    doc = docx.Document()
    doc.core_properties.title = title
    doc.core_properties.author = settings.get("assistant.name", "Jarvis")
    doc.add_heading(title, 0)
    byline = doc.add_paragraph()
    run = byline.add_run(f"Prepared by {doc.core_properties.author} · "
                         + datetime.date.today().strftime("%B %d, %Y"))
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    lines = markdown.replace("\r\n", "\n").split("\n")
    # The model often repeats the title as a top heading; don't print it twice.
    first = next((ln for ln in lines if ln.strip()), "")
    m = _HEADING.match(first.strip())
    if m and m.group(2).strip().lower() == title.strip().lower():
        lines.remove(first)

    paragraph_buf: list[str] = []

    def flush() -> None:
        if paragraph_buf:
            _add_inline(doc.add_paragraph(), " ".join(s.strip() for s in paragraph_buf))
            paragraph_buf.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            para = doc.add_paragraph()
            for k, code_line in enumerate(code):
                r = para.add_run(code_line)
                r.font.name = "Menlo"
                r.font.size = Pt(9)
                if k < len(code) - 1:
                    r.add_break()
        elif stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            _add_table(doc, rows)
            continue
        elif not stripped:
            flush()
        elif re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            flush()
        elif m := _HEADING.match(stripped):
            flush()
            doc.add_heading(m.group(2), min(len(m.group(1)), 4))
        elif m := _BULLET.match(line):
            flush()
            nested = len(m.group(1).expandtabs(4)) >= 2
            _add_inline(_styled(doc, "List Bullet 2" if nested else "List Bullet"),
                        m.group(2))
        elif m := _NUMBERED.match(line):
            flush()
            _add_inline(_styled(doc, "List Number"), m.group(1))
        elif stripped.startswith(">"):
            flush()
            _add_inline(_styled(doc, "Quote"), stripped.lstrip("> ").strip())
        else:
            paragraph_buf.append(stripped)
        i += 1
    flush()

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return len(re.findall(r"\w+", markdown))


@tool(
    name="create_word_document",
    description="Create a Word document (.docx) — reports, research write-ups, letters, "
                "notes. Write `content` in Markdown: # headings, - bullets, 1. lists, "
                "| tables |, **bold**, [links](https://...). Saved in ~/Documents/Jarvis; "
                "returns the file path (pass it to send_file to deliver it to the phone).",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "document title"},
            "content": {"type": "string",
                        "description": "full document body in Markdown (include a "
                                       "Sources section with links for research)"},
            "filename": {"type": "string", "description": "optional file name, no extension"},
        },
        "required": ["title", "content"],
    },
)
def create_word_document(title: str, content: str, filename: str = "") -> str:
    path = _unique_path(DOCS_DIR, _slug(filename or title))
    words = markdown_to_docx(title.strip() or "Document", content, path)
    return (f"Created Word document '{title}' ({words} words) at {path}. "
            "If the user wants it on their phone, call send_file with this path.")


def _name_key(name: str) -> str:
    """Compare file names the way a person would. macOS writes screenshot times
    as 23.55.30 with a narrow no-break space before AM/PM; models write 23:55:30
    with plain spaces, often without the extension."""
    return re.sub(r"[\s\u202f\u00a0]+", " ", name.lower().replace(":", ".")).strip()


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def resolve_path(path: str) -> tuple[Path | None, list[str]]:
    """The file the model meant, or (None, close-name suggestions)."""
    p = Path(path).expanduser()
    if p.exists():
        return p.resolve(), []
    folders = [p.parent] if str(p.parent) not in ("", ".") else [
        Path.home() / d for d in ("Desktop", "Downloads", "Documents")]
    want = _name_key(p.name)
    candidates: list[Path] = []
    for folder in folders:
        try:
            candidates += list(folder.iterdir())
        except OSError:
            continue
    hits = [c for c in candidates if want in (_name_key(c.name), _name_key(c.stem))]
    if len(hits) == 1:
        return hits[0].resolve(), []
    # Suggestions: names containing the guess (newest first), then near-misses.
    stem = _name_key(p.stem)
    containing = sorted((c for c in candidates if len(stem) >= 4 and stem in _name_key(c.name)),
                        key=_mtime, reverse=True)
    names = {_name_key(c.name): c.name for c in candidates}
    close = [names[k] for k in difflib.get_close_matches(want, list(names), n=5, cutoff=0.6)]
    return None, list(dict.fromkeys([c.name for c in containing] + close))[:5]


def _folder_size(folder: Path, limit: int) -> int:
    """Total size of a folder, stopping early once it passes `limit`."""
    total = 0
    for f in folder.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
            if total > limit:
                break
    return total


@tool(
    name="send_file",
    description="Send a file (or a whole folder, zipped) from this Mac to the user's phone, "
                "in the chat they're messaging from. Needs the exact path: find it first "
                "with search_files or list_directory if unsure. Max 50 MB.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "file or folder path, ~ allowed"},
            "caption": {"type": "string", "description": "optional short note shown with the file"},
        },
        "required": ["path"],
    },
    risk="confirm",          # the user sees exactly which file leaves the Mac
    agent_tags=["remote"],   # offered on phone turns (and to the all-tools planner)
)
async def send_file(path: str, caption: str = "") -> str:
    p, suggestions = await asyncio.to_thread(resolve_path, path)
    if p is None:
        hint = f" Similar names there: {', '.join(suggestions)}." if suggestions else ""
        return (f"No file or folder at {Path(path).expanduser()}.{hint} Find the exact "
                "path with search_files or list_directory, then call send_file again.")
    channel = channels.current.get()
    if channel is None:
        # Chatting at the Mac: there is no phone to send to, so show it instead.
        try:
            subprocess.run(["open", "-R", str(p)], timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        return (f"The user is at the Mac, so nothing was sent — {p} was revealed in "
                "Finder instead.")

    limit = channel.max_file_bytes
    if p.is_dir():
        if await asyncio.to_thread(_folder_size, p, limit * 3) > limit * 3:
            return f"The folder {p} is too large to send (over {limit * 3 // 2**20} MB)."
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-send-"))
        try:
            archive = Path(await asyncio.to_thread(
                shutil.make_archive, str(tmp / (p.name or "folder")), "zip", str(p)))
            if archive.stat().st_size > limit:
                return (f"The zipped folder is {archive.stat().st_size // 2**20} MB — "
                        f"over the {limit // 2**20} MB limit. Send individual files instead.")
            return await channel.send_file(archive, caption or f"{p.name} (zipped folder)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    size = p.stat().st_size
    if size > limit:
        return (f"{p.name} is {size // 2**20} MB — over the {limit // 2**20} MB limit "
                f"for {channel.name}.")
    return await channel.send_file(p, caption)

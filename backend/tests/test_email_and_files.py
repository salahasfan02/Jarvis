"""Email: send only when asked, approved every time. Files: newest first,
and forgiving about the names models write."""
import os
import time

from app.config import settings
from app.tools.base import registry
from app.tools.builtin import documents, filesystem, macos


def test_send_email_always_asks_even_if_always_allowed(monkeypatch):
    tool = registry.get("send_email")
    monkeypatch.setitem(settings._data["permissions"], "send_email", "always")
    assert tool.needs_confirmation() and tool.always_ask and tool.risk == "confirm"


def test_draft_email_needs_no_approval_and_never_sends(monkeypatch):
    scripts = []
    monkeypatch.setattr(macos, "_osascript", lambda s, timeout=30: scripts.append(s) or "ok")
    assert not registry.get("draft_email").needs_confirmation()
    out = macos.draft_email("sam@example.com", "Plan", "Hi Sam")
    assert "nothing was sent" in out
    assert "save newMessage" in scripts[0] and "send newMessage" not in scripts[0]


def test_send_email_sends_with_attachments(monkeypatch, tmp_path):
    scripts = []
    monkeypatch.setattr(macos, "_osascript", lambda s, timeout=30: scripts.append(s) or "ok")
    report = tmp_path / "report.docx"
    report.write_bytes(b"docx")
    out = macos.send_email("sam@example.com, kim@example.com", 'The "plan"', "Hi!\nSalah",
                           cc="boss@example.com", attachments=[str(report)])
    assert out.startswith("Sent the email to sam@example.com, kim@example.com with 1 attachment")
    script = scripts[0]
    assert "send newMessage" in script and 'subject:"The \\"plan\\""' in script
    assert script.count("make new to recipient") == 2 and "make new cc recipient" in script
    assert f'POSIX file "{report}"' in script


def test_send_email_refuses_names_and_missing_files(monkeypatch, tmp_path):
    monkeypatch.setattr(macos, "_osascript", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not reach Mail")))
    assert "Not an email address: Mom" in macos.send_email("Mom", "Hi", "Hello")
    assert "Attachment not found" in macos.send_email("a@b.com", "Hi", "Hello",
                                                      attachments=[str(tmp_path / "x.pdf")])


def test_emails_are_signed_with_the_users_real_name(monkeypatch):
    from app.agents.registry import AGENTS
    from app.chat import service
    monkeypatch.setattr(service, "_user_full_name", lambda: "Salah Asfan")
    prompt = service._static_system_prompt(AGENTS["messaging"])
    assert "Salah Asfan" in prompt and "[Your Name]" in prompt  # told never to leave it


def _touch(path, when):
    path.write_bytes(b"x")
    os.utime(path, (when, when))


def test_listings_put_the_newest_file_first(tmp_path):
    now = time.time()
    _touch(tmp_path / "a-old.png", now - 3600)
    _touch(tmp_path / "z-new.png", now)
    out = filesystem.list_directory(str(tmp_path), sort="recent")
    lines = out.splitlines()
    assert "newest first" in lines[0] and lines[1].endswith("z-new.png")


def test_search_results_are_newest_first_with_dates(monkeypatch, tmp_path):
    now = time.time()
    old, new = tmp_path / "Screenshot 1.png", tmp_path / "Screenshot 2.png"
    _touch(old, now - 60)
    _touch(new, now)

    class Result:
        stdout = f"{old}\n{new}\n"

    monkeypatch.setattr(filesystem.subprocess, "run", lambda *a, **k: Result())
    lines = filesystem.search_files("Screenshot").splitlines()
    assert lines[0].endswith(str(new)) and lines[0][:4].isdigit()


def test_send_file_finds_macos_screenshot_names(tmp_path):
    real = tmp_path / "Screenshot 2026-10-09 at 11.55.30 PM.png"
    real.write_bytes(b"png")
    for guess in ["Screenshot 2026-10-09 at 11:55:30 PM.png",   # colons, plain space
                  "Screenshot 2026-10-09 at 11.55.30 PM"]:     # no extension
        assert documents.resolve_path(str(tmp_path / guess)) == (real.resolve(), [])
    found, suggestions = documents.resolve_path(str(tmp_path / "Screenshot.png"))
    assert found is None and suggestions == [real.name]

"""FaceTime calls: "FaceTime Salah's business number" finds the right person
AND the right number before anything rings — and the confirmation shows both."""
import asyncio
import subprocess

import pytest

from app import channels, db
from app.chat import quick
from app.chat import service as chat_service
from app.memory import people
from app.security.permissions import confirmations
from app.tools.builtin import facetime

SALAH = {"name": "Salah Asfan", "handles": [
    {"kind": "phone", "label": "mobile", "value": "+44 7700 900111"},
    {"kind": "phone", "label": "work", "value": "+44 20 7946 0222"},
    {"kind": "email", "label": "icloud", "value": "salah@icloud.com"}]}
SAM_JONES = {"name": "Sam Jones", "handles": [{"kind": "phone", "label": "iphone", "value": "07700 900444"}]}
SAM_SMITH = {"name": "Sam Smith", "handles": [{"kind": "phone", "label": "mobile", "value": "07700 900555"}]}


@pytest.fixture
def contacts(monkeypatch):
    """Fake Contacts, and every URL `open` was asked for."""
    cards = [SALAH, SAM_JONES, SAM_SMITH]
    monkeypatch.setattr(people, "contact_cards",
                        lambda q: [c for c in cards if q.lower() in c["name"].lower()])
    opened: list[str] = []
    guarded = subprocess.run   # conftest's: never really opens anything

    def run(cmd, *a, **k):
        if isinstance(cmd, list) and cmd[:1] == ["open"]:
            opened.append(cmd[1])
        return guarded(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", run)
    return opened


def test_which_number_is_read_from_how_they_said_it():
    assert facetime.parse("Salah's business number") == ("Salah", "work")
    assert facetime.parse("mum's mobile") == ("mum", "mobile")
    assert facetime.parse("Sam at work") == ("Sam", "work")
    assert facetime.parse("dad's home number") == ("dad", "home")
    assert facetime.parse("Sam's iCloud") == ("Sam", "email")
    assert facetime.parse("mum on her mobile") == ("mum", "mobile")
    assert facetime.parse("Salah on his business number") == ("Salah", "work")
    assert facetime.parse("Sam on his landline") == ("Sam", "home")
    assert facetime.parse("Steve Jobs") == ("Steve Jobs", "")      # a name, not "job"
    assert facetime.parse("the office") == ("the office", "")       # nobody left: keep it whole
    assert facetime.direct("+44 7700 900123") == "+44 7700 900123"
    assert facetime.direct("sam@icloud.com") == "sam@icloud.com"
    assert facetime.direct("Sam") == ""


def test_business_number_is_the_work_one(contacts):
    callee = facetime.resolve("Salah's business number")
    assert callee == {"name": "Salah Asfan", "handle": "+44 20 7946 0222",
                      "shown": "+44 20 7946 0222 (work)"}
    # No number named: the mobile (FaceTime reaches phones and Apple IDs best).
    assert facetime.resolve("salah")["handle"] == "+44 7700 900111"
    assert facetime.resolve("Salah's iCloud")["handle"] == "salah@icloud.com"


def test_a_missing_work_number_is_reported_not_guessed(contacts):
    said = facetime.resolve("Sam Jones's work number")
    assert isinstance(said, str)
    assert "no work" in said and "07700 900444 (iPhone)" in said and said.endswith("?")
    assert contacts == []


def test_two_people_with_that_name_means_asking_which(contacts):
    said = facetime.resolve("Sam")
    assert said == "There's more than one Sam: Sam Jones, Sam Smith. Which one should I call?"
    assert facetime.resolve("Sam Smith")["handle"] == "07700 900555"
    assert "couldn't find Bob" in facetime.resolve("Bob")


def test_saved_people_come_first_and_a_card_adds_the_label(contacts, monkeypatch):
    people.remember("Mum", relation="mum", phone="07700 900333")
    try:
        # Saved by relation only, with an unlabelled number: still her mobile.
        assert facetime.resolve("mum's mobile")["handle"] == "07700 900333"
        assert "no work" in facetime.resolve("mum's work number")
        # A saved person with a name: their Contacts card says which number is which.
        people.remember("Salah Asfan", relation="brother", phone="020 7946 0222")
        callee = facetime.resolve("my brother's business number")
        assert callee["name"] == "Salah Asfan" and callee["shown"] == "020 7946 0222 (work)"
    finally:
        people.forget("Mum")
        people.forget("Salah Asfan")


def test_call_urls():
    assert facetime.call_url("+44 7700 900123", "video") == "facetime://+447700900123"
    assert facetime.call_url("sam@icloud.com", "audio") == "facetime-audio://sam@icloud.com"
    assert facetime.call_url("(020) 7946-0222", "phone") == "tel://02079460222"
    assert "number, not an email" in facetime.resolve("sam@icloud.com", "phone")


def test_instant_commands():
    cases = {
        "FaceTime Salah's business number": ("Salah's business number", "video"),
        "Jarvis, facetime audio mum please": ("mum", "audio"),
        "video call Sam": ("Sam", "video"),
        "voice call dad": ("dad", "audio"),
        "call my landlord on facetime": ("my landlord", "video"),
        "make a facetime audio call to Salah Asfan": ("Salah Asfan", "audio"),
    }
    for text, (who, kind) in cases.items():
        a = quick.match(text)
        assert a and (a.tool, a.arguments) == ("facetime_call", {"contact": who, "kind": kind}), text
    for text in ("facetime him", "facetime", "facetime audio", "facetime mum and dad",
                 "facetime isn't working", "FaceTime keeps crashing", "video call quality is bad"):
        assert quick.match(text) is None, text
    assert quick.match("facetime Michael").arguments["contact"] == "Michael"
    assert quick.match("open facetime").tool == "open_app"


def _turn(text: str, approve: bool = True) -> list[dict]:
    conv = db.create_conversation()["id"]

    async def main():
        events = []
        async for event in chat_service.run_chat(conv, text):
            events.append(event)
            if event["type"] == "confirm_request":
                confirmations.resolve(event["id"], approve)
        return events
    return asyncio.run(main())


def test_the_confirmation_shows_who_and_which_number_then_it_calls(contacts):
    events = _turn("FaceTime Salah's business number")
    ask = next(e for e in events if e["type"] == "confirm_request")
    assert ask["tool"] == "facetime_call"
    assert ask["always_ask"] is True          # never "don't ask again" for ringing someone
    assert ask["arguments"]["who"] == "Salah Asfan"
    assert ask["arguments"]["number"] == "+44 20 7946 0222 (work)"
    assert contacts == ["facetime://+442079460222"]
    done = next(e for e in events if e["type"] == "done")
    # No Accessibility in tests: the user presses Call on macOS's own prompt.
    assert done["content"].startswith("Ready to call Salah Asfan (+44 20 7946 0222 (work))")
    assert "Press Call" in done["content"]


def test_the_number_shown_is_the_number_dialled(contacts):
    """A model can't show "Mum" in the dialog and dial something else."""
    planted = facetime._prepare({"contact": "mum", "who": "Mum", "number": "+44 7700 900123 (mobile)",
                                 "handle": "+1 900 555 0199", "kind": "phone"})
    assert "couldn't find mum" in planted          # worked out from contact, the rest ignored
    only_handle = facetime._prepare({"handle": "+1 900 555 0199", "who": "Mum"})
    assert only_handle["who"] == only_handle["handle"] == "+1 900 555 0199"
    assert only_handle["number"] == "+1 900 555 0199"


def test_no_means_no_call(contacts):
    events = _turn("video call Salah", approve=False)
    assert any(e["type"] == "confirm_request" for e in events)
    assert contacts == []
    assert next(e for e in events if e["type"] == "done")["content"] == "Okay, I won't."


def test_nobody_by_that_name_asks_without_a_dialog(contacts):
    events = _turn("facetime Bob")
    assert not any(e["type"] == "confirm_request" for e in events)
    assert "couldn't find Bob" in next(e for e in events if e["type"] == "done")["content"]
    assert contacts == []


def test_it_presses_call_when_macos_asks(contacts, monkeypatch):
    monkeypatch.setattr(facetime, "_waiting_prompt", lambda: False)
    monkeypatch.setattr(facetime, "_press_call", lambda timeout=8.0: True)
    out = facetime.facetime_call(contact="Salah", kind="audio")
    assert out == "Calling Salah Asfan (+44 7700 900111 (mobile)) — FaceTime audio call."
    assert contacts == ["facetime-audio://+447700900111"]


def test_an_earlier_prompt_on_screen_is_left_to_the_user(contacts, monkeypatch):
    pressed = []
    monkeypatch.setattr(facetime, "_waiting_prompt", lambda: True)
    monkeypatch.setattr(facetime, "_press_call", lambda timeout=8.0: pressed.append(1) or True)
    assert facetime.facetime_call(contact="Salah").startswith("Ready to call")
    assert pressed == []


def test_calls_never_start_from_the_phone_or_a_routine(contacts):
    class Phone(channels.ChannelSession):
        name = "Telegram"

    token = channels.current.set(Phone())
    try:
        assert facetime.facetime_call(contact="Salah").startswith("Not calling")
        assert facetime._prepare({"contact": "Salah"}).startswith("Not calling")
    finally:
        channels.current.reset(token)
    assert contacts == []

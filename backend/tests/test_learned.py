"""Real mistakes become test cases."""
import json

from app import db, learned


def test_a_nudged_turn_becomes_a_candidate_and_can_be_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(learned, "LEARNED_FILE", tmp_path / "learned.json")
    conv = db.create_conversation()["id"]
    learned.note_turn(conv, "open my CV", "files", [], "Which file would you like?",
                      ["asked instead of acting"])
    cand = next(c for c in learned.candidates() if c["say"] == "open my CV")
    assert cand["reason"] == "asked instead of acting"
    learned.resolve(cand["id"], ["open_file"])
    saved = json.loads((tmp_path / "learned.json").read_text())
    assert {"say": "open my CV", "learned": True, "tools": ["open_file"]} in saved
    assert all(c["say"] != "open my CV" for c in learned.candidates())


def test_thats_wrong_keeps_the_previous_request():
    conv = db.create_conversation()["id"]
    db.add_message(conv, "user", "close the github tab")
    db.add_message(conv, "assistant", "Closed the Gmail tab.",
                   meta={"agent": "automation", "tools": [{"name": "browser_close_tab",
                                                           "arguments": {"tab_index": 3}}]})
    db.add_message(conv, "user", "no that's wrong")
    db.add_message(conv, "assistant", "Sorry!")
    learned.note_turn(conv, "no that's wrong", "general", [], "Sorry!", [])
    cand = next(c for c in learned.candidates() if c["say"] == "close the github tab")
    assert cand["reason"] == "user said it was wrong"
    assert cand["calls"][0]["name"] == "browser_close_tab"


def test_ordinary_replies_are_not_complaints():
    for text in ("thats great", "no thanks", "is that wrong?", "what's wrong with my wifi"):
        assert not learned.SAYS_WRONG.search(text)
    for text in ("no, that's wrong", "that's not what I asked", "wrong file"):
        assert learned.SAYS_WRONG.search(text)

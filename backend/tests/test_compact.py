"""Long conversations stay inside the model's context."""
import asyncio

from app import db
from app.chat import compact


def _long_conversation(turns=60):
    conv = db.create_conversation()
    for i in range(turns):
        db.add_message(conv["id"], "user", f"Question {i}: " + "tell me about the boiler " * 20)
        db.add_message(conv["id"], "assistant", f"Answer {i}: " + "the boiler is fine " * 30)
    return conv["id"]


def test_long_history_is_trimmed_to_the_budget_keeping_the_newest():
    cid = _long_conversation()
    history = db.get_messages(cid)
    assert compact._tokens(history) > compact.budget()
    fitted = compact.fit(db.get_conversation(cid), history)
    assert compact._tokens(fitted) <= compact.budget()
    assert fitted[-1] == history[-1] and fitted[0]["role"] == "user"


def test_summary_replaces_older_turns(monkeypatch):
    cid = _long_conversation()
    from app.llm import ollama_client

    async def chat_once(messages, **kw):
        assert "Question 0" in messages[0]["content"]   # the oldest turns are folded in
        return "The user asked repeatedly about the boiler; it is fine."
    monkeypatch.setattr(ollama_client, "chat_once", chat_once)
    asyncio.run(compact._summarize(cid))
    conv = db.get_conversation(cid)
    assert conv["summary_upto"] > 0 and "boiler" in conv["summary"]
    fitted = compact.fit(conv, db.get_messages(cid))
    assert fitted[0]["content"].startswith("[Earlier in this conversation — summary]")
    assert compact._tokens(fitted) <= compact.budget()


def test_short_conversations_are_untouched():
    conv = db.create_conversation()
    db.add_message(conv["id"], "user", "hi")
    history = db.get_messages(conv["id"])
    assert compact.fit(db.get_conversation(conv["id"]), history) == history

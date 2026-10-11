"""Tool calls the model wrote as text, full file listings, and click matching."""
from types import SimpleNamespace

from app.chat import service
from app.tools.builtin import screen_click

OFFERED = [SimpleNamespace(name="browser_close_tab"), SimpleNamespace(name="list_directory")]


def test_tool_call_written_as_text_is_recovered():
    # Seen live: "Jarvis close the github" streamed this instead of calling the tool.
    text = 'CloseOperation{"name": "browser_close_tab", "arguments": {"tab_index": 2}}'
    call = service.text_tool_call(text, OFFERED)
    assert call == {"function": {"name": "browser_close_tab", "arguments": {"tab_index": 2}}}


def test_tool_call_inside_tags_with_string_arguments():
    text = '<tool_call>{"name": "list_directory", "arguments": "{\\"path\\": \\"~/Desktop\\"}"}</tool_call>'
    call = service.text_tool_call(text, OFFERED)
    assert call["function"]["arguments"] == {"path": "~/Desktop"}


def test_normal_replies_are_left_alone():
    assert service.text_tool_call("I closed the tab for you.", OFFERED) is None
    # a tool the agent wasn't offered is never run
    assert service.text_tool_call('{"name": "trash_file", "arguments": {}}', OFFERED) is None
    # a long explanation that merely contains JSON is an answer, not a call
    essay = "Here is how a call looks: " + '{"name": "list_directory", "arguments": {}}' + " x" * 100
    assert service.text_tool_call(essay, OFFERED) is None


def test_full_listing_is_shown_and_model_gets_an_excerpt():
    names = [f"file{i}.pdf" for i in range(236)]
    output = "/Users/me/Desktop (236 items):\n" + "\n".join(names)
    block, excerpt = service.listing_for_display("list_directory", output)
    assert all(n in block for n in names)              # the user sees every item
    assert "file200.pdf" not in excerpt                # the model doesn't retype them
    assert "more lines" in excerpt and "Do NOT retype" in excerpt
    assert service.listing_for_display("read_file", output) is None


def test_click_matching_prefers_the_exact_label():
    exact = screen_click._score("Sign in", "sign in")
    inside_button = screen_click._score("Sign in with Google", "sign in")
    inside_prose = screen_click._score("Please sign in to continue reading this article", "sign in")
    assert exact > inside_button > inside_prose > 0
    assert screen_click._score("Sing in", "sign in") > 0         # OCR slip
    assert screen_click._score("Subscribe", "sign in") == 0


def test_people_are_resolved_to_email_addresses(monkeypatch):
    from app.memory import people
    from app.tools.builtin import macos
    monkeypatch.setattr(people, "from_contacts", lambda q: [])
    people.remember("Tom Reed", relation="landlord", email="tom@example.com")
    assert people.resolve_email("my landlord") == ("tom@example.com", [])
    assert people.resolve_email("Tom")[0] == "tom@example.com"
    to, cc, files, err = macos._email_parts("my landlord", "", None)
    assert (to, err) == (["tom@example.com"], "")
    to, cc, files, err = macos._email_parts("Nobody Known", "", None)
    assert "Not an email address" in err

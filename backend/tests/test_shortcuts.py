from app.tools.builtin import shortcuts


def test_shortcut_names_match_loosely():
    names = ["Movie Time", "Lights Off", "Lights On", "Work Focus"]
    assert shortcuts._match("movie time", names) == ("Movie Time", [])
    assert shortcuts._match("work", names) == ("Work Focus", [])
    match, options = shortcuts._match("lights", names)
    assert match is None and set(options) == {"Lights Off", "Lights On"}

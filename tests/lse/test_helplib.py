"""The VMS-style help library: HELP PASCAL and its topics."""

import pytest

from lse import helplib
from lse.helplib import HelpOverlay
from lse.testing import EditorHarness

SAMPLE = """! comment
1 PASCAL
 Pascal text.
2 IF
 IF chooses. More words.
3 Example
   IF x THEN y
2 INPUT
 Reading.
2 LOOPS
 Loops repeat.
3 WHILE
 While text.
3 REPEAT
 Repeat text.
"""

PLAN_TOPICS = ["PROGRAM", "VAR", "TYPES", "WRITELN", "READLN", "IF", "LOOPS", "PROCEDURES",
               "COMPILE-LINK-RUN"]


def test_parse_levels_and_text():
    root = helplib.parse(SAMPLE)
    pascal = root.children[0]
    assert pascal.name == "PASCAL" and pascal.text == ["Pascal text."]
    assert [c.name for c in pascal.children] == ["IF", "INPUT", "LOOPS"]
    if_ = pascal.children[0]
    assert if_.summary == "IF chooses."
    assert if_.children[0].text == ["  IF x THEN y"]
    assert if_.children[0].path == ["PASCAL", "IF", "EXAMPLE"]


def test_find_with_vms_abbreviations():
    root = helplib.parse(SAMPLE)
    topic, missing, amb = root.find(["PAS", "LOO", "W"])
    assert topic.path == ["PASCAL", "LOOPS", "WHILE"] and not missing
    topic, missing, amb = root.find(["PASCAL", "I"])
    assert topic.name == "PASCAL" and missing == ["I"] and [t.name for t in amb] == ["IF", "INPUT"]
    topic, missing, amb = root.find(["PASCAL", "NOPE"])
    assert missing == ["NOPE"] and not amb


def test_the_library_has_the_plan_topics_with_examples():
    root = helplib.load("pascal")
    pascal, _ = root.child("PASCAL")
    names = [c.name for c in pascal.children]
    for topic in PLAN_TOPICS:
        assert topic in names
        t, _ = pascal.child(topic)
        text = "\n".join(line for n in [t, *t.children] for line in n.text)
        assert len(t.text) >= 3, topic
        assert any(line.startswith("  ") and line.strip() for line in text.split("\n")), topic
    loops, _ = pascal.child("LOOPS")
    assert [c.name for c in loops.children] == ["WHILE", "REPEAT", "FOR"]
    for line in (l for t in pascal.children for l in t.text):
        assert len(line) <= 76, line


@pytest.fixture
def h(tmp_path):
    api = pytest.importorskip("pascal.api")
    return EditorHarness(tmp_path, app=True, api=api)


def test_help_pascal_opens_the_viewer(h):
    h.command("HELP PASCAL")
    assert isinstance(h.overlay, HelpOverlay)
    text = h.screen.text()
    assert "[ HELP PASCAL ]" in text
    assert "Additional information available" in text
    assert "> PROGRAM" in text
    assert h.next_line.startswith("Up/Down picks a topic")


def test_navigate_into_a_subtopic_and_back(h):
    h.command("HELP PASCAL")
    h.feed("L")  # jumps to LOOPS
    assert h.overlay.topic.children[h.overlay.index].name == "LOOPS"
    h.press("Enter")
    assert "[ HELP PASCAL LOOPS ]" in h.screen.text()
    h.feed("<Down><Enter>")
    assert h.overlay.topic.path == ["PASCAL", "LOOPS", "REPEAT"]
    assert "UNTIL guess = secret" in h.screen.text()
    h.press("Backspace")
    assert h.overlay.topic.path == ["PASCAL", "LOOPS"]
    assert h.overlay.topic.children[h.overlay.index].name == "REPEAT"
    h.press("Esc")
    assert h.overlay is None


def test_help_goes_straight_to_a_topic(h):
    h.command("HELP PASCAL IF")
    assert h.overlay.topic.path == ["PASCAL", "IF"]
    assert "ELSE IF guess > secret THEN" in h.screen.text()
    h.press("Esc")
    h.command("HELP PAS COMP LINK")
    assert h.overlay.topic.path == ["PASCAL", "COMPILE-LINK-RUN", "LINK"]


def test_unknown_topic_says_so_and_shows_the_nearest(h):
    h.command("HELP PASCAL GOTO")
    assert h.overlay.topic.path == ["PASCAL"]
    assert "Sorry, there is no help on PASCAL GOTO" in h.screen.text()


def test_messages_come_from_the_toolchain_catalog(h):
    h.command("HELP PASCAL MESSAGES SEMIEXP")
    text = h.screen.text()
    assert h.overlay.topic.path == ["PASCAL", "MESSAGES", "SEMIEXP"]
    assert "%PASCAL-E-SEMIEXP" in text and "Hint:" in text
    root = h.editor.help_library
    messages, _ = root.find(["PASCAL", "MESSAGES"])[0], None
    assert len(messages.children) >= 40


def test_help_topics_complete_on_the_command_line(h):
    h.press("C-p")
    h.type("HELP PA").press("Tab")
    assert h.command_line == "LSE> HELP PASCAL"

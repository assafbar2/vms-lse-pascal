"""WRITELN typed by hand without brackets, during the tutorial."""

import pytest
from lse_helpers import GUESS_SEED, TUTORIAL_KEYS, follow_tutorial

from lse.testing import EditorHarness

api = pytest.importorskip("pascal.api")
KEYS = dict((step, keys) for step, keys, _ in TUTORIAL_KEYS)

STUCK_ON_LESSON_2 = """PROGRAM Guess(INPUT, OUTPUT);
BEGIN
  WRITELN 'hi'
END.
"""
FIX = "Line 3: type ( after WRITELN and ) at the end, so it reads WRITELN('hi')"
NOTICE = ("Line 3 should read  WRITELN('hi')  -- WRITELN needs brackets around what it prints: "
          "type ( right after WRITELN and ) at the end.")


def tutorial(tmp_path):
    return EditorHarness(tmp_path, api=api, args=["--seed", str(GUESS_SEED)], size=(24, 80))


def lesson_text(h):
    return " ".join(" ".join(h.tutor.lesson_buffer.lines).split())


def test_the_stuck_program_gets_a_precise_next_line(tmp_path):
    h = tutorial(tmp_path)
    follow_tutorial(h, upto="say")
    h.feed("<Up><End><Enter>WRITELN 'hi'")
    assert h.text + "\n" == STUCK_ON_LESSON_2
    assert h.next_line == FIX
    assert lesson_text(h).startswith(" ".join(NOTICE.split()))
    assert "type WRITELN and press Tab" not in h.next_line


def test_the_same_program_opened_from_disk(tmp_path):
    (tmp_path / "GUESS.PAS").write_text(STUCK_ON_LESSON_2)
    (tmp_path / "GUESS.TUT").write_text("LESSON GUESS\nSTEP 2 say\n")
    h = EditorHarness(tmp_path, api=api, args=[], size=(24, 80))
    assert h.tutor.index == 1
    assert h.next_line == FIX
    h.press("F5")
    assert "%PASCAL-E-NOPARENS, WRITELN needs brackets around what it prints" in h.message
    assert "Hint: Write WRITELN('hi') instead." in h.message
    assert h.next_line == FIX  # still the exact fix, not "F8 goes to the mistake"


def test_following_the_advice_fixes_it(tmp_path):
    h = tutorial(tmp_path)
    follow_tutorial(h, upto="say")
    h.feed("<Up><End><Enter>WRITELN 'I am thinking of a number from 1 to 100.'")
    assert h.tutor.next_text() == ("Line 3: type ( after WRITELN and ) at the end, so it reads "
                                   "WRITELN('I am thinking of a number from 1 to 100.')")
    assert h.next_line.startswith("Line 3: type ( after WRITELN and ) at the end")
    h.feed("<Home>" + "<Right>" * 7 + "(<End>)")
    assert h.lines[2] == "  WRITELN( 'I am thinking of a number from 1 to 100.')"
    assert h.tutor.slip is None
    assert h.next_line == "Press F5 to compile, link and run it"
    assert lesson_text(h).startswith("Statements go between BEGIN and END.")
    h.press("F5")
    assert h.tutor.step.id == "mistake"


def test_a_semicolon_after_it_keeps_its_place(tmp_path):
    h = tutorial(tmp_path)
    follow_tutorial(h, upto="ask")
    h.feed("<Down><End>;<Enter>WRITE 'Your guess? ';")
    assert h.tutor.next_text() == ("Line 8: type ( after WRITE and ) before the ;, so it reads "
                                   "WRITE('Your guess? ');")


def test_readln_without_brackets(tmp_path):
    h = tutorial(tmp_path)
    follow_tutorial(h, upto="ask")
    h.feed("<Down><End>;<Enter>READLN guess")
    assert h.next_line == "Line 8: type ( after READLN and ) at the end, so it reads READLN(guess)"
    assert "READLN needs brackets around the variables it reads into" in lesson_text(h)


def test_not_pointed_out_in_the_step_about_making_mistakes(tmp_path):
    h = tutorial(tmp_path)
    follow_tutorial(h, upto="mistake")
    buf = h.buffer
    with buf.change():
        buf.replace_line(2, "  WRITELN 'I am thinking of a number from 1 to 100.'")
    h.tutor.update()
    assert h.tutor.status.done[0]  # it counts as the mistake the step asks for
    assert h.tutor.slip is None
    assert not h.next_line.startswith("Line 3: put (")


def test_the_lesson_still_fits_with_the_notice(tmp_path):
    h = tutorial(tmp_path)
    follow_tutorial(h, upto="say")
    h.feed("<Up><End><Enter>WRITELN 'I am thinking of a number from 1 to 100.'")
    win = h.tutor.window
    assert win.top == 0
    assert len(h.tutor.lesson_buffer.lines) <= win.fixed_height - 2

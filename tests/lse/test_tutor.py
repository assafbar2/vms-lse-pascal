"""The tutor engine: lesson window, checks, hints, robustness, saved progress."""

import os

import pytest
from lse_helpers import GUESS_SEED, follow_tutorial

from lse.testing import EditorHarness
from lse.tutor import IDLE_NUDGE_SECONDS, PreviewOverlay, pattern_summary

api = pytest.importorskip("pascal.api")


def tutorial(tmp_path, *, args=None, size=(24, 80)):
    return EditorHarness(tmp_path, api=api, size=size,
                         args=["--seed", str(GUESS_SEED)] if args is None else args)


@pytest.fixture
def h(tmp_path):
    return tutorial(tmp_path)


def lesson_text(h):
    return "\n".join(h.lesson)


# ----------------------------------------------------------------------------
# The lesson window can't be lost
# ----------------------------------------------------------------------------


def test_lesson_window_is_a_bordered_pane_under_the_program(h):
    assert len(h.editor.windows) == 2
    code, lesson = h.editor.windows
    assert code.buffer.name == "GUESS.PAS" and h.editor.window is code
    assert lesson.border and not lesson.show_status
    assert lesson.title == "Lesson 1 of 10: Welcome: your first program"
    assert "DO THIS:  ==> 1. Press Tab to open the menu" in lesson_text(h)
    assert h.screen.find("[ Lesson 1 of 10: Welcome: your first program ]") is not None


def test_ctrl_l_hides_and_shows_and_the_status_line_remembers(h):
    h.press("C-l")
    assert h.lesson == [] and len(h.editor.windows) == 1
    assert "[ Lesson 1/10 ^L ]" in h.status
    assert "lesson hidden" in h.message
    assert h.next_line.startswith("Press Tab")  # the NEXT line still guides
    h.press("C-l")
    assert h.lesson and "Lesson 1/10" not in h.status


def test_one_window_hides_it_and_tutorial_brings_it_back(h):
    h.command("ONE WINDOW")
    assert h.lesson == [] and "Lesson 1/10" in h.status
    h.command("TUTORIAL")
    assert h.lesson and h.editor.buffer.name == "GUESS.PAS"


def test_review_borrows_the_lesson_window_and_gives_it_back(h):
    follow_tutorial(h, upto="mistake")
    h.feed("<C-Home><End><Backspace><F7>")
    h.command("REVIEW")
    names = [w.buffer.name for w in h.editor.windows]
    assert names == ["GUESS.PAS", "$REVIEW"]
    review = h.editor.windows[1]
    assert not review.border and review.show_status and review.fixed_height
    assert h.next_line.startswith("Enter goes to the message")
    h.press("Esc")
    assert [w.buffer.name for w in h.editor.windows] == ["GUESS.PAS", "$LESSON"]
    assert h.lesson and h.editor.window.buffer.name == "GUESS.PAS"


def test_ctrl_w_into_the_lesson_says_how_to_get_back(h):
    h.press("C-w")
    assert h.editor.buffer.name == "$LESSON"
    assert h.next_line == "The lesson; Up/Down scroll it. Ctrl-W goes back to GUESS.PAS"
    assert h.key_bar.startswith("^W Back to code")
    h.type("x")
    assert "read-only" in h.message
    h.press("C-w")
    assert h.editor.buffer.name == "GUESS.PAS"


def test_lesson_window_shows_another_buffer_then_comes_back(h):
    h.press("C-w")
    h.command("GOTO BUFFER GUESS.PAS")
    assert all(w.buffer.name == "GUESS.PAS" for w in h.editor.windows)
    assert "Lesson 1/10 ^L" in h.status
    h.press("C-l")
    assert h.lesson
    assert sorted(w.buffer.name for w in h.editor.windows) == ["$LESSON", "GUESS.PAS"]


def test_lesson_follows_the_current_item_on_a_small_screen(tmp_path):
    h = tutorial(tmp_path, size=(16, 60))
    follow_tutorial(h, upto="variables")
    h.feed("<C-Home><End><Enter>VAR<Tab>secret, guess, tries<Tab><Tab><Enter>")
    assert any(line.lstrip("│ ").startswith(("==> 4.", "DO THIS:  ==> 4."))
               or "==> 4." in line for line in h.lesson)


# ----------------------------------------------------------------------------
# Checking, hints, stuck
# ----------------------------------------------------------------------------


def test_items_tick_off_as_you_go(h):
    h.feed("<Tab><Enter>")
    assert "[x] 1. Press Tab" in lesson_text(h)
    assert "==> 2. Type Guess" in lesson_text(h)
    assert h.next_line == "Type Guess over %{program_name}% and press Tab"


def test_f2_says_what_is_missing(h):
    h.feed("<Tab><Enter>Guess<Tab>")
    h.press("F2")
    assert "%LSE-W-NOTYET, 2 of 4 done. Not yet: 2 placeholders still to fill in" in \
        " ".join(h.message.split())
    assert "NEXT: Ctrl-K erases %[declarations]%... if it is not needed (2 left)" in \
        " ".join(h.message.split())


def test_idle_minute_suggests_a_hint(h):
    assert not h.tutor.stuck
    h.idle(IDLE_NUDGE_SECONDS - 1)
    assert not h.next_line.startswith("Stuck?")
    h.idle(2)
    assert h.next_line.startswith("Stuck? Press F4 for a hint. Press Tab")
    assert h.screen.role_at(h.screen.regions["next"][0], 6) == "next_stuck"
    h.press("F4")
    assert not h.next_line.startswith("Stuck?")


def test_progress_resets_the_nudge(h):
    h.idle(IDLE_NUDGE_SECONDS - 10)
    h.feed("<Tab><Enter>")
    h.idle(20)
    assert not h.tutor.stuck


def test_two_failed_compiles_suggest_a_hint(h):
    follow_tutorial(h, upto="variables")
    h.feed("<C-Home><End><Enter>VAR<Tab>")
    h.press("F7")
    assert not h.next_line.startswith("Stuck?")
    h.press("F7")
    assert h.next_line.startswith("Stuck? Press F4 for a hint.")


def test_hints_escalate_then_show_me(h):
    follow_tutorial(h, upto="say")
    h.press("F4")
    assert h.message.startswith("Hint 1 of 3: WRITELN(...) prints")
    assert "Hint 1 of 3" in lesson_text(h)
    h.press("F4")
    assert h.message.startswith("Hint 2 of 3: At the end of BEGIN")
    h.press("F4")
    assert isinstance(h.overlay, PreviewOverlay)
    text = h.screen.text()
    assert "+   WRITELN('I am thinking of a number from 1 to 100.')" in text
    assert h.next_line.startswith("Enter puts this into your program")
    assert "Enter puts this into your program.  Esc keeps yours." in text
    h.press("Enter")
    assert "  WRITELN('I am thinking of a number from 1 to 100.')" in h.lines
    assert h.next_line == "Press F5 to compile, link and run it"


def test_show_me_when_nothing_is_left_to_type(h):
    follow_tutorial(h, upto="say")
    h.command("SHOW ME")
    h.press("Enter")
    h.command("SHOW ME")
    assert h.overlay is None
    assert "already has everything this step needs" in " ".join(h.message.split())


def test_mistakes_elsewhere_are_pointed_out(h):
    follow_tutorial(h, upto="secret")
    h.feed("<End><Enter>RANDOMIZE<Enter>secret := RANDOM(100) + 1;")
    assert h.next_line.startswith('Line 5: ";" expected. F7, then F8 jumps to it') or \
        h.next_line.startswith("Line 6:")


def test_editing_another_pascal_file_points_back(h):
    h.write_file("OTHER.PAS", "PROGRAM Other;\nBEGIN\nEND.\n")
    h.command("GOTO FILE OTHER.PAS")
    assert h.next_line.startswith("The lesson is about GUESS.PAS: Ctrl-O, type GUESS.PAS")


def test_what_now_describes_the_lesson(h):
    h.command("WHAT NOW")
    text = " ".join(h.screen.text().replace("│", " ").split())
    assert "You are on step 1 of 10 of the tutorial: Welcome: your first program." in text


# ----------------------------------------------------------------------------
# Earlier steps are checked again
# ----------------------------------------------------------------------------


def test_deleting_the_var_line_is_noticed_and_can_be_put_back(h):
    follow_tutorial(h, upto="secret")
    assert h.lines[1:3] == ["VAR", "  secret, guess, tries : INTEGER;"]
    h.feed("<C-Home><Down>")
    h.command("DELETE LINE")
    h.command("DELETE LINE")
    assert h.next_line.startswith("Ctrl-Z undoes, F4 puts it back: part of step 4 is gone")
    h.press("F2")
    assert "%LSE-W-UNDONE, something from step 4 is gone" in h.message
    h.press("F4")
    assert isinstance(h.overlay, PreviewOverlay)
    assert "Put back what step 4 made" in h.screen.text()
    assert "+   secret, guess, tries : INTEGER;" in h.screen.text()
    h.press("Enter")
    assert h.lines[1:3] == ["VAR", "  secret, guess, tries : INTEGER;"]
    assert h.tutor.regression is None
    assert h.next_line.startswith("End of the BEGIN line")


def test_ctrl_z_also_repairs_it(h):
    follow_tutorial(h, upto="secret")
    h.feed("<C-Home><Down>")
    h.command("DELETE LINE")
    h.command("DELETE LINE")
    assert h.tutor.regression is not None
    h.press("C-z")
    assert h.tutor.regression is None and h.next_line.startswith("Line ")
    h.press("C-z")
    assert h.tutor.regression is None and h.next_line.startswith("End of the BEGIN line")


def test_regressions_are_not_reported_while_the_program_is_broken(h):
    follow_tutorial(h, upto="ask")
    h.feed("<Down><End>;<Enter>REPEA")
    assert h.tutor.regression is None


def test_pattern_summary_reads_like_pascal():
    assert pattern_summary("IF guess < secret THEN %{a}% ELSE WRITELN(%{text}%...)") == \
        "IF guess < secret THEN ... ELSE WRITELN(...)"


# ----------------------------------------------------------------------------
# Progress, TUTORIAL commands
# ----------------------------------------------------------------------------


def test_progress_is_saved_and_resumed(tmp_path):
    h = tutorial(tmp_path)
    follow_tutorial(h, upto="mistake")
    h.feed("<C-Home><End><Backspace><F7>")
    h.press("C-q")
    h.press("y")
    assert h.editor.quit_requested
    tut = h.file("GUESS.TUT")
    assert "STEP 3 mistake" in tut and "LATCH COMPILE_FAILED" in tut

    again = tutorial(tmp_path, args=[])
    t = again.tutor
    assert t.active and t.index == 2
    assert "welcome back: step 3 of 10" in again.message
    assert t.status.done[:2] == [True, True]
    assert again.next_line == "Press F8 to jump to the error"


def test_tutorial_off_and_on(h):
    follow_tutorial(h, upto="say")
    h.command("TUTORIAL OFF")
    assert h.lesson == [] and not h.tutor.active
    assert "tutorial paused at step 2" in h.message
    assert h.next_line.startswith("Edit and try again")
    assert "F2 Check" not in h.key_bar
    h.command("TUTORIAL")
    assert h.tutor.active and h.tutor.index == 1 and h.lesson


def test_tutorial_restart_keeps_the_old_program_as_a_version(h):
    follow_tutorial(h, upto="mistake")
    h.command("TUTORIAL RESTART")
    assert "Start the tutorial again" in h.command_line
    h.press("y")
    assert h.tutor.index == 0
    assert h.lines == ["%{compilation_unit}%"]
    versions = sorted(f for f in h.ls() if f.startswith("GUESS.PAS;"))
    assert "WRITELN('I am thinking" in h.file(versions[-2])


def test_tutorial_step_jumps_and_can_load_the_program(h):
    h.command("TUTORIAL STEP 7")
    assert "Put the program from the steps before it" in h.command_line
    h.press("y")
    assert h.tutor.index == 6
    assert "  REPEAT" in h.lines and "    READLN(guess)" in h.lines
    assert h.next_line.startswith("End of the READLN(guess) line")
    h.command("TUTORIAL STEP")
    assert h.overlay.title == "Tutorial steps"
    h.feed("<Home><Enter>")
    assert h.tutor.index == 0


def test_existing_guess_pas_offers_a_fresh_start(tmp_path):
    (tmp_path / "GUESS.PAS").write_text("PROGRAM Old;\nBEGIN\nEND.\n")
    h = tutorial(tmp_path, args=[])
    assert "already has a program in it" in h.command_line
    h.press("y")
    assert h.lines == ["%{compilation_unit}%"]
    assert "PROGRAM Old;" in h.file("GUESS.PAS;1")

    other = tmp_path / "keep"
    other.mkdir()
    (other / "GUESS.PAS").write_text("PROGRAM Old;\nBEGIN\nEND.\n")
    k = tutorial(other, args=[])
    k.press("n")
    assert k.lines[0] == "PROGRAM Old;"


def test_without_the_tutor_the_command_explains(tmp_path):
    h = EditorHarness(tmp_path, app=True, api=api)
    h.editor.tutor = None
    h.editor.tutor_problem = "guess.lesson:3: broken"
    h.command("TUTORIAL")
    assert "%LSE-E-NOTUTOR, the tutorial is not available: guess.lesson:3: broken" in h.message
    h.press("F4")
    assert "NOTUTOR" in h.message


def test_f2_and_f4_outside_the_tutorial(tmp_path):
    h = EditorHarness(tmp_path, app=True, api=api, files={"A.PAS": "x\n"})
    h.open("A.PAS")
    h.press("F2")
    assert "TUTORIAL starts it" in h.message
    h.press("F4")
    assert "TUTORIAL starts it" in h.message


def test_progress_file_survives_a_read_only_directory(tmp_path):
    h = tutorial(tmp_path)
    os.chmod(tmp_path, 0o500)
    try:
        h.tutor.save()
    finally:
        os.chmod(tmp_path, 0o700)

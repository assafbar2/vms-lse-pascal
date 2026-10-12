"""F6 Steps: skipping around the tutorial without knowing about TUTORIAL STEP."""

import pytest
from lse_helpers import GUESS_SEED

from lse import guidance
from lse.overlays import MenuOverlay
from lse.testing import EditorHarness

api = pytest.importorskip("pascal.api")


def tutorial(tmp_path, size=(24, 80)):
    return EditorHarness(tmp_path, api=api, args=["--seed", str(GUESS_SEED)], size=size)


def test_f6_steps_is_an_ordinary_key_bar_entry(tmp_path):
    h = tutorial(tmp_path)
    assert ("F6", "Steps") in guidance.key_items(h.editor)
    segs = guidance.key_bar(h.editor, 80)[0]
    at = segs.index(("F6", "keybar_key"))
    assert segs[at + 1][0].strip() == "Steps" and segs[at + 1][1] == "keybar"


def test_the_tutorial_key_bar_fits_80_columns_with_steps_and_quit(tmp_path):
    h = tutorial(tmp_path)
    bar = h.key_bar
    assert len(bar) <= 80
    assert bar == "F1 Help F2 Check F4 Hint F5 Run F6 Steps F7 Compile F8 Errors ^L Lesson ^Q Quit"
    wide = tutorial(tmp_path / "wide", size=(24, 120))
    assert wide.key_bar.startswith("F1 Help  F2 Check  F4 Hint  F5 Run  F6 Steps  F7 Compile")
    assert wide.key_bar.endswith("^Q Quit")


def test_lesson_one_says_so(tmp_path):
    h = tutorial(tmp_path)
    assert "F6 lets you skip to any step" in " ".join(" ".join(h.tutor.lesson_buffer.lines).split())


@pytest.mark.parametrize("key", ["<F6>", "<Esc>6"])
def test_f6_or_esc_6_opens_the_step_menu(tmp_path, key):
    h = tutorial(tmp_path)
    h.feed(key)
    assert isinstance(h.overlay, MenuOverlay) and h.overlay.title == "Tutorial steps"
    menu = "\n".join(h.screen.region("menu"))
    assert "1. Welcome: your first program" in menu and "now" in menu
    assert "10. You did it!" in menu
    h.press("Esc")
    assert h.overlay is None and h.tutor.index == 0


def test_skipping_ahead_offers_the_program_from_the_earlier_steps(tmp_path):
    h = tutorial(tmp_path)
    h.feed("<F6>" + "<Down>" * 6 + "<Enter>")
    assert "Jump to step 7. Put the program from the steps before it into GUESS.PAS?" in \
        h.command_line
    h.press("y")
    assert h.tutor.index == 6 and h.tutor.step.id == "decide"
    assert "    READLN(guess)" in h.lines
    assert h.next_line.startswith("End of the READLN(guess) line")


def test_going_back_needs_no_question(tmp_path):
    h = tutorial(tmp_path)
    h.feed("<F6>" + "<Down>" * 4 + "<Enter>y")
    assert h.tutor.index == 4
    h.feed("<F6><Home><Enter>")
    assert h.tutor.index == 0 and h.overlay is None


def test_f6_outside_the_tutorial_explains(tmp_path):
    h = EditorHarness(tmp_path, api=api, app=True, files={"A.PAS": "x\n"})
    h.open("A.PAS")
    h.press("F6")
    assert h.overlay is None
    assert "F6 lists the tutorial's steps while it runs" in " ".join(h.message.split())
    assert "F6" not in h.key_bar


def test_what_now_mentions_it(tmp_path):
    h = tutorial(tmp_path)
    h.command("WHAT NOW")
    assert "F6 lists the steps to skip to" in " ".join(" ".join(h.overlay.lines).split())

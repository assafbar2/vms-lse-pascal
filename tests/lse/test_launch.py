"""Getting in: what ``lse`` does at start-up, and the welcome screen."""

import os

import pytest

from lse.testing import EditorHarness
from lse.userstate import UserState
from lse.welcome import WelcomeOverlay

api = pytest.importorskip("pascal.api")


def lse(tmp_path, *args, state_dir=None):
    return EditorHarness(tmp_path, api=api, args=list(args), state_dir=state_dir)


def finished_state(tmp_path):
    state = tmp_path / "state-dir"
    UserState(str(state)).mark_tutorial_finished()
    return str(state)


def test_first_launch_goes_straight_into_the_tutorial(tmp_path):
    h = lse(tmp_path)
    assert h.tutor.active and h.tutor.index == 0
    assert h.buffer.name == "GUESS.PAS" and h.lines == ["%{compilation_unit}%"]
    assert h.lesson
    lesson = " ".join(" ".join(h.lesson).split())
    assert "Ctrl-Q quits at any time" in lesson and "TUTORIAL OFF just edits" in lesson
    assert "^Q Quit" in h.key_bar
    assert h.overlay is None


def test_after_the_tutorial_lse_shows_the_welcome_screen(tmp_path):
    h = lse(tmp_path, state_dir=finished_state(tmp_path))
    assert isinstance(h.overlay, WelcomeOverlay)
    text = h.screen.text()
    for label in ("Restart the tutorial", "New file", "Open file", "Quit"):
        assert label in text
    assert "Resume the tutorial" not in text  # no GUESS.TUT here
    assert h.next_line.startswith("Up/Down to choose, Enter to start it")
    assert h.key_bar.startswith("Up/Down Choose  Enter Start  ^Q Quit")


def test_welcome_offers_resume_when_there_is_progress(tmp_path):
    (tmp_path / "GUESS.PAS").write_text("PROGRAM Guess(INPUT, OUTPUT);\nBEGIN\nEND.\n")
    (tmp_path / "GUESS.TUT").write_text("LESSON GUESS\nSTEP 2 say\n")
    h = lse(tmp_path, state_dir=finished_state(tmp_path))
    assert "Resume the tutorial" in h.screen.text()
    assert "step 2 of 10: Say something" in h.screen.text()
    h.press("Enter")
    assert h.overlay is None and h.tutor.active and h.tutor.index == 1


def test_welcome_new_file(tmp_path):
    h = lse(tmp_path, "--no-tutorial")
    assert isinstance(h.overlay, WelcomeOverlay)
    h.press("n")
    assert "New file name [PROGRAM.PAS]:" in h.command_line
    h.type("HELLO").press("Enter")
    assert h.buffer.name == "HELLO.PAS" and h.lines == ["%{compilation_unit}%"]
    assert not h.tutor.active


def test_welcome_open_file_and_quit(tmp_path):
    (tmp_path / "PRIMES.PAS").write_text("PROGRAM Primes;\nBEGIN\nEND.\n")
    h = lse(tmp_path, "--no-tutorial")
    h.feed("<Down><Down>")
    h.press("Enter")
    assert "Open file:" in h.command_line
    h.type("PRI").press("Tab").press("Enter")
    assert h.buffer.name == "PRIMES.PAS"

    q = lse(tmp_path / "q", "--no-tutorial")
    q.press("End", "Enter")
    assert q.editor.quit_requested


def test_welcome_restart_and_escape(tmp_path):
    h = lse(tmp_path, "--no-tutorial")
    h.press("t")
    assert h.tutor.active and h.tutor.index == 0 and h.lesson
    e = lse(tmp_path / "e", "--no-tutorial")
    e.press("Esc")
    assert e.overlay is None
    assert "Ctrl-O opens a file" in e.message
    assert e.next_line.startswith("Ctrl-O opens a file")


def test_tutorial_flag_runs_it_even_when_finished(tmp_path):
    h = lse(tmp_path, "--tutorial", state_dir=finished_state(tmp_path))
    assert h.tutor.active and h.overlay is None


def test_naming_a_file_opens_it_and_offers_the_tutorial(tmp_path):
    (tmp_path / "HELLO.PAS").write_text("PROGRAM Hello(INPUT, OUTPUT);\nBEGIN\nEND.\n")
    h = lse(tmp_path, "HELLO.PAS")
    assert h.buffer.name == "HELLO.PAS" and not h.tutor.active
    assert "Ctrl-P and type TUTORIAL" in " ".join(h.message.split())
    assert h.lesson == []
    done = lse(tmp_path / "done", "HELLO.PAS", state_dir=finished_state(tmp_path))
    assert "TUTORIAL" not in done.message


def test_finishing_is_remembered_in_the_state_file(tmp_path):
    state = tmp_path / "s"
    us = UserState(str(state))
    assert not us.tutorial_finished
    us.mark_tutorial_finished()
    text = (state / "state").read_text()
    assert text.startswith("! LSE settings.") and "tutorial_finished = yes" in text
    assert UserState(str(state)).tutorial_finished


def test_state_dir_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LSE_STATE_DIR", str(tmp_path / "env"))
    assert UserState().dir == str(tmp_path / "env")
    monkeypatch.delenv("LSE_STATE_DIR")
    assert UserState().dir == os.path.join(os.path.expanduser("~"), ".lse")


def test_seed_option_and_environment(tmp_path, monkeypatch):
    assert lse(tmp_path, "--seed", "7", "X.PAS").editor.run_seed == 7
    monkeypatch.setenv("LSE_SEED", "42")
    assert lse(tmp_path / "b", "X.PAS").editor.run_seed == 42


def test_quit_is_always_one_key_away(tmp_path):
    h = lse(tmp_path)
    h.type("x")
    h.press("C-q")
    assert "unsaved changes" in h.command_line
    h.press("n")
    assert h.editor.quit_requested
    assert os.path.exists(tmp_path / "GUESS.TUT")

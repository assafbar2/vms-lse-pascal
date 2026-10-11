"""The Guess My Number lesson: the file itself, and plays through every step."""

import os

import pytest
from lse_helpers import CTRL_C, GUESS_SEED, TUTORIAL_KEYS

from lse import lesson as lessonfile
from lse import placeholders as ph
from lse.testing import EditorHarness
from lse.toolchain import Toolchain
from lse.tutor import PreviewOverlay, _Context

api = pytest.importorskip("pascal.api")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUESS = open(os.path.join(ROOT, "examples", "GUESS.PAS"), encoding="utf-8").read()
LESSON = lessonfile.load("guess")


def tutorial(tmp_path, size=(24, 80)):
    return EditorHarness(tmp_path, api=api, args=["--seed", str(GUESS_SEED)], size=size)


# ----------------------------------------------------------------------------
# The lesson file
# ----------------------------------------------------------------------------


def test_lesson_has_ten_steps_each_with_do_see_hints_and_solution():
    assert LESSON.file == "GUESS.PAS" and LESSON.title == "Guess My Number"
    assert len(LESSON.steps) == 10
    assert [s.id for s in LESSON.steps] == [k for k, _, _ in TUTORIAL_KEYS] + ["done"]
    for step in LESSON.steps[:-1]:
        assert step.title and step.text and step.items and step.see, step.id
        assert all(item.checks for item in step.items), step.id
        assert len(step.hints) >= 2, step.id
        assert step.solution, step.id
        for item in step.items:
            assert len(item.next_text) <= 74, item.next_text
    assert LESSON.steps[-1].final and LESSON.steps[-1].items


def test_every_statement_pattern_parses():
    tc = Toolchain(api)
    for step in LESSON.steps:
        for c in step.all_checks:
            if c.kind == "CONTAINS_STATEMENT":
                for pattern in c.args:
                    assert tc.parse_pattern(pattern) is not None, (step.id, pattern)


def test_every_solution_compiles_and_keeps_the_earlier_steps(tmp_path):
    h = EditorHarness(tmp_path, app=True, api=api)
    tutor = h.tutor
    for k, step in enumerate(LESSON.steps[:-1]):
        h.write_file(f"S{k}.PAS", "\n".join(step.solution) + "\n")
        result = api.compile_file(h.path(f"S{k}.PAS"))
        assert result.ok, (step.id, [d.format() for d in result.diagnostics])
        assert api.link([result.obj_path]).ok
        h.open(f"S{k}.PAS")
        ctx = _Context(h.buffer, h.buffer.text, h.buffer.state_id)
        for earlier in LESSON.steps[:k + 1]:
            for c in earlier.all_checks:
                if c.durable:
                    assert tutor.check(c, ctx).ok, (step.id, earlier.id, str(c))
    assert "\n".join(LESSON.steps[-2].solution) + "\n" == GUESS


def test_private_runs_use_the_known_secret():
    path = os.path.join(ROOT, "examples", "GUESS.PAS")
    obj = api.compile_file(path).obj_path
    exe = api.link([obj], map_file=False).exe_path
    out = api.run_image(exe, input_text="0\n101\n32\n", seed=GUESS_SEED).output
    assert "Too low!" in out and "Too high!" in out and "in 3 tries" in out


# ----------------------------------------------------------------------------
# Playing it
# ----------------------------------------------------------------------------


def test_play_through_every_step_following_do_this(tmp_path):
    h = tutorial(tmp_path)
    t = h.tutor
    assert t.active and h.lesson and "Lesson 1 of 10" in h.screen.text()
    for n, (step_id, keys, typed) in enumerate(TUTORIAL_KEYS):
        assert t.step.id == step_id
        assert f"Lesson {n + 1} of 10: {t.step.title}" in h.screen.text()
        assert h.next_line == t.step.items[0].next_text
        h.host.program_input = typed
        h.feed(keys)
        assert t.index == n + 1, (step_id, t.status, h.dump())
        assert f"step {n + 1} done" in h.message
    assert t.finished and h.tutor.ever_finished
    assert h.next_line.startswith("You finished!")
    assert h.file("GUESS.PAS") == GUESS
    assert "Correct! You got it in 6 tries." in h.host.transcripts[-1]
    assert open(os.path.join(h.state_dir, "state")).read().count("tutorial_finished = yes") == 1


def show_me(h):
    """F4 until the 'show me' preview opens, then Enter to put the answer in."""
    for _ in range(5):
        h.press("F4")
        if isinstance(h.overlay, PreviewOverlay):
            h.press("Enter")
            return
    raise AssertionError("F4 never offered 'show me'")


SHOW_ME_EVENTS = {
    "welcome": ("<F5>", ""),
    "say": ("<F5>", ""),
    "variables": ("<F7>", ""),
    "secret": ("<F5><C-o>GUESS.MAP<Enter><C-o><Enter>", ""),
    "ask": ("<F5>", f"7\n{CTRL_C}\n"),
    "decide": ("<F5>", "50\n32\n"),
    "count": ("<F7>", ""),
}


def test_play_through_every_step_with_show_me(tmp_path):
    h = tutorial(tmp_path)
    t = h.tutor
    for n, step in enumerate(LESSON.steps[:-1]):
        assert t.index == n
        if step.id == "mistake":
            h.feed("<C-Home><End><Backspace><F7><F8>")
            show_me(h)
            h.press("F7")
        elif step.id == "play":
            h.host.program_input = "50\n25\n37\n31\n34\n32\n"
            h.press("F5")
        else:
            show_me(h)
            assert ph.count(h.lines) == 0
            keys, typed = SHOW_ME_EVENTS[step.id]
            h.host.program_input = typed
            h.feed(keys)
        assert t.index == n + 1, (step.id, t.status)
    assert t.finished
    assert h.file("GUESS.PAS") == GUESS


def test_show_me_previews_before_changing_anything(tmp_path):
    h = tutorial(tmp_path)
    before = list(h.lines)
    h.press("F4")
    assert "Hint 1 of 3" in h.message and "Hint 1 of 3" in "\n".join(h.lesson)
    h.press("F4")
    assert "Hint 2 of 3" in h.message
    h.press("F4")
    assert isinstance(h.overlay, PreviewOverlay)
    assert "+ PROGRAM Guess(INPUT, OUTPUT);" in h.screen.text()
    assert h.lines == before
    h.press("Esc")
    assert h.lines == before and "kept your program" in h.message
    h.press("F4")
    h.press("Enter")
    assert h.lines == ["PROGRAM Guess(INPUT, OUTPUT);", "BEGIN", "END."]
    h.press("C-z")
    assert h.lines == before

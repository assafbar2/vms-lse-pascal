"""The tutorial is fully usable on an 80x24 terminal: the lesson never has to scroll."""

import pytest
from lse_helpers import GUESS_SEED, TUTORIAL_KEYS

from lse import lesson as lessonfile
from lse.testing import EditorHarness
from lse.tutor import CODE_ROWS, StepStatus, _every_status, render_step

api = pytest.importorskip("pascal.api")
LESSON = lessonfile.load("guess")
WIDTH = 80 - 4      # the lesson window's inside, less a margin
ROWS = 9            # the lesson window's inside on 80x24


def every_state():
    for step in LESSON.steps:
        for status in _every_status(step):
            for hint in range(len(step.hints) + 1):
                yield step, status, hint


def test_every_step_fits_in_nine_lines_at_80_columns():
    for step, status, hint in every_state():
        lines, current = render_step(step, status, hint, WIDTH)
        assert len(lines) <= ROWS, (step.id, status.current, hint, lines)
        assert all(len(line) <= 78 for line in lines), (step.id, lines)
        if current is not None:
            assert 0 <= current < len(lines)


def test_nothing_needed_is_cut_short_at_80_columns():
    for step, status, hint in every_state():
        lines, _ = render_step(step, status, hint, WIDTH, rows=ROWS)
        text = " ".join(" ".join(lines).split())

        def norm(t):
            return " ".join(t.split())

        assert lines == render_step(step, status, hint, WIDTH)[0], step.id
        if hint == 0:
            for para in step.text:
                assert norm(para) in text, (step.id, para)
        if step.see:
            assert norm(step.see) in text, step.id
        if status.current is not None:
            assert norm(step.items[status.current].text) in text, (step.id, status.current)
        if step.final:
            for item in step.items:
                assert norm(item.text) in text


def test_a_hint_takes_the_place_of_the_explanation():
    step = LESSON.steps[1]
    status = StepStatus([False, False, False], 0)
    plain, _ = render_step(step, status, 0, WIDTH)
    hinted, _ = render_step(step, status, 1, WIDTH)
    assert plain[0].startswith("The statements of a program go between BEGIN and END.")
    assert hinted[0].startswith("Hint 1 of 3: WRITELN(...)")
    assert len(hinted) <= len(plain) + 1
    assert plain[-1] == hinted[-1]  # YOU WILL SEE stays


def test_other_items_take_one_line_each():
    step = LESSON.steps[5]  # ask: five items
    lines, current = render_step(step, StepStatus([True, False, False, False, False], 1),
                                 0, WIDTH)
    assert lines[current].startswith("          ==> 2. Type WRITE")
    items = [l for l in lines if l.lstrip().startswith(("[x]", "[ ]", "==>", "DO THIS"))]
    assert len(items) == 5
    assert lines[2].endswith(" ...")  # item 1, done, on one line


def test_small_terminals_cut_the_explanation_before_scrolling():
    step = LESSON.steps[5]
    lines, current = render_step(step, StepStatus([False] * 5, 0), 0, 50, rows=8)
    assert len(lines) <= 9
    assert lines[0].endswith("...")
    assert lines[current].lstrip().startswith("DO THIS:  ==> 1.")


def test_tutorial_at_80x24_never_scrolls_the_lesson(tmp_path):
    h = EditorHarness(tmp_path, api=api, args=["--seed", str(GUESS_SEED)], size=(24, 80))
    t = h.tutor
    code, lesson = h.editor.windows
    h.screen
    assert lesson.fixed_height == ROWS + 2
    assert code.text_height == CODE_ROWS - 1  # with a one-line message
    for step_id, keys, typed in TUTORIAL_KEYS:
        h.host.program_input = typed
        for key in keys.replace(">", ">\0").split("\0"):
            if not key:
                continue
            h.feed(key)
            win = t.window
            if win is not None:
                assert win.top == 0, (step_id, key)
                assert len(t.lesson_buffer.lines) <= win.fixed_height - 2, (step_id, key)
                if not h.editor.overlays:  # a popup menu may cover part of it for a moment
                    shown = [r[1:-1].rstrip() for r in h.lesson]
                    assert shown[:len(t.lesson_buffer.lines)] == [
                        l.rstrip() for l in t.lesson_buffer.lines], (step_id, key)
    assert t.finished


def test_what_now_shows_the_whole_step(tmp_path):
    h = EditorHarness(tmp_path, api=api, args=["--seed", str(GUESS_SEED)], size=(24, 80))
    h.feed("<Tab><Enter><End><F1>")
    lines = h.overlay.lines
    assert "The lesson step in full:" in lines
    text = " ".join(" ".join(lines).split())
    for item in LESSON.steps[0].items:
        assert item.text in text

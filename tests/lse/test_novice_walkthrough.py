"""A newcomer goes through the whole tutorial, with the wrong turns real people take.

After every single key the screen must still answer "what do I do next?":
the NEXT line is there and names a key, and the lesson is either on the
screen or the status line says how to bring it back.
"""

import pytest
from lse_helpers import CTRL_C, GUESS_SEED, TUTORIAL_KEYS

from lse.guidance import ACTION_WORDS
from lse.keys import parse_keys
from lse.testing import EditorHarness
from lse.tutor import PreviewOverlay

api = pytest.importorskip("pascal.api")
KEYS = dict((step, keys) for step, keys, _ in TUTORIAL_KEYS)


class Newcomer:
    def __init__(self, tmp_path):
        self.h = EditorHarness(tmp_path, api=api, args=["--seed", str(GUESS_SEED)])
        self.keys = 0

    def check(self, what):
        h = self.h
        nxt = h.next_line
        assert nxt.strip(), f"empty NEXT after {what}\n{h.dump()}"
        assert ACTION_WORDS.search(nxt), f"NEXT is not actionable after {what}: {nxt}"
        if not h.editor.overlays:
            assert h.lesson or "Lesson " in h.status, f"lesson lost after {what}\n{h.dump()}"
            assert "Quit" in h.key_bar or "Back" in h.key_bar, h.key_bar

    def do(self, spec, typed=None):
        """Press keys one at a time, checking the guidance after each."""
        if typed is not None:
            self.h.host.program_input = typed
        for key in parse_keys(spec):
            self.h.editor.feed_key(key)
            self.h.editor.flush_keys()
            self.keys += 1
            self.check(f"{key!r} in {spec!r}")
        return self.h

    @property
    def step(self):
        return self.h.tutor.step.id


@pytest.fixture
def newcomer(tmp_path):
    return Newcomer(tmp_path)


def test_newcomer_with_wrong_turns_finishes_the_game(newcomer):
    n, h = newcomer, newcomer.h
    n.check("launch")
    assert n.step == "welcome"

    # Presses a key LSE does not use, then types instead of pressing Tab.
    n.do("<F12>")
    assert "not used" in h.message
    n.do("hello")
    assert h.next_line.startswith("Ctrl-Z undoes your typing")
    n.do("<C-z>")
    assert h.lines == ["%{compilation_unit}%"]

    # Opens the menu and backs out, then does it right.
    n.do("<Tab><Esc>")
    assert h.next_line.startswith("Press Tab to open the menu")
    n.do("<Tab><Enter>Guess")

    # Presses F5 too early: the placeholders are still there.
    n.do("<F5>")
    assert "%PASCAL-E-PLACEHOLDER" in h.message
    assert h.next_line == "Tab goes to the next placeholder (2 left); Ctrl-K erases one"
    n.do("<Tab>")
    assert h.next_line.startswith("Ctrl-K erases %[declarations]%...")
    n.do("<C-k><Tab><C-k><F5>")
    assert n.step == "say"

    # Forgets the closing quote; the compiler finds it and F8 goes there.
    n.do("<Up><End><Enter>WRITELN<Tab>'I am thinking of a number from 1 to 100.")
    n.do("<F5>")
    assert "%LSE-E-COMPERR" in h.message
    assert h.next_line.startswith("F8 goes to the mistake")
    n.do("<F8><End><Left>'<F5>")
    assert n.step == "mistake"

    # Hides the lesson by accident and gets it back.
    n.do("<C-l>")
    assert h.lesson == [] and "Lesson 3/10 ^L" in h.status
    n.do("<C-l>")
    n.do(KEYS["mistake"])
    assert n.step == "variables"

    # Wanders into the lesson window, then back.
    n.do("<C-w>")
    assert h.next_line.endswith("Ctrl-W goes back to GUESS.PAS")
    n.do("<C-w>")
    n.do(KEYS["variables"])
    assert n.step == "secret"

    # Leaves out a semicolon between two statements.
    n.do("<End><Enter>RANDOMIZE<Enter>secret := RANDOM(100) + 1;")
    n.do("<F5>")
    assert "SEMIEXP" in h.message
    assert h.next_line.startswith("F8 goes to the mistake")
    n.do("<F8><Up><End>;<F5>")
    assert h.tutor.status.current == 3
    n.do("<C-o>GUESS.MAP<Enter>")
    assert h.next_line.startswith("Find PAS$RANDOM in the map")
    n.do("<C-o><Enter>")
    assert n.step == "ask"

    # Deletes the VAR lines by mistake: the lesson notices; Ctrl-Z brings them back.
    n.do("<C-Home><Down>")
    h.command("DELETE LINE")
    h.command("DELETE LINE")
    n.check("deleting the VAR lines")
    assert "part of step 4 is gone" in h.next_line
    n.do("<C-z><C-z>")
    assert h.lines[1:3] == ["VAR", "  secret, guess, tries : INTEGER;"]
    assert h.tutor.regression is None

    # Quits by mistake, then keeps editing.
    n.do("x<C-q>")
    assert "unsaved changes" in h.command_line
    n.do("<Esc><Backspace>")
    assert not h.editor.quit_requested

    # Builds the loop; types a letter into the game, then stops it with Ctrl-C.
    n.do("<C-Home>" + "<Down>" * 5 + KEYS["ask"], typed=f"50\nabc\n42\n{CTRL_C}\n")
    run = h.host.transcripts[-1]
    assert '%PAS-W-INVSYNINT, "abc" is not a valid INTEGER' in run
    assert "Hint: Type a whole number and press RETURN." in run
    assert run.count("Your guess? ") == 4
    assert n.step == "decide"

    # Sits there for a while, takes a hint, then carries on.
    h.idle(65)
    n.check("a minute of nothing")
    assert h.next_line.startswith("Stuck? Press F4 for a hint.")
    n.do("<F4>")
    assert h.message.startswith("Hint 1 of 3")
    n.do(KEYS["decide"], typed="50\n25\n32\n")
    assert n.step == "count"

    # Uses "show me" for the counting step instead of typing it.
    for _ in range(3):
        n.do("<F4>")
    assert isinstance(h.overlay, PreviewOverlay)
    n.do("<Enter><F7>")
    assert n.step == "play"

    n.do("<F5>", typed="50\n25\n37\n31\n34\n32\n")
    assert "Correct! You got it in 6 tries." in h.host.transcripts[-1]
    assert n.step == "done" and h.tutor.finished
    assert h.next_line.startswith("You finished!")
    assert n.keys > 300


def test_newcomer_who_gets_lost_in_help_and_buffers(newcomer):
    n, h = newcomer, newcomer.h
    n.do("<F1>")  # on %{compilation_unit}%: explains the placeholder
    assert "Placeholder %{compilation_unit}%" in h.screen.text()
    n.do("<Esc><C-b>")
    assert h.overlay.title == "Buffers"
    n.do("<Esc>")
    h.command("HELP PASCAL")
    n.check("HELP PASCAL")
    n.do("<Down><Enter><Backspace><Esc>")
    h.command("GOTO BUFFER $MESSAGES")
    n.check("$MESSAGES")
    assert "Ctrl-O then Enter goes back to GUESS.PAS" in h.next_line
    n.do("<C-o><Enter>")
    assert h.buffer.name == "GUESS.PAS"
    h.command("ONE WINDOW")
    n.check("ONE WINDOW")
    n.do("<C-p>TUTORIAL<Enter>")
    assert h.lesson

"""The browser glue (web/src/lse_web.py), driven the way worker.js drives it.

A fake bridge stands in for the page: keys go in as the raw text xterm.js
sends, and the ANSI output and events come back for checking. The editor
and the Pascal toolchain are the real ones.
"""

import os
import re
import sys
from collections import deque

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for path in (ROOT, os.path.join(ROOT, "web", "src"), os.path.join(ROOT, "tests", "lse")):
    if path not in sys.path:
        sys.path.insert(0, path)

import lse_web  # noqa: E402
from lse.keys import parse_keys  # noqa: E402
from lse_helpers import CTRL_C, GUESS_SEED, TUTORIAL_KEYS  # noqa: E402

# what a VT220/xterm sends for the keys the tutorial uses
RAW_KEYS = {
    "Enter": "\r", "Tab": "\t", "Backspace": "\x7f", "Esc": "\x1b",
    "Up": "\x1b[A", "Down": "\x1b[B", "Right": "\x1b[C", "Left": "\x1b[D",
    "Home": "\x1b[H", "End": "\x1b[F", "C-Home": "\x1b[1;5H",
    "F5": "\x1b[15~", "F7": "\x1b[18~", "F8": "\x1b[19~",
}

ECHO_PAS = """PROGRAM Echo(INPUT, OUTPUT);
VAR
  n : INTEGER;
BEGIN
  WRITE('Number? ');
  READLN(n);
  WRITELN('Twice that is ', 2 * n:1)
END.
"""

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def raw(spec):
    """A key spec (``"<Up>x<F5>"``) as the characters a terminal sends."""
    out = []
    for key in parse_keys(spec):
        if key in RAW_KEYS:
            out.append(RAW_KEYS[key])
        elif key.startswith("C-") and len(key) == 3:
            out.append(chr(ord(key[2]) - 96))
        elif len(key) == 1:
            out.append(key)
        else:
            raise ValueError(f"no terminal sequence for {key!r}")
    return "".join(out)


def typed_lines(typed):
    """RUN input lines as typed keys: Ctrl-C alone, other lines end with RETURN."""
    return "".join(CTRL_C if line == CTRL_C else line + "\r" for line in typed.splitlines())


class OutOfInput(BaseException):
    """The session waited for a key that the test never typed."""


class FakeBridge:
    def __init__(self, can_block=True):
        self.can_block = can_block
        self.out = []
        self.events = []
        self.chunks = deque()
        self.interrupt = False

    def write(self, text):
        self.out.append(text)

    def event(self, kind, value):
        self.events.append((kind, value))

    def wait_input(self, timeout_ms):
        if self.chunks:
            chunks, self.chunks = list(self.chunks), deque()
            return chunks
        if timeout_ms > 0:
            raise OutOfInput
        return []

    def interrupted(self):
        was, self.interrupt = self.interrupt, False
        return was

    def take(self):
        text, self.out = "".join(self.out), []
        return text

    def kinds(self, kind):
        return [value for k, value in self.events if k == kind]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return str(tmp_path / "home")


def new_session(home, bridge=None, args=None, rows=24, cols=80):
    bridge = bridge or FakeBridge()
    session = lse_web.create(bridge, rows, cols, home, args or [], app_dir=ROOT)
    return session, bridge


def keys(session, text, elapsed=1.0):
    session.pump([[elapsed, text]])


def test_translate_char_matches_the_curses_table():
    screen = pytest.importorskip("lse.screen")
    for ch in [chr(c) for c in range(128)] + ["é", "€", "\u2500"]:
        assert lse_web.translate_char(ch) == screen.translate_key(ch), repr(ch)


def test_starts_in_the_tutorial_and_copies_the_examples(home):
    session, bridge = new_session(home)
    assert "Lesson 1 of 10" in session.screen_text()
    assert os.path.isfile(os.path.join(home, "EXAMPLES", "GUESS.PAS"))
    first = bridge.take()
    assert "\x1b[2J" in first and "\x1b[24;1H" in first
    assert "\x1b[?7l" in first
    assert ("theme", "VT220") in bridge.events


def test_redraws_only_the_rows_that_change(home):
    session, bridge = new_session(home)
    bridge.take()
    keys(session, "\t")
    update = bridge.take()
    assert "\x1b[2J" not in update
    rows = re.findall(r"\x1b\[(\d+);1H", update)
    assert 0 < len(rows) < 24
    keys(session, "\x1b[A")
    keys(session, "\x1b[B")
    assert "\x1b[2J" not in bridge.take()


def test_resize_redraws_the_whole_screen(home):
    session, bridge = new_session(home)
    bridge.take()
    session.resize(30, 100)
    update = bridge.take()
    assert "\x1b[2J" in update and "\x1b[30;1H" in update
    assert len(session.editor.render().lines()) == 30


def test_esc_and_a_digit_is_an_f_key(home):
    session, _ = new_session(home)
    keys(session, raw("<Tab><Enter>Guess<Tab><C-k><Tab><C-k>"))
    assert "Lesson 1 of 10" in session.screen_text()
    bridge = session.bridge
    keys(session, "\x1b")
    assert session.next_delay() == lse_web.ESC_WAIT_MS
    keys(session, "5\r")
    assert "Lesson 2 of 10" in session.screen_text()
    assert bridge.kinds("mode") == ["run", "edit"]


def test_plays_the_whole_tutorial_with_terminal_keys(home):
    session, bridge = new_session(home, args=["--seed", str(GUESS_SEED)])
    for n, (step_id, spec, typed) in enumerate(TUTORIAL_KEYS, 1):
        assert f"Lesson {n} of 10" in session.screen_text(), step_id
        runs = spec.count("<F5>")
        text = raw(spec).replace(RAW_KEYS["F5"], RAW_KEYS["F5"] + typed_lines(typed) + "\r")
        bridge.take()
        keys(session, text)
        assert bridge.kinds("mode") == ["run", "edit"] * runs, step_id
        transcript = ANSI.sub("", bridge.take())
        if step_id == "ask":
            assert "^C" in transcript and "Program stopped" in transcript
        if step_id == "play":
            assert "Correct! You got it in 6 tries." in transcript
        bridge.events.clear()
    assert "You finished!" in session.screen_text()


def test_run_echoes_typing_and_handles_backspace(home):
    os.makedirs(home)
    with open(os.path.join(home, "ECHO.PAS"), "w", encoding="utf-8") as f:
        f.write(ECHO_PAS)
    session, bridge = new_session(home, args=["ECHO.PAS"])
    bridge.take()
    keys(session, RAW_KEYS["F5"] + "12\x7f3\r" + "\r")
    out = bridge.take()
    assert "\x1b[?7h" in out
    assert "Number? 12\b \b3\r\n" in out
    assert "Twice that is 26\r\n" in out
    assert "Press RETURN" in out
    assert bridge.kinds("mode") == ["run", "edit"]
    assert bridge.kinds("input") == ["wait"]
    assert "\x1b[2J" in out.rsplit("Press RETURN", 1)[1]


def test_ctrl_c_stops_a_program_waiting_in_readln(home):
    os.makedirs(home)
    with open(os.path.join(home, "ECHO.PAS"), "w", encoding="utf-8") as f:
        f.write(ECHO_PAS)
    session, bridge = new_session(home, args=["ECHO.PAS"])
    bridge.take()
    keys(session, RAW_KEYS["F5"] + "4\x03" + "\r")
    out = ANSI.sub("", bridge.take())
    assert "Number? 4^C" in out
    assert "CONTROLC" in out
    assert bridge.kinds("mode") == ["run", "edit"]

    bridge.events.clear()
    bridge.interrupt = True
    keys(session, RAW_KEYS["F5"] + "\r")
    out = ANSI.sub("", bridge.take())
    assert "CONTROLC" in out
    assert bridge.kinds("mode") == ["run", "edit"]
    assert not bridge.interrupt


def test_without_shared_memory_readln_sees_the_end_of_input(home):
    os.makedirs(home)
    with open(os.path.join(home, "ECHO.PAS"), "w", encoding="utf-8") as f:
        f.write(ECHO_PAS)
    session, bridge = new_session(home, FakeBridge(can_block=False), args=["ECHO.PAS"])
    bridge.take()
    keys(session, RAW_KEYS["F5"])
    out = ANSI.sub("", bridge.take())
    assert "PASTEOF" in out
    assert "cannot pass your typing" in out
    assert session.hold and bridge.kinds("mode") == ["run"]
    keys(session, "x")
    assert session.hold and bridge.take() == ""
    keys(session, "\r")
    assert not session.hold and bridge.kinds("mode") == ["run", "edit"]
    assert "\x1b[2J" in bridge.take()
    assert "PROGRAM Echo" in session.screen_text()


def test_quit_shows_the_exit_screen_and_any_key_restarts(home):
    session, bridge = new_session(home)
    bridge.take()
    keys(session, "\x11")
    assert session.exited
    assert lse_web.EXIT_SCREEN in bridge.take()
    assert bridge.kinds("quit") == [""]
    session.resize(30, 100)
    assert lse_web.EXIT_SCREEN in bridge.take()
    assert bridge.kinds("quit") == [""]
    keys(session, "x")
    assert not session.exited
    assert "Lesson 1 of 10" in session.screen_text()
    assert "\x1b[30;1H" in bridge.take()

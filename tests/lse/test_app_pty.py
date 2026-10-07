"""End-to-end: run the real ``lse`` program in a pseudo-terminal and type at it."""

import os
import select
import struct
import subprocess
import sys
import time

import pytest

pty = pytest.importorskip("pty")
fcntl = pytest.importorskip("fcntl")
termios = pytest.importorskip("termios")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Terminal:
    def __init__(self, cwd, *args, rows=24, cols=80, extra_path=None):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        path = os.pathsep.join(filter(None, [extra_path, ROOT]))
        env = dict(os.environ, TERM="xterm", PYTHONPATH=path, ESCDELAY="25")
        self.proc = subprocess.Popen([sys.executable, "-m", "lse", *args], stdin=slave,
                                     stdout=slave, stderr=slave, cwd=cwd, env=env,
                                     start_new_session=True)
        os.close(slave)
        self.output = bytearray()

    def drain(self, quiet=0.4, limit=10.0):
        end = time.monotonic() + limit
        last = time.monotonic()
        while time.monotonic() < end:
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if ready:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.output += data
                last = time.monotonic()
            elif time.monotonic() - last > quiet:
                return

    def send(self, data: bytes, quiet=0.3):
        os.write(self.master, data)
        self.drain(quiet)

    def finish(self, timeout=10):
        try:
            self.proc.wait(timeout=timeout)
        finally:
            if self.proc.poll() is None:
                self.proc.kill()
            os.close(self.master)
        return self.proc.returncode

    @property
    def text(self):
        return self.output.decode("utf-8", "replace")


TAB, ENTER, CTRL_K, CTRL_S, CTRL_Q = b"\t", b"\r", b"\x0b", b"\x13", b"\x11"


def test_lse_edits_and_saves_versions(tmp_path):
    term = Terminal(tmp_path, "HELLO.PAS")
    term.drain(quiet=1.0)
    assert "HELLO.PAS is a new file" in term.text
    for chunk in (TAB, ENTER, b"Hello", TAB, CTRL_K, TAB, TAB, ENTER, b"'Hi'", TAB, CTRL_K,
                  CTRL_S):
        term.send(chunk)
    assert "written to file HELLO.PAS;1" in term.text
    term.send(b"\x1b[F" + ENTER + b"{ again }" + CTRL_S)  # End, new line, save again
    term.send(CTRL_Q)
    assert term.finish() == 0
    assert (tmp_path / "HELLO.PAS;1").read_text() == \
        "PROGRAM Hello(INPUT, OUTPUT);\nBEGIN\n  WRITELN('Hi')\nEND.\n"
    assert "  WRITELN('Hi')\n  { again }\nEND.\n" in (tmp_path / "HELLO.PAS;2").read_text()
    assert (tmp_path / "HELLO.PAS").read_text() == (tmp_path / "HELLO.PAS;2").read_text()


def test_lse_command_line_with_tab_completion(tmp_path):
    (tmp_path / "A.PAS").write_text("x\n")
    term = Terminal(tmp_path, "A.PAS")
    term.drain(quiet=1.0)
    term.send(b"\x10")  # Ctrl-P
    term.send(b"wri" + TAB)
    term.send(b"FILE B.PAS" + ENTER)
    term.send(b"\x10" + b"qui" + TAB + ENTER)
    assert term.finish() == 0
    assert (tmp_path / "B.PAS;1").read_text() == "x\n"


def test_quit_asks_about_unsaved_changes(tmp_path):
    term = Terminal(tmp_path, "C.PAS")
    term.drain(quiet=1.0)
    term.send(b"x" + CTRL_Q)
    assert "unsaved changes" in term.text
    term.send(b"n")
    assert term.finish() == 0
    assert not (tmp_path / "C.PAS;1").exists()


def test_esc_digit_works_as_function_key(tmp_path):
    (tmp_path / "D.TXT").write_text("plain text\n")
    term = Terminal(tmp_path, "D.TXT")
    term.drain(quiet=1.0)
    term.send(b"\x1b[F")  # End: off any word, so F1 shows the keypad
    term.send(b"\x1b" + b"1", quiet=0.6)  # Esc 1 = F1
    assert "LSE keypad" in term.text
    term.send(b"\x1b", quiet=1.5)  # lone Esc closes the help after the timeout
    term.send(CTRL_Q)
    assert term.finish() == 0


FAKE_PASCAL_API = '''
from lse.testing import FakePascalApi
_api = FakePascalApi()
parse_source = _api.parse_source
compile_file = _api.compile_file
link = _api.link
run_image = _api.run_image
get_message = _api.get_message
all_messages = _api.all_messages
'''


def test_f5_suspends_screen_and_runs_program(tmp_path):
    pkg = tmp_path / "fakepkg" / "pascal"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "api.py").write_text(FAKE_PASCAL_API)
    work = tmp_path / "work"
    work.mkdir()
    (work / "ASK.PAS").write_text("PROGRAM Ask(INPUT, OUTPUT);\nBEGIN\n  WRITE('Name? ');\n"
                                  "  READLN(n);\n  WRITELN('Hello there')\nEND.\n")
    term = Terminal(work, "ASK.PAS", extra_path=str(tmp_path / "fakepkg"))
    term.drain(quiet=1.0)
    term.send(b"\x1b[15~", quiet=1.0)  # F5
    assert "Running ASK.EXE. Type your answers and press RETURN." in term.text
    assert "Name? " in term.text
    term.send(b"Ada\r", quiet=0.8)
    assert "Hello there" in term.text
    assert "Program finished. Press RETURN to go back to LSE." in term.text
    term.send(b"\r", quiet=0.8)
    term.send(b"\x10GOTO BUFFER $OUTPUT\r")
    assert "Name? Hello there" in term.text
    term.send(CTRL_Q)
    assert term.finish() == 0
    assert (work / "ASK.EXE").exists()


def test_keytest(tmp_path):
    term = Terminal(tmp_path, "--keytest")
    term.drain(quiet=1.0)
    assert "Key test" in term.text
    term.send(b"\x1b[15~")  # F5 as xterm sends it
    term.send(b"\x1b\x1b")
    assert term.finish() == 0


def test_lse_refuses_without_terminal(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "lse", "X.PAS"], cwd=tmp_path,
                          env=dict(os.environ, PYTHONPATH=ROOT), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=20)
    assert proc.returncode == 2
    assert "needs a terminal" in proc.stderr

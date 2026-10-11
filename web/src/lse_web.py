"""LSE in a web browser: the glue between the editor and the page.

This module runs inside Pyodide in a Web Worker (see ``worker.js``). The
editor itself is unchanged: this module plays the part that ``lse.app``
and ``lse.screen`` play in a terminal.

* Keys arrive as the raw text a terminal would send (xterm.js ``onData``)
  and go through the editor's own Esc decoder, so F-keys, arrows and the
  Esc + digit fallback behave exactly as in a terminal.
* ``Session.render`` turns the editor's ``VirtualScreen`` into ANSI escape
  sequences for xterm.js, redrawing only the rows that changed.
* ``WebHost.run_program`` gives the terminal to a running Pascal program,
  the way ``CursesHost`` does: READLN blocks until the user presses
  RETURN, with echo and Backspace done here (the "cooked mode" a real
  terminal driver would provide).

The page talks to the session through a *bridge* object:

* ``bridge.write(text)``: terminal output (ANSI).
* ``bridge.event(kind, value)``: ``mode`` (``"run"``/``"edit"``),
  ``input`` (a running program waits in READLN), ``theme``,
  ``modified`` (``"1"``/``"0"``), ``bell``, ``quit``.
* ``bridge.wait_input(timeout_ms)``: raw input chunks
  ``[[elapsed_seconds, text], ...]`` typed so far, waiting up to
  ``timeout_ms`` for some (only when ``bridge.can_block``).
* ``bridge.interrupted()``: whether Ctrl-C was pressed while a program
  ran (and clear the flag).
* ``bridge.can_block``: True when the worker can wait for keys
  (SharedArrayBuffer is available). Without it, programs still run, but
  READLN sees the end of the input.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import traceback
from collections import deque
from typing import Any

from lse.app import build_editor, parse_args, start_editor
from lse.host import After, Host, ProgramFn, after_text
from lse.themes import get_theme
from lse.vscreen import BOX_TO_ASCII

IDLE_MS = 1000
ESC_WAIT_MS = 1000
FLUSH_BYTES = 4096
FLUSH_SECONDS = 0.05

# the same table as lse.screen.translate_key, which cannot be imported here
# because it needs curses
_FIXED_KEYS = {"\t": "Tab", "\n": "Enter", "\r": "Enter", "\x1b": "Esc", "\x7f": "Backspace",
               "\x08": "Backspace", "\x00": "C-Space"}

_SGR_ATTRS = {"bold": "1", "dim": "2", "underline": "4", "reverse": "7"}

NO_INPUT_NOTE = ("(This browser window cannot pass your typing to a running program, so READLN "
                 "saw the end of the input. Open the page in a normal, non-private window.)")

EXIT_SCREEN = ("LSE has exited. Your files are kept in this browser.\r\n\r\n"
               "Press any key to start LSE again.")


def translate_char(ch: str) -> str | None:
    """One character of terminal input as an editor key (None = ignore)."""
    if ch in _FIXED_KEYS:
        return _FIXED_KEYS[ch]
    code = ord(ch)
    if 1 <= code <= 26:
        return "C-" + chr(code + 96)
    if code == 31:
        return "C-_"
    if code < 32:
        return None
    return ch


def _to_py(value: Any) -> Any:
    to_py = getattr(value, "to_py", None)
    return to_py() if callable(to_py) else value


def crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


class _ProgramOutput:
    """``stdout`` for a running program: text goes to the terminal in batches."""

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.pending: list[str] = []
        self.size = 0
        self.last = time.monotonic()

    def write(self, text: str) -> int:
        self.pending.append(text)
        self.size += len(text)
        if self.size >= FLUSH_BYTES or time.monotonic() - self.last >= FLUSH_SECONDS:
            self.flush()
        return len(text)

    def flush(self) -> None:
        if self.pending:
            self.session.write(crlf("".join(self.pending)))
            self.pending = []
            self.size = 0
        self.last = time.monotonic()


class _ProgramInput:
    """``stdin`` for a running program: a line at a time, typed in the terminal."""

    def __init__(self, session: "Session", output: _ProgramOutput) -> None:
        self.session = session
        self.output = output

    def readline(self, *args: Any) -> str:
        self.output.flush()
        return self.session.read_line()


class _NoInput:
    def readline(self, *args: Any) -> str:
        return ""


class WebHost(Host):
    """Gives the terminal to a program (RUN), like ``lse.app.CursesHost``."""

    def __init__(self, session: "Session") -> None:
        self.session = session

    def run_program(self, before: str, after: After, fn: ProgramFn) -> Any:
        s = self.session
        blocking = s.can_block
        s.event("mode", "run")
        s.write("\x1b[0m\x1b[?7h\x1b[H\x1b[2J\x1b[3J" + crlf(before) + "\r\n\r\n\x1b[?25h")
        out = _ProgramOutput(s)
        stdin = _ProgramInput(s, out) if blocking else _NoInput()
        result = None
        try:
            result = fn(stdin, out)
        except KeyboardInterrupt:
            out.write("\n%LSE-W-INTERRUPTED, the program was stopped with Ctrl-C\n")
        if not blocking and s.program_read_input(result):
            out.write("\n" + NO_INPUT_NOTE + "\n")
        out.write("\n" + after_text(after, result) + "\n")
        out.flush()
        if blocking:
            s.wait_for_return()
            s.end_run()
        else:
            s.hold = True
        return result

    def bell(self) -> None:
        self.session.event("bell", "")


class Session:
    """One editor session in the page: input, rendering, RUN and restarts."""

    def __init__(self, bridge: Any, rows: int, cols: int, *, home: str,
                 args: list[str] | None = None, app_dir: str | None = None) -> None:
        self.bridge = bridge
        self.can_block = bool(getattr(bridge, "can_block", False))
        self.rows, self.cols = max(4, int(rows)), max(20, int(cols))
        self.home = home
        self.args = list(args or [])
        self.app_dir = app_dir
        self.queue: deque[tuple[str, float | None]] = deque()
        self.hold = False
        self.exited = False
        self.running = False
        self._rows: list[str] | None = None
        self._theme: str | None = None
        self._modified: bool | None = None
        self._last_key = time.monotonic()
        self.editor: Any = None
        os.makedirs(home, exist_ok=True)
        self._copy_examples()
        self.start()

    # ----- life cycle -----------------------------------------------------------

    def _copy_examples(self) -> None:
        src = os.path.join(self.app_dir, "examples") if self.app_dir else None
        dst = os.path.join(self.home, "EXAMPLES")
        if src and os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)

    def start(self) -> None:
        """Start (or restart) the editor the way ``lse`` with no file name does."""
        os.chdir(self.home)
        self.editor = build_editor(cwd=self.home, host=WebHost(self), height=self.rows,
                                   width=self.cols, state_dir=os.path.join(self.home, ".lse"))
        try:
            args = parse_args(self.args)
        except SystemExit:
            args = parse_args([])
        start_editor(self.editor, args)
        self.exited = False
        self.hold = False
        self.invalidate()
        self.render()

    def _quit(self) -> None:
        self.exited = True
        self._rows = None
        self._draw_exit_screen()
        self.event("modified", "0")
        self._modified = False
        self.event("quit", "")

    def _draw_exit_screen(self) -> None:
        self.write("\x1b[0m\x1b[?7h\x1b[H\x1b[2J\x1b[3J\x1b[?25h" + EXIT_SCREEN)

    # ----- talking to the page ------------------------------------------------

    def write(self, text: str) -> None:
        if text:
            self.bridge.write(text)

    def event(self, kind: str, value: str) -> None:
        self.bridge.event(kind, value)

    def _pull(self, timeout_ms: int = 0) -> None:
        if not self.can_block:
            return
        chunks = _to_py(self.bridge.wait_input(int(timeout_ms))) or []
        self.add_input(chunks)

    def add_input(self, chunks: Any) -> None:
        """Queue raw input: ``[[elapsed_seconds, text], ...]``."""
        for elapsed, text in _to_py(chunks) or []:
            first = True
            for ch in str(text):
                self.queue.append((ch, float(elapsed) if first and elapsed is not None else 0.0))
                first = False

    # ----- keys ---------------------------------------------------------------

    def pump(self, chunks: Any = None) -> int:
        """Handle all input typed so far; return the delay for the next ``timer`` call."""
        if chunks is not None:
            self.add_input(chunks)
        self._pull(0)
        try:
            while self.queue:
                ch, elapsed = self.queue.popleft()
                self._last_key = time.monotonic()
                if self.exited:
                    self.queue.clear()
                    self.start()
                    break
                if self.hold:
                    if ch in ("\r", "\n", "\x03"):
                        self.hold = False
                        self.end_run()
                    continue
                key = translate_char(ch)
                if key is None:
                    continue
                self.editor.feed_key(key, elapsed)
                if self.editor.quit_requested:
                    self._quit()
                    self.queue.clear()
                    break
                self._pull(0)
        except KeyboardInterrupt:
            self.clear_interrupt()
        self.render()
        return self.next_delay()

    def timer(self) -> int:
        """Called by the page after ``next_delay`` ms without input."""
        try:
            if not (self.exited or self.hold):
                ed = self.editor
                if ed.decoder.waiting:
                    ed.flush_keys()
                    if ed.quit_requested:
                        self._quit()
                else:
                    ed.idle()
        except KeyboardInterrupt:
            self.clear_interrupt()
        self.render()
        return self.next_delay()

    def next_delay(self) -> int:
        if self.editor is not None and self.editor.decoder.waiting:
            return ESC_WAIT_MS
        return IDLE_MS

    def resize(self, rows: int, cols: int) -> None:
        self.rows, self.cols = max(4, int(rows)), max(20, int(cols))
        if self.editor is not None:
            self.editor.resize(self.rows, self.cols)
        self.invalidate()
        if self.exited:
            self._draw_exit_screen()
        elif not self.hold:
            self.render()

    # ----- RUN ----------------------------------------------------------------

    def clear_interrupt(self) -> None:
        if self.can_block:
            self.bridge.interrupted()

    def _next_char(self) -> str:
        """The next typed character, waiting for one; Ctrl-C raises KeyboardInterrupt."""
        while True:
            if self.bridge.interrupted():
                raise KeyboardInterrupt
            if self.queue:
                return self.queue.popleft()[0]
            self._pull(IDLE_MS)

    def _skip_sequence(self) -> None:
        """Drop the rest of an escape sequence (arrow keys mean nothing to READLN)."""
        if not self.queue or self.queue[0][0] not in "[O":
            return
        intro = self.queue.popleft()[0]
        if intro == "O":
            if self.queue:
                self.queue.popleft()
            return
        while self.queue:
            ch = self.queue.popleft()[0]
            if 0x40 <= ord(ch) <= 0x7E:
                return

    def read_line(self) -> str:
        """READLN: a line typed with echo and Backspace; "" at end of input (Ctrl-D)."""
        line: list[str] = []
        self.event("input", "wait")
        while True:
            try:
                ch = self._next_char()
            except KeyboardInterrupt:
                self.write("^C\r\n")
                raise
            if ch in ("\r", "\n"):
                self.write("\r\n")
                return "".join(line) + "\n"
            if ch == "\x03":
                self.write("^C\r\n")
                raise KeyboardInterrupt
            if ch == "\x04":
                if not line:
                    self.write("\r\n")
                    return ""
            elif ch in ("\x7f", "\x08"):
                if line:
                    line.pop()
                    self.write("\b \b")
            elif ch == "\x15":
                self.write("\b \b" * len(line))
                line.clear()
            elif ch == "\x1b":
                self._skip_sequence()
            elif ch.isprintable():
                line.append(ch)
                self.write(ch)

    def wait_for_return(self) -> None:
        """"Press RETURN to go back to LSE." (Ctrl-C also goes back.)"""
        while True:
            try:
                ch = self._next_char()
            except KeyboardInterrupt:
                return
            if ch in ("\r", "\n", "\x03"):
                return

    def end_run(self) -> None:
        self.clear_interrupt()
        self.event("mode", "edit")
        self.invalidate()

    def program_read_input(self, result: Any) -> bool:
        error = getattr(result, "error", None)
        return getattr(error, "ident", "") == "PASTEOF"

    # ----- screen -------------------------------------------------------------

    def invalidate(self) -> None:
        self._rows = None

    def _sgr(self, theme: Any, role: str) -> str:
        fg, attrs = theme.style(role)
        color = theme.foreground[0] if fg == "normal" else theme.bright[0]
        codes = ["0"] + [_SGR_ATTRS[a] for a in sorted(attrs) if a in _SGR_ATTRS]
        codes.append(f"38;5;{color}")
        return "\x1b[" + ";".join(codes) + "m"

    def render(self) -> None:
        """Draw the editor screen, sending only the rows that changed."""
        if self.exited or self.hold or self.editor is None:
            return
        ed = self.editor
        scr = ed.render()
        theme = get_theme(ed.theme)
        if theme.name != self._theme:
            self._theme = theme.name
            self.event("theme", theme.name)
            self._rows = None
        modified = bool(ed.modified_buffers())
        if modified != self._modified:
            self._modified = modified
            self.event("modified", "1" if modified else "0")
        ascii_lines = ed.line_drawing == "ASCII"
        styles: dict[str, str] = {}
        out: list[str] = []
        prev = self._rows
        if prev is None or len(prev) != scr.height:
            out.append("\x1b[0m\x1b[?7l\x1b[?25l\x1b[H\x1b[2J")
            prev = [""] * scr.height
            full = True
        else:
            out.append("\x1b[?25l")
            full = False
        rows: list[str] = []
        for r in range(scr.height):
            parts = []
            for _col, text, role in scr.runs(r):
                sgr = styles.get(role)
                if sgr is None:
                    sgr = styles[role] = self._sgr(theme, role)
                if ascii_lines:
                    text = text.translate(BOX_TO_ASCII)
                parts.append(sgr + text)
            row = "".join(parts)
            rows.append(row)
            if full or row != prev[r]:
                out.append(f"\x1b[{r + 1};1H{row}")
        out.append("\x1b[0m")
        if scr.cursor is not None:
            cr, cc = scr.cursor
            out.append(f"\x1b[{min(cr, scr.height - 1) + 1};{min(cc, scr.width - 1) + 1}H\x1b[?25h")
        self._rows = rows
        self.write("".join(out))

    def screen_text(self) -> str:
        """The editor screen as plain text (for debugging from the console)."""
        return self.editor.render().text() if self.editor is not None else ""


def create(bridge: Any, rows: int, cols: int, home: str, args: Any = None,
           app_dir: str | None = None) -> Session:
    """Entry point for ``worker.js``."""
    try:
        return Session(bridge, rows, cols, home=home, args=list(_to_py(args) or []),
                       app_dir=app_dir)
    except Exception:
        bridge.write("\x1b[0m\x1b[H\x1b[2J" + crlf(traceback.format_exc()))
        print(traceback.format_exc(), file=sys.stderr)
        raise

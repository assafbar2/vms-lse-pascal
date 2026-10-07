"""The editor's view of the outside world while it runs.

The editor core never touches curses. When it needs the real terminal
(RUN suspends the screen so the program can talk to the user) it asks
its ``Host``. The curses app provides ``CursesHost`` (in ``lse.app``);
tests use ``HeadlessHost``, which feeds scripted input to the program
and records what it printed.
"""

from __future__ import annotations

import io
from typing import Any, Callable, TextIO, Union

ProgramFn = Callable[[TextIO, TextIO], Any]
#: the closing banner, or a function of the program's result that makes it
After = Union[str, Callable[[Any], str]]


def after_text(after: After, result: Any) -> str:
    return after(result) if callable(after) else after


class Host:
    def run_program(self, before: str, after: After, fn: ProgramFn) -> Any:
        """Give the terminal to ``fn(stdin, stdout)``; show the banners around it."""
        raise NotImplementedError

    def bell(self) -> None:
        pass


CTRL_C = "\x03"


class _ScriptedInput(io.StringIO):
    """Typed input for a headless RUN; a line starting with Ctrl-C (``\\x03``) interrupts."""

    def readline(self, *args: Any) -> str:  # type: ignore[override]
        line = super().readline(*args)
        if line.startswith(CTRL_C):
            raise KeyboardInterrupt
        return line


class HeadlessHost(Host):
    """Runs programs against scripted input and keeps a transcript.

    ``program_input`` is the text the "user" types into the program; set
    it before each RUN. A line that starts with ``\\x03`` stands for
    pressing Ctrl-C. ``transcripts`` collects one entry per run with the
    banners and the program output, as the user would have seen it.
    """

    def __init__(self, program_input: str = "") -> None:
        self.program_input = program_input
        self.transcripts: list[str] = []
        self.bells = 0

    def run_program(self, before: str, after: After, fn: ProgramFn) -> Any:
        stdin = _ScriptedInput(self.program_input)
        stdout = io.StringIO()
        try:
            result = fn(stdin, stdout)
        except KeyboardInterrupt:
            result = None
            stdout.write("\n%LSE-W-INTERRUPTED, the program was stopped with Ctrl-C\n")
        self.transcripts.append(f"{before}\n{stdout.getvalue()}{after_text(after, result)}\n")
        return result

    def bell(self) -> None:
        self.bells += 1

"""The editor's view of the outside world while it runs.

The editor core never touches curses. When it needs the real terminal
(RUN suspends the screen so the program can talk to the user) it asks
its ``Host``. The curses app provides ``CursesHost`` (in ``lse.app``);
tests use ``HeadlessHost``, which feeds scripted input to the program
and records what it printed.
"""

from __future__ import annotations

import io
from typing import Any, Callable, TextIO

ProgramFn = Callable[[TextIO, TextIO], Any]


class Host:
    def run_program(self, before: str, after: str, fn: ProgramFn) -> Any:
        """Give the terminal to ``fn(stdin, stdout)``; show the banners around it."""
        raise NotImplementedError

    def bell(self) -> None:
        pass


class HeadlessHost(Host):
    """Runs programs against scripted input and keeps a transcript.

    ``program_input`` is the text the "user" types into the program; set
    it before each RUN. ``transcripts`` collects one entry per run with
    the banners and the program output, as the user would have seen it.
    """

    def __init__(self, program_input: str = "") -> None:
        self.program_input = program_input
        self.transcripts: list[str] = []
        self.bells = 0

    def run_program(self, before: str, after: str, fn: ProgramFn) -> Any:
        stdin = io.StringIO(self.program_input)
        stdout = io.StringIO()
        result = fn(stdin, stdout)
        self.transcripts.append(f"{before}\n{stdout.getvalue()}{after}\n")
        return result

    def bell(self) -> None:
        self.bells += 1

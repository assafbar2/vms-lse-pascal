"""Headless test harness for the editor, plus a fake toolchain.

Drive the editor with key sequences and read back the virtual screen,
without a terminal::

    from lse.testing import EditorHarness

    h = EditorHarness(tmp_path)               # a directory to work in
    h.open("HELLO.PAS")                       # like `lse HELLO.PAS`
    h.feed("<Tab><Enter>Hello")               # keys: <Name> or literal text
    h.command("WRITE FILE")                   # = <C-p>WRITE FILE<Enter>
    assert h.file("HELLO.PAS;1").startswith("PROGRAM Hello")
    assert "WRITTEN" in h.message             # the message line(s)
    print(h.dump())                           # screen + state, for debugging

Key names in ``feed``: ``<Enter> <Tab> <S-Tab> <Esc> <Backspace> <Delete>
<Up> <Down> <Left> <Right> <Home> <End> <PageUp> <PageDown> <C-s> <C-k>
<C-Delete> <F1>..<F12> <S-F8>``; friendly spellings like ``<Ctrl-S>`` work
too, ``<lt>`` types ``<``, and a newline in the text is Enter. Keys go
through the same Esc decoder as the terminal, so ``<Esc>5`` is F5; a
lone Esc is released at the end of each ``feed``.

Reading the screen (all re-rendered on access):

* ``h.screen``: the ``VirtualScreen`` (``.text()``, ``.lines()``,
  ``.region(name)``, ``.find(text)``, ``.role_at(r, c)``, ``.cursor``)
* ``h.window_lines(i)``, ``h.status``, ``h.message``, ``h.command_line``
* ``h.buffer``, ``h.text``, ``h.lines``, ``h.cursor`` (row, col, 0-based)
* ``h.overlay``: the open popup/prompt, if any (``MenuOverlay`` etc.)

The toolchain is ``FakePascalApi`` unless you pass ``api=`` (for example
the real ``pascal.api`` module). RUN reads ``h.host.program_input`` as the
user's typing and records what the user saw in ``h.host.transcripts``.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any

from .commands import quote
from .editor import Editor
from .host import HeadlessHost
from .keys import normalize_key, parse_keys
from .toolchain import Toolchain


class FakeClock:
    """A clock for tests: time only moves when ``advance`` is called."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class EditorHarness:
    """Drive an editor headlessly.

    By default it is the bare editor core. With ``app=True`` it is built
    the way ``lse`` builds it (NEXT line, key bar, pipeline indicator,
    help library, tutor, welcome screen), with the per-user state in
    ``<directory>/.lse-state`` and a ``FakeClock`` in ``h.clock``. Pass
    ``args`` (the ``lse`` command-line arguments, e.g. ``[]`` or
    ``["--tutorial"]``) to run the launch flow as well.
    """

    def __init__(self, directory: str | os.PathLike | None = None, *,
                 files: dict[str, str] | None = None, size: tuple[int, int] = (24, 80),
                 api: Any = None, program_input: str = "", raise_errors: bool = True,
                 app: bool = False, args: list[str] | None = None,
                 state_dir: str | None = None) -> None:
        self.dir = str(directory) if directory is not None else tempfile.mkdtemp(prefix="lse-")
        os.makedirs(self.dir, exist_ok=True)
        for name, text in (files or {}).items():
            self.write_file(name, text)
        self.api = api if api is not None else FakePascalApi()
        self.host = HeadlessHost(program_input)
        self.clock = FakeClock()
        if app or args is not None:
            from .app import build_editor, parse_args, start_editor
            self.state_dir = state_dir or os.path.join(self.dir, ".lse-state")
            self.editor = build_editor(cwd=self.dir, host=self.host, height=size[0],
                                       width=size[1], toolchain=Toolchain(self.api),
                                       state_dir=self.state_dir, raise_errors=raise_errors)
            self.editor.clock = self.clock
            if self.editor.tutor is not None:
                self.editor.tutor.last_progress = self.clock()
            if args is not None:
                start_editor(self.editor, parse_args(list(args)))
        else:
            self.editor = Editor(cwd=self.dir, toolchain=Toolchain(self.api), host=self.host,
                                 height=size[0], width=size[1], raise_errors=raise_errors)

    # ----- input --------------------------------------------------------------

    def open(self, name: str) -> "EditorHarness":
        """Open a file as ``lse NAME`` would."""
        self.editor.execute(f"GOTO FILE {quote(name)}")
        return self

    def feed(self, spec: str) -> "EditorHarness":
        """Press keys described by ``spec`` (``"IF<Tab>x > 1<S-Tab>"``)."""
        for key in parse_keys(spec):
            self.editor.feed_key(key)
        self.editor.flush_keys()
        return self

    def press(self, *keys: str) -> "EditorHarness":
        """Press named keys (``press("C-s")``, ``press("Ctrl-Q", "n")``)."""
        for key in keys:
            self.editor.feed_key(normalize_key(key))
        self.editor.flush_keys()
        return self

    def type(self, text: str) -> "EditorHarness":
        """Type literal text (no ``<...>`` key names; newline = Enter)."""
        for ch in text:
            self.editor.feed_key("Enter" if ch == "\n" else ch)
        self.editor.flush_keys()
        return self

    def command(self, text: str) -> "EditorHarness":
        """Type a command at the ``LSE>`` prompt (Ctrl-P, the text, Enter)."""
        self.press("C-p")
        self.type(text)
        return self.press("Enter")

    def idle(self, seconds: float = 0.0) -> "EditorHarness":
        """Let ``seconds`` pass with no keys (the terminal's idle tick)."""
        self.clock.advance(seconds)
        self.editor.idle()
        return self

    # ----- output -------------------------------------------------------------

    @property
    def screen(self):
        return self.editor.render()

    def window_lines(self, index: int = 0) -> list[str]:
        return self.screen.region(f"window{index}")

    @property
    def status(self) -> str:
        return self.screen.region_text(f"status{self.editor.current_window}")

    @property
    def message(self) -> str:
        return self.screen.region_text("message")

    @property
    def command_line(self) -> str:
        return self.screen.region_text("command")

    @property
    def next_line(self) -> str:
        """The NEXT line (app mode), without the ``NEXT: `` label."""
        text = self.screen.region_text("next")
        return text[len("NEXT: "):] if text.startswith("NEXT: ") else text

    @property
    def key_bar(self) -> str:
        return self.screen.region_text("keybar")

    @property
    def tutor(self):
        return getattr(self.editor, "tutor", None)

    @property
    def lesson(self) -> list[str]:
        """The text rows of the LESSON window as shown (empty if it is not on screen)."""
        for i, w in enumerate(self.editor.windows):
            if "lesson" in w.tags:
                return self.screen.region(f"window{i}")
        return []

    @property
    def buffer(self):
        return self.editor.buffer

    @property
    def text(self) -> str:
        return self.editor.buffer.text

    @property
    def lines(self) -> list[str]:
        return list(self.editor.buffer.lines)

    @property
    def cursor(self) -> tuple[int, int]:
        return self.editor.buffer.cursor

    @property
    def overlay(self):
        return self.editor.overlays[-1] if self.editor.overlays else None

    # ----- files --------------------------------------------------------------

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def write_file(self, name: str, text: str) -> None:
        with open(self.path(name), "w", encoding="utf-8") as f:
            f.write(text)

    def file(self, name: str) -> str:
        with open(self.path(name), encoding="utf-8") as f:
            return f.read()

    def exists(self, name: str) -> bool:
        return os.path.exists(self.path(name))

    def ls(self) -> list[str]:
        return sorted(e for e in os.listdir(self.dir) if not e.startswith("."))

    # ----- debugging ----------------------------------------------------------

    def dump(self) -> str:
        """Screen (ASCII, cursor shown as a block) plus key state, for failures."""
        scr = self.screen
        lines = scr.lines(ascii=True)
        if scr.cursor is not None:
            r, c = scr.cursor
            row = lines[r].ljust(c + 1)
            lines[r] = row[:c] + "\u2588" + row[c + 1:]
        ed = self.editor
        state = (f"buffer={ed.buffer.name} cursor={ed.buffer.cursor} "
                 f"windows={len(ed.windows)} overlays={[type(o).__name__ for o in ed.overlays]}")
        return "\n".join(["+" + "-" * scr.width + "+"] + [f"|{l.ljust(scr.width)}|" for l in lines]
                         + ["+" + "-" * scr.width + "+", state])


# ============================================================================
# A fake implementation of the pascal.api contract
# ============================================================================


@dataclass
class Diagnostic:
    file: str | None
    line: int | None
    column: int | None
    severity: str
    facility: str
    ident: str
    text: str
    explanation: str = ""
    hint: str = ""

    def format(self, explain: bool = True) -> str:
        out = f"%{self.facility}-{self.severity}-{self.ident}, {self.text}"
        if explain and self.explanation:
            out += f"\n  Explanation: {self.explanation}"
        if explain and self.hint:
            out += f"\n  Hint: {self.hint}"
        return out


@dataclass
class CompileResult:
    ok: bool
    diagnostics: list[Diagnostic]
    obj_path: str | None
    dia_path: str | None
    lis_path: str | None = None


@dataclass
class ParseResult:
    ast: Any
    diagnostics: list[Diagnostic]


@dataclass
class LinkResult:
    ok: bool
    diagnostics: list[Diagnostic]
    exe_path: str | None
    map_path: str | None


@dataclass
class RunResult:
    exit_status: int
    output: str
    error: Diagnostic | None = None
    traceback: list[str] = field(default_factory=list)
    transcript: str = ""


@dataclass
class MessageInfo:
    facility: str
    ident: str
    severity: str
    template: str
    explanation: str
    hint: str


_PH = re.compile(r"%[{\[][A-Za-z_][\w$ ]*[}\]]%(?:\.\.\.)?")
_IO = re.compile(r"\b(WRITELN|WRITE|READLN)\b\s*(?:\(([^)]*)\))?", re.IGNORECASE)
_STR = re.compile(r"'((?:[^']|'')*)'")

MESSAGES = {
    ("PASCAL", "PLACEHOLDER"): MessageInfo(
        "PASCAL", "PLACEHOLDER", "E", "unexpanded placeholder {0}",
        "The program still contains a placeholder that LSE put there for you to fill in.",
        "Move to it with F8 (or Tab) and type over it, expand it with Tab, or erase it with Ctrl-K."),
    ("PASCAL", "SYNTAX"): MessageInfo(
        "PASCAL", "SYNTAX", "E", "syntax error",
        "The compiler found something it did not expect.",
        "Look at the line and compare it with the examples in HELP."),
    ("LINK", "OPENIN"): MessageInfo(
        "LINK", "OPENIN", "F", "cannot open {0}",
        "The object file does not exist.", "COMPILE the program first."),
    ("LINK", "UNDFSYMS"): MessageInfo(
        "LINK", "UNDFSYMS", "W", "undefined symbol {0}",
        "The program uses a name that no module defines.", "Check the spelling, or LINK the module that defines it."),
    ("LINK", "NOIMGFIL"): MessageInfo(
        "LINK", "NOIMGFIL", "E", "image file not created",
        "LINK found errors, so it did not write the .EXE.", "Fix the messages above, then LINK again."),
    ("PAS", "DIVBYZERO"): MessageInfo(
        "PAS", "DIVBYZERO", "F", "division by zero",
        "The program tried to divide by zero.", "Check the value before you divide."),
}


class FakePascalApi:
    """Stands in for ``pascal.api`` in editor tests.

    It does just enough to exercise the editor:

    * ``compile_file`` reports every leftover placeholder as
      ``%PASCAL-E-PLACEHOLDER`` and every line containing ``SYNTAXERROR`` as
      ``%PASCAL-E-SYNTAX``; otherwise it writes ``.OBJ`` and ``.DIA``.
    * ``link`` writes ``.EXE`` and ``.MAP`` that point back at the source; a
      source line containing ``UNDEFINEDSYM`` gives ``%LINK-W-UNDFSYMS`` there.
    * ``run_image`` "runs" the source: it prints the string literals of each
      ``WRITE``/``WRITELN`` and consumes a line of input for each
      ``READLN`` (shown in ``transcript``); a line containing ``DIVBYZERO``
      raises that runtime error. Exit status 0, or 1 after an error.

    Every call is recorded in ``calls`` as ``(name, args)``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    # -- helpers

    @staticmethod
    def _diag(path: str | None, line: int | None, col: int | None, fac: str, ident: str,
              *args: str) -> Diagnostic:
        info = MESSAGES[(fac, ident)]
        return Diagnostic(path, line, col, info.severity, fac, ident,
                          info.template.format(*args) + (f" at line {line}" if line else ""),
                          info.explanation, info.hint)

    def _check(self, text: str, path: str | None) -> list[Diagnostic]:
        diags = []
        for n, line in enumerate(text.split("\n"), 1):
            for m in _PH.finditer(line):
                diags.append(self._diag(path, n, m.start() + 1, "PASCAL", "PLACEHOLDER", m.group(0)))
            if "SYNTAXERROR" in line:
                diags.append(self._diag(path, n, line.index("SYNTAXERROR") + 1, "PASCAL", "SYNTAX"))
        return diags

    # -- contract

    def parse_source(self, text: str, filename: str = "<buffer>") -> ParseResult:
        self.calls.append(("parse_source", (filename,)))
        diags = self._check(text, filename)
        return ParseResult(None if diags else {"text": text}, diags)

    def compile_file(self, path, *, list_file: bool = False) -> CompileResult:
        path = str(path)
        self.calls.append(("compile_file", (path, list_file)))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        diags = self._check(text, path)
        base = os.path.splitext(path)[0]
        dia = base + ".DIA"
        with open(dia, "w", encoding="utf-8") as f:
            f.write("".join(d.format(False) + "\n" for d in diags))
        lis = None
        if list_file:
            lis = base + ".LIS"
            with open(lis, "w", encoding="utf-8") as f:
                f.write(text)
        if any(d.severity in "EF" for d in diags):
            return CompileResult(False, diags, None, dia, lis)
        obj = base + ".OBJ"
        with open(obj, "w", encoding="utf-8") as f:
            f.write(f"MODULE FAKE\nSOURCE {path}\n")
        return CompileResult(True, diags, obj, dia, lis)

    def link(self, obj_paths: list[str], *, output: str | None = None,
             map_file: bool = True) -> LinkResult:
        self.calls.append(("link", (tuple(obj_paths), output, map_file)))
        for obj in obj_paths:
            if not os.path.exists(obj):
                return LinkResult(False, [self._diag(None, None, None, "LINK", "OPENIN", obj)],
                                  None, None)
        with open(obj_paths[0], encoding="utf-8") as f:
            source = f.read().split("SOURCE ", 1)[1].strip()
        with open(source, encoding="utf-8") as f:
            for n, line in enumerate(f.read().split("\n"), 1):
                if "UNDEFINEDSYM" in line:
                    col = line.index("UNDEFINEDSYM") + 1
                    return LinkResult(False, [
                        self._diag(source, n, col, "LINK", "UNDFSYMS", "UNDEFINEDSYM"),
                        self._diag(None, None, None, "LINK", "NOIMGFIL")], None, None)
        exe = output or os.path.splitext(obj_paths[0])[0] + ".EXE"
        with open(exe, "w", encoding="utf-8") as f:
            f.write(f"IMAGE FAKE\nSOURCE {source}\n")
        mp = None
        if map_file:
            mp = os.path.splitext(exe)[0] + ".MAP"
            with open(mp, "w", encoding="utf-8") as f:
                f.write("PAS$WRITELN  PASRTL\n")
        return LinkResult(True, [], exe, mp)

    def run_image(self, exe_path, *, input_text: str | None = None, stdin=None, stdout=None,
                  seed: int | None = None, explain: bool = True) -> RunResult:
        self.calls.append(("run_image", (str(exe_path), input_text, seed)))
        self.last_explain = explain
        with open(exe_path, encoding="utf-8") as f:
            source = f.read().split("SOURCE ", 1)[1].strip()
        with open(source, encoding="utf-8") as f:
            text = f.read()
        pending = (input_text or "").split("\n") if input_text is not None else None
        out: list[str] = []
        transcript: list[str] = []

        def emit(s: str) -> None:
            out.append(s)
            transcript.append(s)
            if stdout is not None:
                stdout.write(s)

        for n, line in enumerate(text.split("\n"), 1):
            if "DIVBYZERO" in line:
                err = self._diag(source, n, None, "PAS", "DIVBYZERO")
                return RunResult(1, "".join(out), err,
                                 ["%TRACE-F-TRACEBACK, symbolic stack dump follows",
                                  f"  module FAKE  line {n}"], "".join(transcript))
            for m in _IO.finditer(line):
                kind = m.group(1).upper()
                if kind == "READLN":
                    typed = ""
                    if pending is not None:
                        typed = pending.pop(0) if pending else ""
                    elif stdin is not None:
                        typed = stdin.readline().rstrip("\n")
                    transcript.append(typed + "\n")
                    continue
                emit("".join(s.replace("''", "'") for s in _STR.findall(m.group(2) or "")))
                if kind == "WRITELN":
                    emit("\n")
        return RunResult(0, "".join(out), transcript="".join(transcript))

    def get_message(self, facility: str, ident: str) -> MessageInfo:
        return MESSAGES[(facility.upper(), ident.upper())]

    def all_messages(self) -> list[MessageInfo]:
        return list(MESSAGES.values())

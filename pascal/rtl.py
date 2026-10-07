"""The Pascal run-time library (PASRTL).

Compiled programs do their input and output, mathematics and random
numbers by calling ``PAS$...`` routines. The linker takes those routines
from the object library ``PASRTL.OLB``, just as VMS took them from its
shareable run-time library. Each library routine is a tiny p-code stub
whose ``NATIVE`` instruction runs the Python implementation below.

Run ``python -m pascal.rtl`` to regenerate ``PASRTL.OLB``.
"""

from __future__ import annotations

import math
import re
import time
from pathlib import Path

from . import VERSION
from .messages import diag

LIBRARY_PATH = Path(__file__).with_name("PASRTL.OLB")
LIBRARY_DATE = "7-OCT-2026 00:00:00"

# name: (library module, signature, argument cells, returns a value)
ROUTINES: dict[str, tuple[str, str, int, bool]] = {
    "PAS$WRITE_INT":   ("PAS$IO", "PROCEDURE(INTEGER,INTEGER)", 2, False),
    "PAS$WRITE_REAL":  ("PAS$IO", "PROCEDURE(REAL,INTEGER,INTEGER)", 3, False),
    "PAS$WRITE_BOOL":  ("PAS$IO", "PROCEDURE(BOOLEAN,INTEGER)", 2, False),
    "PAS$WRITE_CHAR":  ("PAS$IO", "PROCEDURE(CHAR,INTEGER)", 2, False),
    "PAS$WRITE_STR":   ("PAS$IO", "PROCEDURE(STRING,INTEGER)", 2, False),
    "PAS$WRITE_CHARS": ("PAS$IO", "PROCEDURE(VAR CHARS,INTEGER,INTEGER)", 3, False),
    "PAS$WRITE_ENUM":  ("PAS$IO", "PROCEDURE(INTEGER,INTEGER,STRING)", 3, False),
    "PAS$WRITELN":     ("PAS$IO", "PROCEDURE", 0, False),
    "PAS$READ_INT":    ("PAS$IO", "FUNCTION:INTEGER", 0, True),
    "PAS$READ_REAL":   ("PAS$IO", "FUNCTION:REAL", 0, True),
    "PAS$READ_CHAR":   ("PAS$IO", "FUNCTION:CHAR", 0, True),
    "PAS$READ_CHARS":  ("PAS$IO", "PROCEDURE(VAR CHARS,INTEGER)", 2, False),
    "PAS$READLN":      ("PAS$IO", "PROCEDURE", 0, False),
    "PAS$EOF":         ("PAS$IO", "FUNCTION:BOOLEAN", 0, True),
    "PAS$EOLN":        ("PAS$IO", "FUNCTION:BOOLEAN", 0, True),
    "PAS$SQRT":        ("PAS$MATH", "FUNCTION(REAL):REAL", 1, True),
    "PAS$SIN":         ("PAS$MATH", "FUNCTION(REAL):REAL", 1, True),
    "PAS$COS":         ("PAS$MATH", "FUNCTION(REAL):REAL", 1, True),
    "PAS$ARCTAN":      ("PAS$MATH", "FUNCTION(REAL):REAL", 1, True),
    "PAS$EXP":         ("PAS$MATH", "FUNCTION(REAL):REAL", 1, True),
    "PAS$LN":          ("PAS$MATH", "FUNCTION(REAL):REAL", 1, True),
    "PAS$RANDOMIZE":   ("PAS$RANDOM", "PROCEDURE", 0, False),
    "PAS$RANDOM":      ("PAS$RANDOM", "FUNCTION(INTEGER):INTEGER", 1, True),
    "PAS$RANDOM_REAL": ("PAS$RANDOM", "FUNCTION:REAL", 0, True),
    "PAS$HALT":        ("PAS$MISC", "PROCEDURE", 0, False),
}

DEFAULT_SEED = 20261007
MAXINT = 2147483647
MININT = -2147483648

_INT_RE = re.compile(r"[+-]?\d+\Z")
_REAL_RE = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\Z")


class PascalRuntimeError(Exception):
    """A fatal run-time error: becomes a %PAS-F-... message plus a traceback."""

    def __init__(self, ident: str, **args):
        super().__init__(ident)
        self.ident = ident
        self.args_ = args


class HaltProgram(Exception):
    pass


class Lcg:
    """The VAX MTH$RANDOM generator: seed := 69069 * seed + 1 (mod 2**32)."""

    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF
        for _ in range(8):      # stir small seeds so the first numbers look random
            self.next()

    def next(self) -> float:
        self.state = (69069 * self.state + 1) & 0xFFFFFFFF
        return self.state / 4294967296.0


class Runtime:
    """Input, output and random-number state of one program run."""

    def __init__(self, *, input_text: str | None = None, stdin=None, stdout=None,
                 seed: int | None = None, explain: bool = True):
        self.stdin = stdin
        self.stdout = stdout
        self.echo = stdin is None and stdout is not None
        self.pending = (input_text or "").replace("\r\n", "\n").split("\n")
        if self.pending and self.pending[-1] == "":
            self.pending.pop()
        self.explain = explain
        self.seed = seed
        self.rng = Lcg(seed if seed is not None else DEFAULT_SEED)
        self.output: list[str] = []
        self.transcript: list[str] = []
        self.out_line = ""        # text written on the current output line (the prompt)
        self.tr_col = 0
        self.term_col = 0
        self.line: str | None = None
        self.pos = 0
        self.prompt = ""
        self.memory = None        # set by the VM
        self.natives = {
            "PAS$WRITE_INT": lambda a: self.write_int(a[0], a[1]),
            "PAS$WRITE_REAL": lambda a: self.write_real(a[0], a[1], a[2]),
            "PAS$WRITE_BOOL": lambda a: self.write_field("TRUE" if a[0] else "FALSE", a[1]),
            "PAS$WRITE_CHAR": lambda a: self.write_field(chr(a[0]), a[1]),
            "PAS$WRITE_STR": lambda a: self.write_str(a[0], a[1]),
            "PAS$WRITE_CHARS": lambda a: self.write_str(self.chars_at(a[0], a[1]), a[2]),
            "PAS$WRITE_ENUM": lambda a: self.write_field(a[2].split(",")[a[0]], a[1]),
            "PAS$WRITELN": lambda a: self.write("\n"),
            "PAS$READ_INT": lambda a: self.read_int(),
            "PAS$READ_REAL": lambda a: self.read_real(),
            "PAS$READ_CHAR": lambda a: self.read_char(),
            "PAS$READ_CHARS": lambda a: self.read_chars(a[0], a[1]),
            "PAS$READLN": lambda a: self.readln(),
            "PAS$EOF": lambda a: self.eof(),
            "PAS$EOLN": lambda a: self.eoln(),
            "PAS$SQRT": lambda a: self.sqrt(a[0]),
            "PAS$SIN": lambda a: math.sin(a[0]),
            "PAS$COS": lambda a: math.cos(a[0]),
            "PAS$ARCTAN": lambda a: math.atan(a[0]),
            "PAS$EXP": lambda a: self.exp(a[0]),
            "PAS$LN": lambda a: self.ln(a[0]),
            "PAS$RANDOMIZE": lambda a: self.randomize(),
            "PAS$RANDOM": lambda a: self.random(a[0]),
            "PAS$RANDOM_REAL": lambda a: self.rng.next(),
            "PAS$HALT": lambda a: self.halt(),
        }

    # -- output ----------------------------------------------------------------
    def _to_output(self, s: str):
        if not s:
            return
        self.output.append(s)
        nl = s.rfind("\n")
        self.out_line = s[nl + 1:] if nl >= 0 else self.out_line + s

    def _to_transcript(self, s: str):
        if not s:
            return
        self.transcript.append(s)
        nl = s.rfind("\n")
        self.tr_col = len(s) - nl - 1 if nl >= 0 else self.tr_col + len(s)

    def _to_terminal(self, s: str):
        if self.stdout is None or not s:
            return
        self.stdout.write(s)
        nl = s.rfind("\n")
        self.term_col = len(s) - nl - 1 if nl >= 0 else self.term_col + len(s)

    def write(self, s: str):
        self._to_output(s)
        self._to_transcript(s)
        self._to_terminal(s)

    def flush(self):
        if self.stdout is not None:
            try:
                self.stdout.flush()
            except (OSError, ValueError):
                pass

    def write_message(self, text: str):
        """Write a system message on a line of its own on every stream."""
        self._to_output(("\n" if self.out_line else "") + text + "\n")
        self._to_transcript(("\n" if self.tr_col else "") + text + "\n")
        self._to_terminal(("\n" if self.term_col else "") + text + "\n")
        self.flush()

    def write_field(self, s: str, width: int):
        if width < 0:
            raise PascalRuntimeError("NEGWIDDIG", value=width)
        self.write(s.rjust(width))

    def write_int(self, v: int, width: int):
        self.write_field(str(int(v)), width)

    def write_str(self, s: str, width: int):
        if width < 0:
            raise PascalRuntimeError("NEGWIDDIG", value=width)
        self.write(s[:width] if width < len(s) else s.rjust(width))

    def write_real(self, v: float, width: int, digits: int):
        if width < 0:
            raise PascalRuntimeError("NEGWIDDIG", value=width)
        v = float(v)
        if digits >= 0:
            s = f"{v:.{digits}f}"
        else:
            sig = max(width - 7, 1)
            s = f"{v:.{sig}E}"
            if v >= 0 or s.startswith("+"):
                s = " " + s
        self.write(s.rjust(width))

    def chars_at(self, addr: int, n: int) -> str:
        cells = self.memory[addr:addr + n]
        return "".join(" " if c is None else chr(c) for c in cells)

    # -- input -----------------------------------------------------------------
    def fetch_line(self) -> bool:
        self.prompt = self.out_line
        self.flush()
        if self.stdin is not None:
            s = self.stdin.readline()
            if s == "":
                return False
            s = s.rstrip("\n").rstrip("\r")
            self._to_transcript(s + "\n")
            self.term_col = 0
        else:
            if not self.pending:
                return False
            s = self.pending.pop(0)
            self._to_transcript(s + "\n")
            if self.echo:
                self._to_terminal(s + "\n")
        self.line = s
        self.pos = 0
        return True

    def need_line(self):
        if self.line is None and not self.fetch_line():
            raise PascalRuntimeError("PASTEOF")

    def read_token(self) -> str:
        while True:
            self.need_line()
            line = self.line
            p = self.pos
            while p < len(line) and line[p] in " \t":
                p += 1
            if p >= len(line):
                self.line = None
                continue
            q = p
            while q < len(line) and line[q] not in " \t":
                q += 1
            self.pos = q
            return line[p:q]

    def bad_input(self, ident: str, text: str):
        d = diag("PAS", ident, text=text)
        self.line = None
        self.write_message(d.format(explain=self.explain))
        if self.prompt:
            self.write(self.prompt)

    def read_int(self) -> int:
        while True:
            tok = self.read_token()
            if _INT_RE.match(tok):
                v = int(tok)
                if MININT <= v <= MAXINT:
                    return v
            self.bad_input("INVSYNINT", tok)

    def read_real(self) -> float:
        while True:
            tok = self.read_token()
            if _REAL_RE.match(tok):
                return float(tok)
            self.bad_input("INVSYNREA", tok)

    def read_char(self) -> int:
        self.need_line()
        if self.pos >= len(self.line):
            self.line = None
            return ord(" ")
        c = self.line[self.pos]
        self.pos += 1
        return ord(c) if ord(c) < 256 else ord("?")

    def read_chars(self, addr: int, n: int):
        self.need_line()
        text = self.line[self.pos:self.pos + n]
        self.pos += len(text)
        text = text.ljust(n)
        for i, ch in enumerate(text):
            self.memory[addr + i] = ord(ch) if ord(ch) < 256 else ord("?")

    def readln(self):
        self.need_line()
        self.line = None

    def eof(self) -> int:
        if self.line is not None:
            return 0
        return 0 if self.fetch_line() else 1

    def eoln(self) -> int:
        if self.line is None and not self.fetch_line():
            return 1
        return 1 if self.pos >= len(self.line) else 0

    # -- mathematics -----------------------------------------------------------
    def sqrt(self, x: float) -> float:
        if x < 0:
            raise PascalRuntimeError("SQUROONEG", value=_num(x))
        return math.sqrt(x)

    def ln(self, x: float) -> float:
        if x <= 0:
            raise PascalRuntimeError("LOGNONPOS", value=_num(x))
        return math.log(x)

    def exp(self, x: float) -> float:
        try:
            return math.exp(x)
        except OverflowError:
            raise PascalRuntimeError("FLTOVF") from None

    # -- random numbers --------------------------------------------------------
    def randomize(self):
        seed = self.seed if self.seed is not None else time.time_ns() // 1000
        self.rng = Lcg(seed)

    def random(self, n: int) -> int:
        if n < 1:
            raise PascalRuntimeError("RANDARG", value=n)
        return min(int(self.rng.next() * n), n - 1)

    def halt(self):
        raise HaltProgram


def _num(x) -> str:
    return f"{x:g}" if isinstance(x, float) else str(x)


def library_modules():
    """The object modules that make up PASRTL.OLB."""
    from .objfile import ObjectModule, RoutineInfo, Symbol
    from .pcode import Instr

    by_module: dict[str, list[str]] = {}
    for name, (module, *_rest) in ROUTINES.items():
        by_module.setdefault(module, []).append(name)
    modules = []
    for module, names in by_module.items():
        obj = ObjectModule(name=module, kind="MODULE", source="PASRTL", ident=VERSION,
                           created=LIBRARY_DATE)
        for name in names:
            _, sig, cells, returns = ROUTINES[name]
            start = len(obj.code)
            obj.code.append(Instr("NATIVE", [name, cells], 0, "run the built-in routine"))
            obj.code.append(Instr("RETV" if returns else "RET", [], 0))
            obj.globals.append(Symbol(name, "ROUTINE", start, sig))
            obj.routines.append(RoutineInfo(name, start, len(obj.code) - 1, 1))
        modules.append(obj)
    return modules


def build_library_text() -> str:
    from .objfile import write_library
    return write_library("PASRTL", library_modules(),
                         title="Pascal run-time library (PAS$ routines)", created=LIBRARY_DATE)


def main():
    LIBRARY_PATH.write_text(build_library_text())
    print(f"wrote {LIBRARY_PATH}")


if __name__ == "__main__":
    main()

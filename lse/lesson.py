"""Lesson files: the data behind the tutorial (``lse/lessons/*.lesson``).

A lesson is a header and a list of steps::

    LESSON GUESS
      TITLE "Guess My Number"
      FILE GUESS.PAS
    END LESSON

    STEP variables
      TITLE "Variables: boxes that hold values"
      TEXT
        A variable is a named box. Pascal wants to know what kind of
        value goes in each box -- INTEGER means whole numbers.
      END TEXT
      DO "Go to the end of line 1, press Enter, type VAR and press Tab."
        CHECK CONTAINS_WORD VAR
      DO "Type secret, guess, tries and press Tab."
        NEXT "Type secret, guess, tries over %{identifier}%... and press Tab"
        CHECK DECLARES secret
      SEE "VAR and secret, guess, tries : INTEGER; just above BEGIN."
      HINT "The VAR section lists names, a colon, then the type."
      HINT "Type: secret, guess, tries   then Tab, Tab, Enter (INTEGER)"
      SOLUTION
        PROGRAM Guess(INPUT, OUTPUT);
        VAR
          secret, guess, tries : INTEGER;
        BEGIN
        END.
      END SOLUTION
    END STEP

* ``DO`` is one numbered action with the exact keys. The ``CHECK`` lines
  under it say when it is done; ``NEXT`` is an optional shorter wording
  for the NEXT line. ``CHECK`` lines before the first ``DO`` belong to the
  step as a whole.
* ``SEE`` says what success looks like (YOU WILL SEE).
* ``HINT`` lines are the first hint levels; the last level is "show me",
  which offers to put ``SOLUTION`` (the whole program as it should be at
  the end of the step) into the file.
* A step with no checks at all is the end of the lesson.
* ``!`` starts a comment line. Strings use double quotes (``""`` for a
  quote); ``\\n`` in a qualifier value is a new line.

Check types (``CHECK TYPE args /QUALIFIER=value``, every one takes
``/FAIL="what to say when it is not done yet"``):

=====================  =========================================================
``CONTAINS_TEXT t``    the program text contains ``t`` (any case)
``CONTAINS_WORD w``    ... contains the word ``w``
``PROGRAM_NAME n``     it is ``PROGRAM n``
``NO_PLACEHOLDERS``    no placeholders are left
``DECLARES v [type]``  a VAR section declares ``v`` (with that type)
``CONTAINS_STATEMENT`` a statement matches the pattern (several patterns: any)
``NO_ERRORS``          the compiler would find no errors
``COMPILES``           the user compiled it, with no errors, since the last change
``LINKS``              ... and linked it
``RAN``                ... and ran it to the end (``/OUTPUT="text"`` it printed,
                       ``/STOPPED`` also counts a run stopped with Ctrl-C)
``RUN_OUTPUT_CONTAINS`` a private test run (``/INPUT="1\\n2"``, ``/SEED=n``) prints t
``COMPILE_FAILED``     during this step a compile failed (optionally with that ident)
``MADE_ERROR``         during this step the program had an error
``REVIEWED``           during this step F8 (REVIEW) was used
``FILE_OPENED name``   during this step that file was opened
``EDITING name``       that file is in the current window
=====================  =========================================================
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

LESSON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lessons")

#: check type -> (minimum args, maximum args or None, allowed qualifiers)
CHECK_TYPES: dict[str, tuple[int, int | None, frozenset[str]]] = {
    "CONTAINS_TEXT": (1, 1, frozenset()),
    "CONTAINS_WORD": (1, 1, frozenset()),
    "PROGRAM_NAME": (1, 1, frozenset()),
    "NO_PLACEHOLDERS": (0, 0, frozenset()),
    "DECLARES": (1, 2, frozenset()),
    "CONTAINS_STATEMENT": (1, None, frozenset()),
    "NO_ERRORS": (0, 0, frozenset()),
    "COMPILES": (0, 0, frozenset()),
    "LINKS": (0, 0, frozenset()),
    "RAN": (0, 0, frozenset({"OUTPUT", "STOPPED"})),
    "RUN_OUTPUT_CONTAINS": (1, 1, frozenset({"INPUT", "SEED"})),
    "COMPILE_FAILED": (0, 1, frozenset()),
    "MADE_ERROR": (0, 0, frozenset()),
    "REVIEWED": (0, 0, frozenset()),
    "FILE_OPENED": (1, 1, frozenset()),
    "EDITING": (1, 1, frozenset()),
}

#: checks about the program text, re-checked in later steps (they should stay true)
DURABLE = frozenset({"CONTAINS_TEXT", "CONTAINS_WORD", "PROGRAM_NAME", "DECLARES",
                     "CONTAINS_STATEMENT"})
#: checks that remember an event once it happened during the step
LATCHED = frozenset({"COMPILE_FAILED", "MADE_ERROR", "REVIEWED", "FILE_OPENED"})


class LessonError(Exception):
    def __init__(self, filename: str, line: int, text: str) -> None:
        super().__init__(f"{filename}:{line}: {text}")
        self.filename, self.line, self.text = filename, line, text


@dataclass
class Check:
    kind: str
    args: list[str] = field(default_factory=list)
    quals: dict[str, str] = field(default_factory=dict)
    line: int = 0

    @property
    def durable(self) -> bool:
        return self.kind in DURABLE

    @property
    def latched(self) -> bool:
        return self.kind in LATCHED

    @property
    def key(self) -> str:
        """Identifies a latched check within its step (for saved progress)."""
        return " ".join([self.kind, *self.args]).upper()

    def __str__(self) -> str:
        parts = [self.kind] + [f'"{a}"' if " " in a else a for a in self.args]
        parts += [f"/{k}={v}" if v else f"/{k}" for k, v in self.quals.items()]
        return " ".join(parts)


@dataclass
class DoItem:
    text: str
    next: str | None = None
    checks: list[Check] = field(default_factory=list)

    @property
    def next_text(self) -> str:
        return self.next or self.text


@dataclass
class Step:
    id: str
    title: str = ""
    text: list[str] = field(default_factory=list)     # paragraphs
    items: list[DoItem] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)  # step-level
    see: str = ""
    hints: list[str] = field(default_factory=list)
    solution: list[str] | None = None
    line: int = 0

    @property
    def all_checks(self) -> list[Check]:
        return [c for item in self.items for c in item.checks] + self.checks

    @property
    def final(self) -> bool:
        return not self.all_checks


@dataclass
class Lesson:
    name: str
    title: str = ""
    file: str = ""
    steps: list[Step] = field(default_factory=list)
    filename: str = "<lesson>"

    def index_of(self, step_id: str) -> int | None:
        for i, st in enumerate(self.steps):
            if st.id.upper() == step_id.upper():
                return i
        return None


# ============================================================================
# Parsing
# ============================================================================


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n")


def _tokens(text: str, fname: str, lineno: int) -> list[tuple[str, bool]]:
    """Split a directive line into (token, quoted) pairs."""
    out: list[tuple[str, bool]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while True:
                if j >= n:
                    raise LessonError(fname, lineno, "a string is not closed (missing \")")
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            out.append(("".join(buf), True))
            i = j + 1
            continue
        j = i
        while j < n and not text[j].isspace():
            if text[j] == '"':
                j += 1
                while j < n and text[j] != '"':
                    j += 1
            j += 1
        out.append((text[i:j], False))
        i = j
    return out


def _qualifier(tok: str, fname: str, lineno: int) -> tuple[str, str]:
    body = tok[1:]
    name, _, value = body.partition("=")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].replace('""', '"')
    if not name:
        raise LessonError(fname, lineno, f"empty qualifier {tok!r}")
    return name.upper(), _unescape(value)


def _one_string(rest: list[tuple[str, bool]], what: str, fname: str, lineno: int) -> str:
    if len(rest) != 1:
        raise LessonError(fname, lineno, f'{what} needs one "quoted text"')
    return rest[0][0]


def _block(lines: list[str], start: int, end_word: str, fname: str) -> tuple[list[str], int]:
    """Lines up to ``END <end_word>``, dedented; returns them and the index after the END."""
    body: list[str] = []
    i = start
    while i < len(lines):
        if " ".join(lines[i].split()).upper() == f"END {end_word}":
            break
        body.append(lines[i].rstrip())
        i += 1
    else:
        raise LessonError(fname, start, f"{end_word} block has no END {end_word}")
    indents = [len(l) - len(l.lstrip()) for l in body if l.strip()]
    cut = min(indents) if indents else 0
    body = [l[cut:] if l.strip() else "" for l in body]
    while body and not body[-1]:
        body.pop()
    while body and not body[0]:
        body.pop(0)
    return body, i + 1


def _paragraphs(lines: list[str]) -> list[str]:
    paras: list[str] = []
    cur: list[str] = []
    for line in lines:
        if line.strip():
            cur.append(line.strip())
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return paras


def parse_check(rest: list[tuple[str, bool]], fname: str, lineno: int) -> Check:
    if not rest:
        raise LessonError(fname, lineno, "CHECK needs a check type, e.g. CHECK COMPILES")
    kind = rest[0][0].upper()
    if kind not in CHECK_TYPES:
        raise LessonError(fname, lineno, f"unknown check type {kind} (known: "
                          + ", ".join(sorted(CHECK_TYPES)) + ")")
    lo, hi, allowed = CHECK_TYPES[kind]
    args: list[str] = []
    quals: dict[str, str] = {}
    for tok, quoted in rest[1:]:
        if not quoted and tok.startswith("/"):
            name, value = _qualifier(tok, fname, lineno)
            if name not in allowed and name != "FAIL":
                raise LessonError(fname, lineno, f"CHECK {kind} has no /{name} qualifier")
            quals[name] = value
        else:
            args.append(tok)
    if len(args) < lo or (hi is not None and len(args) > hi):
        want = f"{lo}" if lo == hi else f"{lo} to {hi if hi is not None else 'any'}"
        raise LessonError(fname, lineno, f"CHECK {kind} takes {want} argument(s), "
                          f"got {len(args)}")
    if "SEED" in quals:
        try:
            int(quals["SEED"])
        except ValueError:
            raise LessonError(fname, lineno, f"/SEED needs a number, not {quals['SEED']!r}") \
                from None
    return Check(kind, args, quals, lineno)


def parse(text: str, filename: str = "<lesson>") -> Lesson:
    lines = text.split("\n")
    lesson: Lesson | None = None
    step: Step | None = None
    i = 0
    while i < len(lines):
        raw = lines[i]
        lineno = i + 1
        line = raw.strip()
        i += 1
        if not line or line.startswith("!"):
            continue
        toks = _tokens(line, filename, lineno)
        word = toks[0][0].upper()
        rest = toks[1:]
        two = " ".join(t for t, _ in toks[:2]).upper()
        if lesson is None:
            if word != "LESSON" or len(rest) != 1:
                raise LessonError(filename, lineno, "a lesson file starts with LESSON name")
            lesson = Lesson(rest[0][0], filename=filename)
            while i < len(lines):
                hdr = lines[i].strip()
                i += 1
                if not hdr or hdr.startswith("!"):
                    continue
                if " ".join(hdr.split()).upper() == "END LESSON":
                    break
                htoks = _tokens(hdr, filename, i)
                hword = htoks[0][0].upper()
                if hword == "TITLE":
                    lesson.title = _one_string(htoks[1:], "TITLE", filename, i)
                elif hword == "FILE":
                    lesson.file = _one_string(htoks[1:], "FILE", filename, i)
                else:
                    raise LessonError(filename, i, f"unknown LESSON line {hword}")
            else:
                raise LessonError(filename, lineno, "LESSON has no END LESSON")
            if not lesson.file:
                raise LessonError(filename, lineno, "the LESSON needs a FILE line")
            continue
        if step is None:
            if word != "STEP" or len(rest) != 1:
                raise LessonError(filename, lineno, f"expected STEP name, found {line!r}")
            if lesson.index_of(rest[0][0]) is not None:
                raise LessonError(filename, lineno, f"there are two steps called {rest[0][0]}")
            step = Step(rest[0][0], line=lineno)
            continue
        if two == "END STEP":
            if not step.title:
                raise LessonError(filename, step.line, f"step {step.id} has no TITLE")
            if not step.final and not step.items:
                raise LessonError(filename, step.line, f"step {step.id} has no DO lines")
            if not step.final and not step.see:
                raise LessonError(filename, step.line, f"step {step.id} has no SEE line")
            lesson.steps.append(step)
            step = None
        elif word == "TITLE":
            step.title = _one_string(rest, "TITLE", filename, lineno)
        elif word == "TEXT":
            body, i = _block(lines, i, "TEXT", filename)
            step.text = _paragraphs(body)
        elif word == "SOLUTION":
            body, i = _block(lines, i, "SOLUTION", filename)
            step.solution = body
        elif word == "DO":
            step.items.append(DoItem(_one_string(rest, "DO", filename, lineno)))
        elif word == "NEXT":
            if not step.items:
                raise LessonError(filename, lineno, "NEXT belongs under a DO line")
            step.items[-1].next = _one_string(rest, "NEXT", filename, lineno)
        elif word == "CHECK":
            check = parse_check(rest, filename, lineno)
            (step.items[-1].checks if step.items else step.checks).append(check)
        elif word == "SEE":
            text = _one_string(rest, "SEE", filename, lineno)
            step.see = f"{step.see} {text}".strip()
        elif word == "HINT":
            step.hints.append(_one_string(rest, "HINT", filename, lineno))
        else:
            raise LessonError(filename, lineno, f"unknown line in STEP {step.id}: {word}")
    if lesson is None:
        raise LessonError(filename, 1, "the file is empty (a lesson starts with LESSON name)")
    if step is not None:
        raise LessonError(filename, step.line, f"STEP {step.id} has no END STEP")
    if not lesson.steps:
        raise LessonError(filename, 1, "the lesson has no steps")
    return lesson


def load(name: str, directory: str = LESSON_DIR) -> Lesson:
    path = name if os.path.sep in name or name.endswith(".lesson") else \
        os.path.join(directory, name.lower() + ".lesson")
    with open(path, encoding="utf-8") as f:
        return parse(f.read(), path)

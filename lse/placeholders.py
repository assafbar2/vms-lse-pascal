"""Placeholder engine: find, navigate, expand and erase placeholders.

Pascal uses ``{ }`` for comments and ``[ ]`` for arrays, so placeholders
use LSE's alternate delimiters:

* ``%{name}%``  required
* ``%[name]%``  optional
* a trailing ``...`` marks a list placeholder (it can repeat)

Everything here is a pure function over a list of lines, so it can be
tested and reused (by the editor and by the tutor) without a screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .langdef import PlaceholderDef

PLACEHOLDER_RE = re.compile(
    r"%(?P<open>[{\[])(?P<name>[A-Za-z_][\w$]*(?: [\w$]+)*)(?P<close>[}\]])%(?P<list>\.\.\.)?"
)
_PAIRS = {"{": "}", "[": "]"}
_IDENT = re.compile(r"[A-Za-z0-9_]")


@dataclass(frozen=True)
class Placeholder:
    row: int
    start: int
    end: int
    name: str
    optional: bool
    is_list: bool

    @property
    def text(self) -> str:
        return make_placeholder(self.name, optional=self.optional, is_list=self.is_list)

    def contains(self, row: int, col: int) -> bool:
        return row == self.row and self.start <= col < self.end


def make_placeholder(name: str, *, optional: bool = False, is_list: bool = False) -> str:
    o, c = ("[", "]") if optional else ("{", "}")
    return f"%{o}{name}{c}%" + ("..." if is_list else "")


def scan_line(line: str, row: int = 0) -> list[Placeholder]:
    out = []
    for m in PLACEHOLDER_RE.finditer(line):
        if _PAIRS[m.group("open")] != m.group("close"):
            continue
        out.append(Placeholder(row, m.start(), m.end(), m.group("name"),
                               m.group("open") == "[", bool(m.group("list"))))
    return out


def scan(lines: list[str]) -> list[Placeholder]:
    out: list[Placeholder] = []
    for row, line in enumerate(lines):
        if "%" in line:
            out.extend(scan_line(line, row))
    return out


def count(lines: list[str]) -> int:
    return len(scan(lines))


def placeholder_at(lines: list[str], row: int, col: int) -> Placeholder | None:
    """The placeholder covering (row, col), if any (its end is exclusive)."""
    if not 0 <= row < len(lines):
        return None
    for ph in scan_line(lines[row], row):
        if ph.start <= col < ph.end:
            return ph
    return None


def next_placeholder(lines: list[str], row: int, col: int, *, wrap: bool = True
                     ) -> tuple[Placeholder, bool] | None:
    """The next placeholder after the cursor; ``(placeholder, wrapped)``."""
    current = placeholder_at(lines, row, col)
    phs = scan(lines)
    for ph in phs:
        if (ph.row, ph.start) > (row, col) and ph != current:
            return ph, False
    if wrap:
        for ph in phs:
            if ph != current:
                return ph, True
    return None


def previous_placeholder(lines: list[str], row: int, col: int, *, wrap: bool = True
                         ) -> tuple[Placeholder, bool] | None:
    current = placeholder_at(lines, row, col)
    limit = (current.row, current.start) if current else (row, col)
    phs = scan(lines)
    for ph in reversed(phs):
        if (ph.row, ph.start) < limit:
            return ph, False
    if wrap:
        for ph in reversed(phs):
            if ph != current:
                return ph, True
    return None


def word_at(line: str, col: int) -> tuple[int, int, str] | None:
    """The identifier touching ``col`` (under the cursor or just before it)."""
    s = col
    while s > 0 and _IDENT.match(line[s - 1]):
        s -= 1
    e = col
    while e < len(line) and _IDENT.match(line[e]):
        e += 1
    if s == e:
        return None
    return s, e, line[s:e]


def indent_of(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" "))]


def base_indent(line: str, start: int) -> str:
    """Indentation for the 2nd and later lines of a template inserted at ``start``."""
    before = line[:start]
    if before.strip() == "":
        return before
    return indent_of(line)


@dataclass(frozen=True)
class Duplication:
    """How a list placeholder repeats after it is expanded."""

    text: str
    separator: str
    vertical: bool


def duplication_for(ph: Placeholder, defn: "PlaceholderDef | None", line: str) -> Duplication | None:
    if not ph.is_list:
        return None
    sep = defn.separator if defn else ""
    mode = defn.duplication if defn else "CONTEXT_DEPENDENT"
    if mode == "CONTEXT_DEPENDENT":
        vertical = line[:ph.start].strip() == "" and line[ph.end:].strip() == ""
    else:
        vertical = mode == "VERTICAL"
    return Duplication(make_placeholder(ph.name, optional=True, is_list=True), sep, vertical)


@dataclass
class EditResult:
    lines: list[str]
    cursor: tuple[int, int]
    region: tuple[int, int, int, int] = (0, 0, 0, 0)


def apply_template(lines: list[str], row: int, start: int, end: int, body: list[str],
                   dup: Duplication | None = None) -> EditResult:
    """Replace ``lines[row][start:end]`` with a template.

    Later body lines are indented to line up with the start of the
    replaced text. With ``dup`` a copy of the list placeholder follows the
    expansion (on a new line when vertical, after the separator when
    horizontal). The cursor goes to the first placeholder inside the
    expansion, or to its end.
    """
    line = lines[row]
    before, after = line[:start], line[end:]
    indent = base_indent(line, start)
    body = body or [""]
    new = [body[0]] + [(indent + b) if b.strip() else "" for b in body[1:]]
    region_end_row = row + len(new) - 1
    region_end_col = len(new[-1]) + (len(before) if len(new) == 1 else 0)
    if dup:
        if dup.vertical:
            new[-1] += dup.separator
            new.append(indent + dup.text)
        else:
            new[-1] += dup.separator + dup.text
    new[0] = before + new[0]
    new[-1] = new[-1] + after
    result = lines[:row] + new + lines[row + 1:]
    cursor = (region_end_row, region_end_col)
    for ph in scan(result[row:region_end_row + 1]):
        r = ph.row + row
        if (r, ph.start) >= (row, start) and (r, ph.end) <= (region_end_row, region_end_col):
            cursor = (r, ph.start)
            break
    return EditResult(result, cursor, (row, start, region_end_row, region_end_col))


_JOINABLE = set(";,")


def erase(lines: list[str], ph: Placeholder, defn: "PlaceholderDef | None" = None) -> EditResult:
    """Remove a placeholder.

    A placeholder alone on its line takes the line with it. An optional
    list placeholder also takes the separator in front of it (the ``;``
    at the end of the previous statement, or the ``, `` before it on the
    same line). Punctuation left alone on a line joins the previous line.
    """
    line = lines[ph.row]
    before, after = line[:ph.start], line[ph.end:]
    sep = defn.separator.strip() if (defn and ph.optional and ph.is_list) else ""
    new = list(lines)
    if before.strip() == "" and after.strip() == "":
        del new[ph.row]
        if not new:
            return EditResult([""], (0, 0))
        if sep:
            p = ph.row - 1
            while p >= 0 and not new[p].strip():
                p -= 1
            if p >= 0 and new[p].rstrip().endswith(sep):
                stripped = new[p].rstrip()
                new[p] = stripped[:-len(sep)].rstrip()
                return EditResult(new, (p, len(new[p])))
        r = min(ph.row, len(new) - 1)
        return EditResult(new, (r, len(indent_of(new[r]))))
    if sep and before.rstrip().endswith(sep):
        before = before.rstrip()[:-len(sep)].rstrip()
    elif before.endswith(" ") and (after == "" or after.startswith(" ")):
        before = before.rstrip(" ") if after == "" else before[:-1]
    joined = before + after
    leftover = joined.strip()
    if (before.strip() == "" and leftover and set(leftover) <= _JOINABLE and ph.row > 0):
        prev = new[ph.row - 1].rstrip()
        new[ph.row - 1] = prev + leftover
        del new[ph.row]
        return EditResult(new, (ph.row - 1, len(prev)))
    new[ph.row] = joined
    return EditResult(new, (ph.row, len(before)))

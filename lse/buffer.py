"""Line-based text buffer with undo/redo and versioned save."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

from . import files

if TYPE_CHECKING:
    from .langdef import Language

UNDO_LIMIT = 2000


class ReadOnlyError(Exception):
    pass


@dataclass
class _Snapshot:
    lines: list[str]
    cursor: tuple[int, int]
    state_id: int


class Buffer:
    """A list of lines plus a cursor.

    The cursor belongs to the buffer (``row``/``col``, both 0-based), so
    two windows on one buffer share it. Every edit method records undo
    information; wrap several edits in ``with buffer.change():`` to make
    them one undo step. ``state_id`` changes on every edit and returns to
    an earlier value on undo, so ``modified`` is exact.
    """

    def __init__(self, name: str, lines: list[str] | None = None, *,
                 path: str | None = None, version: int | None = None,
                 language: "Language | None" = None, read_only: bool = False,
                 system: bool = False) -> None:
        self.name = name
        self.lines: list[str] = list(lines) if lines else [""]
        self.path = path
        self.version = version
        self.language = language
        self.read_only = read_only
        self.system = system
        self.row = 0
        self.col = 0
        self.goal_col: int | None = None
        self.undo_stack: list[_Snapshot] = []
        self.redo_stack: list[_Snapshot] = []
        self._ids = 0
        self.state_id = 0
        self.saved_state_id = 0
        self._group_next: object = None
        self._txn_depth = 0
        self._txn_group: object = None
        self._txn_snapshotted = False
        self.highlight_row: int | None = None
        #: key -> command overrides while this buffer is current (e.g. Enter in $REVIEW)
        self.local_keys: dict[str, str] = {}

    # ----- basic properties -------------------------------------------------

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def cursor(self) -> tuple[int, int]:
        return self.row, self.col

    @property
    def modified(self) -> bool:
        return not self.system and self.state_id != self.saved_state_id

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def display_name(self) -> str:
        if self.path and self.version:
            return f"{self.name};{self.version}"
        return self.name

    def set_cursor(self, row: int, col: int, *, keep_goal: bool = False) -> None:
        row = max(0, min(row, len(self.lines) - 1))
        col = max(0, min(col, len(self.lines[row])))
        self.row, self.col = row, col
        if not keep_goal:
            self.goal_col = None

    def current_line(self) -> str:
        return self.lines[self.row]

    # ----- undo machinery ---------------------------------------------------

    def _new_state(self) -> None:
        self._ids += 1
        self.state_id = self._ids

    def _prepare_undo(self, group: object) -> None:
        if group is None or group != self._group_next:
            self.undo_stack.append(_Snapshot(list(self.lines), self.cursor, self.state_id))
            if len(self.undo_stack) > UNDO_LIMIT:
                del self.undo_stack[0]
        self.redo_stack.clear()
        self._group_next = None

    def _edit(self) -> None:
        if self.read_only:
            raise ReadOnlyError(self.name)
        if self._txn_depth:
            if not self._txn_snapshotted:
                self._prepare_undo(self._txn_group)
                self._txn_snapshotted = True
        else:
            self._prepare_undo(None)
        self._new_state()

    @contextmanager
    def change(self, group: object = None, next_group: object = None) -> Iterator[None]:
        """Group edits into one undo step.

        ``group`` lets consecutive steps merge: if it equals the
        ``next_group`` given by the previous step, no new undo entry is made
        (this is how typing a word becomes one undo step).
        """
        outer = self._txn_depth == 0
        if outer:
            self._txn_group = group
            self._txn_snapshotted = False
        self._txn_depth += 1
        try:
            yield
        finally:
            self._txn_depth -= 1
            if outer:
                if self._txn_snapshotted:
                    self._group_next = next_group
                self._txn_group = None

    def break_undo_group(self) -> None:
        self._group_next = None

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        snap = self.undo_stack.pop()
        self.redo_stack.append(_Snapshot(list(self.lines), self.cursor, self.state_id))
        self._restore(snap)
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        snap = self.redo_stack.pop()
        self.undo_stack.append(_Snapshot(list(self.lines), self.cursor, self.state_id))
        self._restore(snap)
        return True

    def _restore(self, snap: _Snapshot) -> None:
        self.lines = list(snap.lines)
        self.state_id = snap.state_id
        self._group_next = None
        self.set_cursor(*snap.cursor)

    # ----- primitive edits --------------------------------------------------

    def insert(self, row: int, col: int, text: str) -> tuple[int, int]:
        """Insert ``text`` (may contain newlines); return the end position."""
        self._edit()
        line = self.lines[row]
        before, after = line[:col], line[col:]
        parts = text.split("\n")
        if len(parts) == 1:
            self.lines[row] = before + text + after
            return row, col + len(text)
        new = [before + parts[0], *parts[1:-1], parts[-1] + after]
        self.lines[row:row + 1] = new
        return row + len(parts) - 1, len(parts[-1])

    def delete(self, r1: int, c1: int, r2: int, c2: int) -> str:
        """Delete from (r1, c1) up to (r2, c2); return the removed text."""
        if (r2, c2) < (r1, c1):
            r1, c1, r2, c2 = r2, c2, r1, c1
        if (r1, c1) == (r2, c2):
            return ""
        self._edit()
        removed = self.get_text(r1, c1, r2, c2)
        self.lines[r1:r2 + 1] = [self.lines[r1][:c1] + self.lines[r2][c2:]]
        return removed

    def get_text(self, r1: int, c1: int, r2: int, c2: int) -> str:
        if r1 == r2:
            return self.lines[r1][c1:c2]
        out = [self.lines[r1][c1:], *self.lines[r1 + 1:r2], self.lines[r2][:c2]]
        return "\n".join(out)

    def replace_line(self, row: int, text: str) -> None:
        self._edit()
        self.lines[row] = text

    def set_lines(self, lines: list[str]) -> None:
        """Replace the whole text (one undo step)."""
        self._edit()
        self.lines = list(lines) if lines else [""]
        self.set_cursor(self.row, self.col)

    def delete_lines(self, start: int, end: int) -> None:
        """Delete whole lines ``start`` .. ``end - 1``."""
        self._edit()
        del self.lines[start:end]
        if not self.lines:
            self.lines = [""]

    def load_text(self, text: str | list[str]) -> None:
        """Replace content without undo history (system buffers, reloads)."""
        self.lines = text.split("\n") if isinstance(text, str) else (list(text) or [""])
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._new_state()
        self.saved_state_id = self.state_id
        self.set_cursor(0, 0)

    def append_line(self, text: str) -> None:
        """Append to a system buffer (no undo, no modified flag)."""
        if self.lines == [""]:
            self.lines = []
        self.lines.extend(text.split("\n"))

    # ----- files ------------------------------------------------------------

    def save(self, path: str | None = None) -> int:
        """Write a new version; return its number. ``path`` renames first."""
        if path is not None:
            self.path = files.split_version(path)[0]
            self.name = os.path.basename(self.path)
        if not self.path:
            raise ValueError("buffer has no file name")
        version = files.write_new_version(self.path, self.lines)
        self.version = version
        self.saved_state_id = self.state_id
        self.break_undo_group()
        return version

    def mark_saved(self) -> None:
        self.saved_state_id = self.state_id

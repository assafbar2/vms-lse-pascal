"""A headless character grid: what the editor would show on the terminal.

The renderer (``lse.render``) draws into a ``VirtualScreen``; the curses
backend (``lse.screen``) copies it to the real terminal, and tests read it
directly. Each cell has a character and a *role* (``"text"``,
``"status"``, ``"placeholder"`` ...) that the theme turns into colours.

Line-drawing characters are stored as Unicode box characters
(``┌ ─ ┐ │ └ ┘ ├ ┤ ┬ ┴ ┼``); curses draws them with the DEC Special
Graphics (ACS) set. ``text(ascii=True)`` shows them as ``+ - |``.

``regions`` names the rows of each part of the layout, so tests do not
hard-code row numbers: ``"window0"``, ``"status0"``, ``"window1"``,
``"status1"``, ``"message"``, ``"command"`` (and whatever panels later
layers add, such as ``"next"`` or ``"keybar"``).
"""

from __future__ import annotations

BOX_TO_ASCII = str.maketrans({
    "┌": "+", "┐": "+", "└": "+", "┘": "+", "├": "+", "┤": "+",
    "┬": "+", "┴": "+", "┼": "+", "─": "-", "│": "|",
})


class VirtualScreen:
    def __init__(self, height: int, width: int) -> None:
        self.height = height
        self.width = width
        self.chars = [[" "] * width for _ in range(height)]
        self.roles = [["text"] * width for _ in range(height)]
        self.cursor: tuple[int, int] | None = None
        #: where the text cursor was before overlays drew (menus anchor to it)
        self.buffer_cursor: tuple[int, int] | None = None
        self.regions: dict[str, list[int]] = {}

    # ----- drawing ------------------------------------------------------------

    def put(self, row: int, col: int, text: str, role: str = "text") -> int:
        """Write ``text`` at (row, col), clipped to the screen; return end column."""
        if not 0 <= row < self.height:
            return col
        for ch in text:
            if col >= self.width:
                break
            if col >= 0:
                self.chars[row][col] = ch
                self.roles[row][col] = role
            col += 1
        return col

    def fill(self, row: int, role: str = "text", ch: str = " ", start: int = 0,
             end: int | None = None) -> None:
        if not 0 <= row < self.height:
            return
        end = self.width if end is None else min(end, self.width)
        for c in range(max(0, start), end):
            self.chars[row][c] = ch
            self.roles[row][c] = role

    def set_role(self, row: int, start: int, end: int, role: str) -> None:
        if not 0 <= row < self.height:
            return
        for c in range(max(0, start), min(end, self.width)):
            self.roles[row][c] = role

    def box(self, top: int, left: int, height: int, width: int, role: str = "border",
            title: str | None = None, fill_role: str | None = None) -> None:
        """Draw a line-drawing box; optionally clear its inside to ``fill_role``."""
        if height < 2 or width < 2:
            return
        right, bottom = left + width - 1, top + height - 1
        self.put(top, left, "┌" + "─" * (width - 2) + "┐", role)
        for r in range(top + 1, bottom):
            self.put(r, left, "│", role)
            if fill_role is not None:
                self.fill(r, fill_role, start=left + 1, end=right)
            self.put(r, right, "│", role)
        self.put(bottom, left, "└" + "─" * (width - 2) + "┘", role)
        if title:
            label = f"[ {title} ]"[: max(0, width - 4)]
            self.put(top, left + 2, label, role)

    # ----- reading ------------------------------------------------------------

    def line(self, row: int, *, ascii: bool = False) -> str:
        text = "".join(self.chars[row]).rstrip()
        return text.translate(BOX_TO_ASCII) if ascii else text

    def lines(self, *, ascii: bool = False) -> list[str]:
        return [self.line(r, ascii=ascii) for r in range(self.height)]

    def text(self, *, ascii: bool = False) -> str:
        return "\n".join(self.lines(ascii=ascii))

    def __str__(self) -> str:
        return self.text()

    def region(self, name: str) -> list[str]:
        """Text of the rows in a named region (empty list if absent)."""
        return [self.line(r) for r in self.regions.get(name, [])]

    def region_text(self, name: str) -> str:
        return "\n".join(self.region(name)).rstrip("\n")

    def find(self, text: str) -> tuple[int, int] | None:
        for r in range(self.height):
            c = "".join(self.chars[r]).find(text)
            if c >= 0:
                return r, c
        return None

    def __contains__(self, text: str) -> bool:
        return self.find(text) is not None

    def role_at(self, row: int, col: int) -> str:
        return self.roles[row][col]

    def runs(self, row: int) -> list[tuple[int, str, str]]:
        """``(col, text, role)`` runs of equal role, for the curses backend."""
        out: list[tuple[int, str, str]] = []
        start = 0
        chars, roles = self.chars[row], self.roles[row]
        for c in range(1, self.width + 1):
            if c == self.width or roles[c] != roles[start]:
                out.append((start, "".join(chars[start:c]), roles[start]))
                start = c
        return out

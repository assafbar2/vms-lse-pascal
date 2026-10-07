"""Curses backend: copy a ``VirtualScreen`` to the terminal and read keys.

This is the only module that imports curses at runtime. It runs the
terminal in raw mode so that Ctrl-S, Ctrl-Q, Ctrl-Z and Ctrl-C reach the
editor instead of being taken as flow control or signals.
"""

from __future__ import annotations

import curses
from typing import Callable

from .themes import ROLES, get_theme
from .vscreen import BOX_TO_ASCII, VirtualScreen

_FIXED_CODES: dict[int, str] = {
    9: "Tab", 10: "Enter", 13: "Enter", 27: "Esc", 127: "Backspace", 8: "Backspace",
    0: "C-Space",
}

_CURSES_NAMES = {
    "KEY_UP": "Up", "KEY_DOWN": "Down", "KEY_LEFT": "Left", "KEY_RIGHT": "Right",
    "KEY_HOME": "Home", "KEY_END": "End", "KEY_PPAGE": "PageUp", "KEY_NPAGE": "PageDown",
    "KEY_IC": "Insert", "KEY_DC": "Delete", "KEY_BACKSPACE": "Backspace",
    "KEY_ENTER": "Enter", "KEY_BTAB": "S-Tab", "KEY_RESIZE": "Resize",
    "KEY_SLEFT": "S-Left", "KEY_SRIGHT": "S-Right", "KEY_SR": "S-Up", "KEY_SF": "S-Down",
    "KEY_A1": "Home", "KEY_A3": "PageUp", "KEY_C1": "End", "KEY_C3": "PageDown",
}

# terminfo extended key names (xterm modifiers: 3 = Alt, 5 = Ctrl)
_EXTENDED = {
    "kDC5": "C-Delete", "kLFT5": "C-Left", "kRIT5": "C-Right", "kUP5": "C-Up",
    "kDN5": "C-Down", "kHOM5": "C-Home", "kEND5": "C-End",
    "kLFT": "S-Left", "kRIT": "S-Right",
}


def _code_table() -> dict[int, str]:
    table: dict[int, str] = {}
    for attr, name in _CURSES_NAMES.items():
        code = getattr(curses, attr, None)
        if code is not None:
            table[code] = name
    for n in range(1, 13):
        table[curses.KEY_F0 + n] = f"F{n}"
    # xterm reports Shift-F1..F12 as F13..F24
    for n in range(13, 25):
        table[curses.KEY_F0 + n] = f"S-F{n - 12}"
    return table


_CODES = _code_table()


def translate_key(ch: int | str, keyname: Callable[[int], bytes] | None = None) -> str | None:
    """Map a value from ``get_wch()`` to an editor key name (None = ignore)."""
    if isinstance(ch, str):
        if len(ch) != 1:
            return None
        code = ord(ch)
        if code in _FIXED_CODES:
            return _FIXED_CODES[code]
        if 1 <= code <= 26:
            return "C-" + chr(code + 96)
        if code == 31:
            return "C-_"
        if code < 32:
            return None
        return ch
    if ch in _FIXED_CODES:
        return _FIXED_CODES[ch]
    if ch in _CODES:
        return _CODES[ch]
    if keyname is not None:
        try:
            name = keyname(ch).decode("ascii", "replace")
        except Exception:
            return None
        if name in _EXTENDED:
            return _EXTENDED[name]
    return None


_ACS_NAMES = {
    "┌": "ACS_ULCORNER", "┐": "ACS_URCORNER", "└": "ACS_LLCORNER", "┘": "ACS_LRCORNER",
    "─": "ACS_HLINE", "│": "ACS_VLINE", "├": "ACS_LTEE", "┤": "ACS_RTEE",
    "┬": "ACS_TTEE", "┴": "ACS_BTEE", "┼": "ACS_PLUS",
}

_ATTRS = {"bold": "A_BOLD", "reverse": "A_REVERSE", "underline": "A_UNDERLINE", "dim": "A_DIM"}


class CursesScreen:
    def __init__(self, stdscr) -> None:
        self.stdscr = stdscr
        self.theme_name: str | None = None
        self._attr: dict[str, int] = {}
        self._acs = {ch: getattr(curses, name) for ch, name in _ACS_NAMES.items()
                     if hasattr(curses, name)}
        curses.raw()
        curses.noecho()
        curses.nonl()
        stdscr.keypad(True)
        try:
            curses.set_escdelay(25)
        except AttributeError:
            pass
        self.has_colors = False
        try:
            if curses.has_colors():
                curses.start_color()
                self.has_colors = True
        except curses.error:
            pass

    def size(self) -> tuple[int, int]:
        return self.stdscr.getmaxyx()

    def apply_theme(self, name: str) -> None:
        if name == self.theme_name:
            return
        self.theme_name = name
        theme = get_theme(name)
        self._attr = {}
        pair_fg: dict[str, int] = {}
        if self.has_colors:
            colors = curses.COLORS

            def pick(options: tuple[int, ...]) -> int:
                for c in options:
                    if c < colors:
                        return c
                return 7

            pair_fg = {"normal": pick(theme.foreground), "bright": pick(theme.bright)}
            for i, which in enumerate(("normal", "bright"), start=1):
                try:
                    curses.init_pair(i, pair_fg[which], theme.background)
                except curses.error:
                    pass
        for role in ROLES:
            fg, attrs = theme.style(role)
            value = 0
            if self.has_colors:
                value |= curses.color_pair(1 if fg == "normal" else 2)
            elif fg == "bright":
                value |= curses.A_BOLD
            for a in attrs:
                value |= getattr(curses, _ATTRS[a], 0)
            self._attr[role] = value
        if self.has_colors:
            self.stdscr.bkgd(" ", curses.color_pair(1))

    def draw(self, scr: VirtualScreen, line_drawing: str = "ACS") -> None:
        """Copy the virtual screen to the terminal.

        ``line_drawing``: ``ACS`` (DEC Special Graphics, the default),
        ``UNICODE`` (box characters as text) or ``ASCII`` (``+ - |``), for
        terminals whose DEC graphics show up as ``lqqk``.
        """
        win = self.stdscr
        h, w = win.getmaxyx()
        win.erase()
        acs_map = self._acs if line_drawing == "ACS" else {}
        for row in range(min(h, scr.height)):
            for col, text, role in scr.runs(row):
                if col >= w:
                    break
                attr = self._attr.get(role, 0)
                text = text[: w - col]
                if line_drawing == "ASCII":
                    text = text.translate(BOX_TO_ASCII)
                start = 0
                for i, ch in enumerate(text):
                    acs = acs_map.get(ch)
                    if acs is None:
                        continue
                    if i > start:
                        self._put(row, col + start, text[start:i], attr)
                    self._putch(row, col + i, acs, attr)
                    start = i + 1
                if start < len(text):
                    self._put(row, col + start, text[start:], attr)
        if scr.cursor is not None:
            try:
                curses.curs_set(1)
            except curses.error:
                pass
            r, c = scr.cursor
            try:
                win.move(min(r, h - 1), min(c, w - 1))
            except curses.error:
                pass
        else:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        win.refresh()

    def _put(self, row: int, col: int, text: str, attr: int) -> None:
        try:
            self.stdscr.addstr(row, col, text, attr)
        except curses.error:
            pass  # writing the bottom-right cell moves the cursor off screen

    def _putch(self, row: int, col: int, ch: int, attr: int) -> None:
        try:
            self.stdscr.addch(row, col, ch, attr)
        except curses.error:
            pass

    def read_key(self, timeout_ms: int) -> str | None:
        """Wait up to ``timeout_ms`` (-1 = forever) for a key; None on timeout."""
        self.stdscr.timeout(timeout_ms)
        while True:
            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                return None
            key = translate_key(ch, curses.keyname)
            if key is not None:
                return key

"""Colour themes: VT220 (white on black), AMBER and GREEN phosphor.

The renderer tags every screen cell with a role; a theme says how each
role looks. Styles use terminal-neutral words so the headless screen
and tests never depend on curses:

* ``fg``: ``"normal"`` (the phosphor colour) or ``"bright"``
* ``attrs``: any of ``"bold"``, ``"reverse"``, ``"underline"``, ``"dim"``
"""

from __future__ import annotations

from dataclasses import dataclass

ROLES = (
    "text", "placeholder", "eof", "highlight", "status", "status_inactive",
    "message", "message_warning", "message_error", "message_hint",
    "command", "command_hint", "menu", "menu_selected", "menu_border",
    "help", "help_title", "border", "keytest_ok",
)

_STYLES: dict[str, tuple[str, frozenset[str]]] = {
    "text": ("normal", frozenset()),
    "placeholder": ("bright", frozenset({"bold", "underline"})),
    "eof": ("normal", frozenset({"dim"})),
    "highlight": ("bright", frozenset({"reverse"})),
    "status": ("normal", frozenset({"reverse"})),
    "status_inactive": ("normal", frozenset({"reverse", "dim"})),
    "message": ("normal", frozenset()),
    "message_warning": ("bright", frozenset({"bold"})),
    "message_error": ("bright", frozenset({"bold"})),
    "message_hint": ("normal", frozenset({"dim"})),
    "command": ("bright", frozenset({"bold"})),
    "command_hint": ("normal", frozenset({"dim"})),
    "menu": ("normal", frozenset()),
    "menu_selected": ("bright", frozenset({"reverse", "bold"})),
    "menu_border": ("bright", frozenset({"bold"})),
    "help": ("normal", frozenset()),
    "help_title": ("bright", frozenset({"bold"})),
    "border": ("normal", frozenset()),
    "keytest_ok": ("bright", frozenset({"bold"})),
}


@dataclass(frozen=True)
class Theme:
    name: str
    description: str
    # curses colour numbers to try in order (256-colour first, then 8-colour)
    foreground: tuple[int, ...]
    bright: tuple[int, ...]
    background: int = 0

    def style(self, role: str) -> tuple[str, frozenset[str]]:
        return _STYLES.get(role, _STYLES["text"])


THEMES: dict[str, Theme] = {
    "VT220": Theme("VT220", "white on black, like a DEC VT220", (250, 7), (231, 15, 7)),
    "AMBER": Theme("AMBER", "amber phosphor", (214, 172, 3), (220, 11, 3)),
    "GREEN": Theme("GREEN", "green phosphor", (40, 34, 2), (82, 10, 2)),
}

DEFAULT_THEME = "VT220"


def theme_names() -> list[str]:
    return list(THEMES)


def get_theme(name: str) -> Theme:
    return THEMES[name.upper()]

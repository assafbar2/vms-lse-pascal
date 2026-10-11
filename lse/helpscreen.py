"""The F1 keypad help screen: the VT220 keypad, labeled with modern keys.

Each keypad key shows three lines: the VT key, what it did in LSE, and
the key that does it here. The modern labels come from the live key map,
so the picture stays true if bindings change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .keys import describe_key

if TYPE_CHECKING:
    from .editor import Editor

CELL = 8

# (vt key, LSE function, command whose key is shown; None = literal label)
KEYPAD = [
    [("PF1", "GOLD", None, "Esc 0-9"), ("PF2", "HELP", "HELP INDICATED", None),
     ("PF3", "FINDNEXT", "FIND NEXT", None), ("PF4", "ERASE PH", "ERASE PLACEHOLDER", None)],
    [("7", "COMMAND", "COMMAND", None), ("8", "EXPAND", "TAB", None),
     ("9", "NEXT PH", "NEXT PLACEHOLDER", None), ("-", "PREV PH", "PREVIOUS PLACEHOLDER", None)],
    [("4", "COMPILE", "COMPILE", None), ("5", "REVIEW", "NEXT ERROR", None),
     ("6", "RUN", "BUILD", None), (",", "UNDO", "UNDO", None)],
    [("1", "WORD", "MOVE WORD RIGHT", None), ("2", "EOL", "MOVE LINE END", None),
     ("3", "GOTO LN", "GOTO LINE", None)],
]
ENTER = ("ENTER", "", "NEW LINE", None)
BOTTOM = [("0", "WRITE FILE", "WRITE FILE", None), (".", "QUIT", "QUIT", None)]

SIDE = [
    "The VT220 keypad LSE was made for,",
    "labeled with today's keys:",
    "  top line   = keypad key",
    "  middle     = what it did in LSE",
    "  bottom     = the key to press now",
    "",
    "Function keys",
    "  F1  Help        F3  Find next",
    "  F5  Compile, link and run",
    "  F7  Compile     F8  Next error",
    "  F10 LSE> command line",
    "Other keys",
    "  Ctrl-S Save     Ctrl-Q Quit",
    "  Ctrl-Z Undo     Ctrl-Y Redo",
    "  Ctrl-F Find     Ctrl-O Open file",
    "  Ctrl-W Window   Ctrl-B Buffers",
    "Terminal took a key?",
    "  Esc then 1-9, 0 = F1-F9, F10",
    "  Ctrl-P, type the command, Tab",
    "    completes it (LSE> COMPILE)",
    "  lse --keytest shows what works",
]


def short_key(key: str) -> str:
    text = describe_key(key)
    for long, short in (("Shift-", "Sh-"), ("Right", "Rt"), ("Left", "Lt"),
                        ("Delete", "Del"), ("PageUp", "PgUp"), ("PageDown", "PgDn")):
        text = text.replace(long, short)
    return text[:CELL]


def _modern(editor: "Editor", command: str | None, literal: str | None) -> str:
    if literal is not None:
        return literal
    keys = editor.keymap.keys_for(command or "")
    return short_key(keys[0]) if keys else "LSE>"


def _cells(editor: "Editor", row: list[tuple]) -> list[tuple[str, str, str]]:
    return [(k, f, _modern(editor, c, lit)) for k, f, c, lit in row]


def keypad_diagram(editor: "Editor") -> list[str]:
    """The keypad as box-drawing text (21 lines, 37 columns)."""
    bar = "─" * CELL
    out = ["┌" + "┬".join([bar] * 4) + "┐"]
    for i, row in enumerate(KEYPAD):
        cells = _cells(editor, row)
        if i < 3:
            for part in range(3):
                out.append("│" + "│".join(c[part].ljust(CELL) for c in cells) + "│")
            out.append("├" + "┼".join([bar] * 4) + "┤")
        else:
            enter = (ENTER[0], ENTER[1], "")
            for part in range(3):
                out.append("│" + "│".join(c[part].ljust(CELL) for c in cells)
                           + "│" + enter[part].ljust(CELL) + "│")
            out.append("├" + bar + "┴" + bar + "┼" + bar + "┤" + " " * CELL + "│")
    zero, dot = _cells(editor, BOTTOM)
    enter_key = _modern(editor, ENTER[2], ENTER[3])
    wide = CELL * 2 + 1
    for part in range(3):
        last = enter_key if part == 2 else ""
        out.append("│" + zero[part].ljust(wide) + "│" + dot[part].ljust(CELL)
                   + "│" + last.ljust(CELL) + "│")
    out.append("└" + "─" * wide + "┴" + bar + "┴" + bar + "┘")
    return out


def keypad_lines(editor: "Editor") -> list[str]:
    diagram = keypad_diagram(editor)
    width = len(diagram[0])
    lines = []
    for i in range(max(len(diagram), len(SIDE))):
        left = diagram[i] if i < len(diagram) else " " * width
        right = SIDE[i] if i < len(SIDE) else ""
        lines.append(f"{left}  {right}".rstrip())
    return lines

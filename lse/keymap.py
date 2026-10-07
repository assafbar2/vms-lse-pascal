"""The modern key profile: key names mapped to ``LSE>`` command lines.

Each binding is the text of a command, exactly as it could be typed at
the ``LSE>`` prompt, so every key has a command-line equivalent for
terminals that swallow the key (and Esc + digit covers F1-F10).
"""

from __future__ import annotations

from .keys import describe_key, normalize_key

MODERN_PROFILE: dict[str, str] = {
    # cursor movement
    "Up": "MOVE UP",
    "Down": "MOVE DOWN",
    "Left": "MOVE LEFT",
    "Right": "MOVE RIGHT",
    "C-Left": "MOVE WORD LEFT",
    "C-Right": "MOVE WORD RIGHT",
    "Home": "MOVE LINE START",
    "End": "MOVE LINE END",
    "C-Home": "GOTO TOP",
    "C-End": "GOTO BOTTOM",
    "PageUp": "MOVE PAGE UP",
    "PageDown": "MOVE PAGE DOWN",
    "C-g": "GOTO LINE",
    # editing
    "Enter": "NEW LINE",
    "Backspace": "DELETE PREVIOUS CHARACTER",
    "Delete": "DELETE CHARACTER",
    "Insert": "CHANGE MODE",
    "C-z": "UNDO",
    "C-y": "REDO",
    "C-f": "FIND",
    "F3": "FIND NEXT",
    # placeholders and templates
    "Tab": "TAB",
    "S-Tab": "PREVIOUS PLACEHOLDER",
    "C-n": "NEXT PLACEHOLDER",
    "C-e": "EXPAND",
    "C-k": "ERASE PLACEHOLDER",
    "C-Delete": "ERASE PLACEHOLDER",
    # files, buffers, windows
    "C-s": "WRITE FILE",
    "C-o": "GOTO FILE",
    "C-q": "QUIT",
    "C-w": "NEXT WINDOW",
    "C-b": "SHOW BUFFERS",
    # build
    "F5": "BUILD",
    "F7": "COMPILE",
    "F8": "NEXT ERROR",
    "S-F8": "PREVIOUS ERROR",
    # command line and help
    "C-p": "COMMAND",
    "F10": "COMMAND",
    "F1": "HELP INDICATED",
    "Esc": "CANCEL",
    "C-c": "CANCEL",
}


class Keymap:
    def __init__(self, bindings: dict[str, str] | None = None) -> None:
        self.bindings: dict[str, str] = dict(MODERN_PROFILE if bindings is None else bindings)

    def lookup(self, key: str) -> str | None:
        return self.bindings.get(key)

    def bind(self, key: str, command: str) -> None:
        self.bindings[normalize_key(key)] = command

    def unbind(self, key: str) -> None:
        self.bindings.pop(normalize_key(key), None)

    def keys_for(self, command: str) -> list[str]:
        want = " ".join(command.upper().split())
        return [k for k, c in self.bindings.items() if " ".join(c.upper().split()) == want]

    def describe_keys_for(self, command: str) -> str:
        return " or ".join(describe_key(k) for k in self.keys_for(command))

"""Key names, key-spec parsing and escape-sequence decoding.

A key is a plain string. Printable characters stand for themselves
(``"a"``, ``" "``, ``"%"``); every other key has a name:

    Enter Tab S-Tab Esc Backspace Delete C-Delete Insert
    Up Down Left Right Home End PageUp PageDown
    C-Left C-Right C-Up C-Down C-Home C-End
    F1 .. F20, S-F1 .. S-F12, C-a .. C-z

``KeyDecoder`` turns raw keys into editor keys. It implements the
fallback for terminals that steal function keys (Esc followed by a digit
acts as that F-key, Esc 0 = F10) and decodes VT100/xterm escape
sequences that curses did not recognise itself.
"""

from __future__ import annotations

import re

NAMED_KEYS = [
    "Enter", "Tab", "S-Tab", "Esc", "Backspace", "Delete", "C-Delete", "Insert",
    "Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown",
    "C-Left", "C-Right", "C-Up", "C-Down", "C-Home", "C-End", "C-Space",
    "S-Up", "S-Down", "S-Left", "S-Right",
]
NAMED_KEYS += [f"F{n}" for n in range(1, 21)]
NAMED_KEYS += [f"S-F{n}" for n in range(1, 13)]
NAMED_KEYS += [f"C-{c}" for c in "abcdefghijklmnopqrstuvwxyz"]

_CANON = {k.lower(): k for k in NAMED_KEYS}

_ALIASES = {
    "return": "Enter", "ret": "Enter", "cr": "Enter", "newline": "Enter",
    "escape": "Esc", "bs": "Backspace", "del": "Delete", "ins": "Insert",
    "pgup": "PageUp", "prior": "PageUp", "pgdn": "PageDown", "next": "PageDown",
    "backtab": "S-Tab", "space": " ", "spc": " ", "lt": "<", "gt": ">",
}

_MOD_WORDS = {"c": "C", "ctrl": "C", "control": "C", "s": "S", "shift": "S",
              "m": "M", "alt": "M", "meta": "M"}


def normalize_key(name: str) -> str:
    """Return the canonical key name for ``name``.

    Accepts the canonical form (``"C-s"``) and friendly spellings such as
    ``"Ctrl-S"``, ``"ctrl+s"``, ``"^S"``, ``"Shift-Tab"`` or ``"PgUp"``.
    A single printable character is returned unchanged.
    """
    if len(name) == 1:
        return name
    if name.startswith("^") and len(name) == 2:
        return "C-" + name[1].lower()
    low = name.lower()
    if low in _CANON:
        return _CANON[low]
    if low in _ALIASES:
        return _ALIASES[low]
    parts = re.split(r"[-+]", name)
    if len(parts) >= 2 and all(p.lower() in _MOD_WORDS for p in parts[:-1]):
        mods = "".join(sorted({_MOD_WORDS[p.lower()] for p in parts[:-1]}))
        base = normalize_key(parts[-1]) if parts[-1] else "-"
        if mods == "S" and base == "Tab":
            return "S-Tab"
        if len(base) == 1 and base.isalpha() and "C" in mods:
            return "C-" + base.lower()
        prefix = "-".join(mods)
        cand = f"{prefix}-{base}"
        return _CANON.get(cand.lower(), cand)
    raise ValueError(f"unknown key name: {name!r}")


def parse_keys(spec: str) -> list[str]:
    """Split a key spec such as ``"PROGRAM<Tab>Hello<C-s>"`` into keys.

    Text outside angle brackets is typed literally (a newline is Enter).
    ``<lt>`` types a literal ``<``.
    """
    keys: list[str] = []
    i = 0
    while i < len(spec):
        ch = spec[i]
        if ch == "<":
            j = spec.find(">", i + 2)
            if j > i + 1:
                keys.append(normalize_key(spec[i + 1:j]))
                i = j + 1
                continue
        keys.append("Enter" if ch == "\n" else ch)
        i += 1
    return keys


def is_printable(key: str) -> bool:
    return len(key) == 1 and key.isprintable()


def describe_key(key: str) -> str:
    """Human-readable key name for help screens: ``"C-s"`` -> ``"Ctrl-S"``."""
    if key == " ":
        return "Space"
    if len(key) == 1:
        return key
    out = key
    if key.startswith("C-"):
        rest = key[2:]
        out = "Ctrl-" + (rest.upper() if len(rest) == 1 else rest)
    elif key.startswith("S-"):
        out = "Shift-" + key[2:]
    return out


_CSI_TILDE = {
    "1": "Home", "2": "Insert", "3": "Delete", "4": "End", "5": "PageUp",
    "6": "PageDown", "7": "Home", "8": "End",
    "11": "F1", "12": "F2", "13": "F3", "14": "F4", "15": "F5", "17": "F6",
    "18": "F7", "19": "F8", "20": "F9", "21": "F10", "23": "F11", "24": "F12",
}
_CSI_LETTER = {"A": "Up", "B": "Down", "C": "Right", "D": "Left",
               "H": "Home", "F": "End", "P": "F1", "Q": "F2", "R": "F3", "S": "F4"}
_SS3 = {"A": "Up", "B": "Down", "C": "Right", "D": "Left", "H": "Home", "F": "End",
        "P": "F1", "Q": "F2", "R": "F3", "S": "F4", "M": "Enter"}
_LINUX_CONSOLE_F = {"A": "F1", "B": "F2", "C": "F3", "D": "F4", "E": "F5"}


def _with_modifier(base: str, mod: str) -> str:
    # xterm modifier parameter: 2 = Shift, 5 = Ctrl
    if mod == "2":
        cand = "S-" + base
    elif mod in ("5", "6"):
        cand = "C-" + base
    else:
        return base
    return _CANON.get(cand.lower(), base)


def decode_sequence(seq: str) -> str | None:
    """Decode the characters after ESC (``"[3;5~"``, ``"OP"``) to a key name."""
    if seq == "[Z":
        return "S-Tab"
    if seq.startswith("[[") and len(seq) == 3:
        return _LINUX_CONSOLE_F.get(seq[2])
    if seq.startswith("O") and len(seq) == 2:
        return _SS3.get(seq[1])
    if not seq.startswith("["):
        return None
    body, final = seq[1:-1], seq[-1]
    params = body.split(";") if body else []
    if final == "~" and params:
        base = _CSI_TILDE.get(params[0])
        if base is None:
            return None
        return _with_modifier(base, params[1]) if len(params) > 1 else base
    if final in _CSI_LETTER:
        base = _CSI_LETTER[final]
        return _with_modifier(base, params[1]) if len(params) > 1 else base
    return None


class KeyDecoder:
    """Turns raw keys into editor keys.

    * ``Esc`` then a digit becomes that F-key (``Esc 5`` = ``F5``,
      ``Esc 0`` = ``F10``), for terminals that keep F-keys for themselves.
    * ``Esc [ ... final`` / ``Esc O x`` sequences that curses passed through
      undecoded are translated (``Esc [ 3 ; 5 ~`` = ``C-Delete``).
    * A lone ``Esc`` is held until the next key or until ``flush()`` is
      called (the curses loop calls it after a short timeout).
    """

    HUMAN_DELAY = 0.1

    def __init__(self) -> None:
        self._pending: list[str] = []

    @property
    def waiting(self) -> bool:
        return bool(self._pending)

    def feed(self, key: str, elapsed: float | None = None) -> list[str]:
        """Feed one raw key; return the editor keys that are now complete.

        ``elapsed`` is the time since the previous raw key. When it is known
        and long, ``Esc [`` is treated as typed by a person, not a sequence.
        """
        p = self._pending
        if not p:
            if key == "Esc":
                self._pending = ["Esc"]
                return []
            return [key]
        if len(p) == 1:
            if len(key) == 1 and key.isdigit():
                self._pending = []
                return ["F10" if key == "0" else f"F{key}"]
            if key == "Esc":
                self._pending = []
                return ["Esc", "Esc"]
            if key in ("[", "O") and (elapsed is None or elapsed < self.HUMAN_DELAY):
                p.append(key)
                return []
            self._pending = []
            return ["Esc", key]
        if len(key) != 1:
            self._pending = []
            return ["Esc", *p[1:], key]
        p.append(key)
        seq = "".join(p[1:])
        if not self._sequence_complete(seq):
            if len(seq) > 12:
                self._pending = []
                return ["Esc", *seq]
            return []
        self._pending = []
        name = decode_sequence(seq)
        if name is None:
            return [f"Unknown:ESC{seq}"]
        return [name]

    @staticmethod
    def _sequence_complete(seq: str) -> bool:
        if seq.startswith("O"):
            return len(seq) >= 2
        if seq == "[[":
            return False
        if seq.startswith("[[") and len(seq) == 3:
            return True
        if len(seq) < 2:
            return False
        return 0x40 <= ord(seq[-1]) <= 0x7E

    def flush(self) -> list[str]:
        """Release a held Esc (and any partial sequence) after a timeout."""
        p, self._pending = self._pending, []
        return p

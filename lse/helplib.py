"""A VMS-style hierarchical HELP library (``lse/help/pascal.hlp``).

The file uses the VMS help-library layout: a line ``1 PASCAL`` starts a
top-level topic, ``2 IF`` a subtopic of it, ``3 Example`` a subtopic of
that, and every other line is text of the topic above it::

    1 PASCAL
     A small, readable programming language ...
    2 IF
     IF chooses between statements ...
    3 Example
       IF guess < secret THEN ...

``HELP PASCAL``, ``HELP PASCAL IF`` or ``HELP PAS LOOP WHILE`` (each word
may be abbreviated) opens the help viewer at that topic. In the viewer,
Up/Down pick a subtopic, Enter opens it, Backspace goes back up and Esc
leaves. ``HELP PASCAL MESSAGES`` also lists every compiler, linker and
run-time message with its explanation and hint, straight from the toolchain.
"""

from __future__ import annotations

import os
import re
import textwrap
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .keys import is_printable
from .overlays import Overlay

if TYPE_CHECKING:
    from .editor import Editor
    from .vscreen import VirtualScreen

HELP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help")
_HEADER = re.compile(r"^([1-9])\s+(\S.*?)\s*$")


@dataclass(eq=False)
class Topic:
    name: str
    level: int = 0
    text: list[str] = field(default_factory=list)
    children: list["Topic"] = field(default_factory=list)
    parent: "Topic | None" = None

    @property
    def path(self) -> list[str]:
        out: list[str] = []
        t: Topic | None = self
        while t is not None and t.level > 0:
            out.append(t.name)
            t = t.parent
        return list(reversed(out))

    @property
    def summary(self) -> str:
        for line in self.text:
            if line.strip():
                first = line.strip()
                m = re.match(r"(.+?[.!?])(\s|$)", first)
                return m.group(1) if m else first
        return ""

    def child(self, word: str) -> tuple["Topic | None", list["Topic"]]:
        """The subtopic ``word`` names (VMS abbreviation rules), and any ambiguity."""
        up = word.upper()
        exact = [c for c in self.children if c.name.upper() == up]
        if exact:
            return exact[0], []
        hits = [c for c in self.children if c.name.upper().startswith(up)]
        if len(hits) == 1:
            return hits[0], []
        return None, hits

    def find(self, words: list[str]) -> tuple["Topic", list[str], list["Topic"]]:
        """Follow ``words`` down; returns (deepest topic, words not found, ambiguous)."""
        t = self
        for i, w in enumerate(words):
            nxt, amb = t.child(w)
            if nxt is None:
                return t, words[i:], amb
            t = nxt
        return t, [], []


def parse(text: str) -> Topic:
    root = Topic("HELP", 0)
    stack = [root]
    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.startswith("!"):
            continue
        m = _HEADER.match(line)
        if m:
            level = int(m.group(1))
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1] if stack else root
            if level > parent.level + 1:
                level = parent.level + 1
            topic = Topic(m.group(2).upper(), level, parent=parent)
            parent.children.append(topic)
            stack.append(topic)
        else:
            stack[-1].text.append(line[1:] if line.startswith(" ") else line)
    _trim(root)
    return root


def _trim(t: Topic) -> None:
    while t.text and not t.text[-1].strip():
        t.text.pop()
    while t.text and not t.text[0].strip():
        t.text.pop(0)
    for c in t.children:
        _trim(c)


def load(name: str = "pascal") -> Topic:
    with open(os.path.join(HELP_DIR, name.lower() + ".hlp"), encoding="utf-8") as f:
        return parse(f.read())


def add_messages(root: Topic, messages: list[Any]) -> None:
    """Fill PASCAL MESSAGES with one subtopic per toolchain message."""
    pascal, _ = root.child("PASCAL")
    if pascal is None:
        return
    topic, _ = pascal.child("MESSAGES")
    if topic is None:
        topic = Topic("MESSAGES", pascal.level + 1, parent=pascal)
        pascal.children.append(topic)
    known = {c.name for c in topic.children}
    for m in sorted(messages, key=lambda m: (getattr(m, "ident", ""), getattr(m, "facility", ""))):
        ident = str(getattr(m, "ident", "")).upper()
        if not ident or ident in known:
            continue
        known.add(ident)
        fac = getattr(m, "facility", "?")
        sev = getattr(m, "severity", "?")
        template = re.sub(r"\{\w+\}", "...", str(getattr(m, "template", "")))
        body = [f"%{fac}-{sev}-{ident}, {template}", ""]
        body += textwrap.wrap(str(getattr(m, "explanation", "")), 74) + [""]
        hint = str(getattr(m, "hint", ""))
        if hint:
            body += textwrap.wrap("Hint: " + hint, 74, subsequent_indent="      ")
        topic.children.append(Topic(ident, topic.level + 1, body, parent=topic))


# ============================================================================
# The viewer
# ============================================================================


class HelpOverlay(Overlay):
    """Full-screen help: the topic's text, then its subtopics to pick from."""

    full_screen = True
    guidance_kind = "help"

    def __init__(self, topic: Topic, note: str = "") -> None:
        self.topic = topic
        self.note = note
        self.index = 0
        self.offset = 0
        self._rows = 10
        self._subtopic_rows: list[int] = []

    def _go(self, topic: Topic) -> None:
        self.topic = topic
        self.index = 0
        self.offset = 0
        self.note = ""

    def handle_key(self, editor: "Editor", key: str) -> None:
        kids = self.topic.children
        if key in ("Esc", "C-c", "C-q", "F1"):
            self.close(editor)
            editor.info("HELP", "back to your program (HELP PASCAL opens the Pascal help again)")
        elif key == "Enter" and kids:
            self._go(kids[self.index])
        elif key in ("Backspace", "Left"):
            if self.topic.parent is not None and self.topic.parent.level > 0:
                came_from = self.topic
                self._go(self.topic.parent)
                self.index = self.topic.children.index(came_from)
            else:
                self.close(editor)
                editor.info("HELP", "back to your program")
        elif key in ("Down", "C-n", "Tab", "Right"):
            if kids:
                self.index = (self.index + 1) % len(kids)
            else:
                self.offset += 1
        elif key in ("Up", "C-p", "S-Tab"):
            if kids:
                self.index = (self.index - 1) % len(kids)
            else:
                self.offset = max(0, self.offset - 1)
        elif key in ("PageDown", " "):
            self.offset += max(1, self._rows - 1)
        elif key == "PageUp":
            self.offset = max(0, self.offset - max(1, self._rows - 1))
        elif key == "Home":
            self.offset, self.index = 0, 0
        elif is_printable(key) and key.strip() and kids:
            ch = key.upper()
            order = list(range(self.index + 1, len(kids))) + list(range(0, self.index + 1))
            for i in order:
                if kids[i].name.startswith(ch):
                    self.index = i
                    break
        else:
            editor.show("Up/Down pick a topic, Enter opens it, Backspace goes back, Esc leaves.",
                        "I", log=False)

    def content(self, width: int) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        if self.note:
            lines += [(self.note, "help_title"), ("", "help")]
        for line in self.topic.text:
            if len(line) <= width:
                lines.append((line, "help"))
            else:
                indent = len(line) - len(line.lstrip())
                lines += [(w, "help") for w in textwrap.wrap(
                    line, width, subsequent_indent=" " * (indent + 2))]
        self._subtopic_rows = []
        kids = self.topic.children
        if kids:
            if lines:
                lines.append(("", "help"))
            lines.append(("Additional information available (Up/Down, then Enter):", "help_title"))
            name_w = max(len(k.name) for k in kids) + 2
            for i, k in enumerate(kids):
                self._subtopic_rows.append(len(lines))
                mark = ">" if i == self.index else " "
                text = f" {mark} {k.name:<{name_w}}{k.summary}"
                lines.append((text[:width], "menu_selected" if i == self.index else "help"))
        return lines

    def draw(self, editor: "Editor", scr: "VirtualScreen") -> None:
        h, w = scr.height, scr.width
        for r in range(h):
            scr.fill(r, "help")
        title = "HELP " + " ".join(self.topic.path)
        scr.box(0, 0, h, w, "border", title=title)
        inner = w - 4
        body = self.content(inner)
        rows = h - 3
        self._rows = rows
        if self._subtopic_rows:
            sel = self._subtopic_rows[self.index]
            if sel >= self.offset + rows:
                self.offset = sel - rows + 1
            elif sel < self.offset:
                self.offset = sel
        self.offset = max(0, min(self.offset, max(0, len(body) - rows)))
        for i in range(rows):
            idx = self.offset + i
            if idx >= len(body):
                break
            text, role = body[idx]
            if role == "menu_selected":
                scr.fill(1 + i, role, start=2, end=w - 2)
            scr.put(1 + i, 2, text[:inner], role)
        up = "Backspace: back to " + " ".join(self.topic.parent.path) \
            if self.topic.parent is not None and self.topic.parent.level > 0 else "Esc: back to LSE"
        footer = "Enter opens a topic.  " + up + ".  Esc leaves help."
        if self.offset + rows < len(body):
            footer += "  (more below)"
        scr.put(h - 2, 2, footer[:inner], "help_title")
        scr.regions["help"] = list(range(h))
        scr.cursor = None


def open_help(ed: "Editor", words: list[str]) -> None:
    root = getattr(ed, "help_library", None)
    if root is None:
        ed.warn("NOHELPLIB", "the Pascal help library is not installed")
        return
    topic, missing, ambiguous = root.find(words)
    note = ""
    if topic.level == 0:
        topic = root.children[0]
    if ambiguous:
        note = (f"\"{missing[0]}\" could be: " + ", ".join(t.name for t in ambiguous)
                + ". Pick one below.")
    elif missing:
        note = f"Sorry, there is no help on {' '.join(words)}. Here is {' '.join(topic.path)}."
    ed.push_overlay(HelpOverlay(topic, note))


def install(ed: "Editor") -> None:
    try:
        root = load("pascal")
    except OSError as e:
        ed.messages_buffer.append_line(f"help library: {e}")
        return
    try:
        if ed.toolchain.available:
            add_messages(root, ed.toolchain.all_messages())
    except Exception:
        pass
    ed.help_library = root
    for top in root.children:
        ed.help_topics[top.name] = (lambda name: lambda e, rest: open_help(
            e, [name] + rest.split()))(top.name)

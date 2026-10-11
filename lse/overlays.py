"""Modal overlays: prompts, questions, popup menus, text views, key test.

The editor keeps a stack of overlays; the top one gets every key until
it closes. Each overlay draws itself onto the virtual screen after the
windows and panels, so tests see exactly what a user would.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from .keys import describe_key, is_printable

if TYPE_CHECKING:
    from .commands import Completion
    from .editor import Editor
    from .vscreen import VirtualScreen


def page_height(scr: "VirtualScreen") -> int:
    """Rows a full-screen page may cover: all of them, or everything above the
    NEXT line when the guidance layer is on (NEXT, messages and keys stay visible)."""
    nxt = scr.regions.get("next")
    return nxt[0] if nxt else scr.height


class Overlay:
    #: True when the overlay covers the whole screen (help, key test)
    full_screen = False

    def handle_key(self, editor: "Editor", key: str) -> None:
        raise NotImplementedError

    def draw(self, editor: "Editor", scr: "VirtualScreen") -> None:
        raise NotImplementedError

    def close(self, editor: "Editor") -> None:
        editor.close_overlay(self)


class PromptOverlay(Overlay):
    """A one-line input on the command row (``LSE>``, ``Find:``, ``_File:``)."""

    def __init__(self, label: str, on_submit: Callable[[str], Any], *, initial: str = "",
                 completer: Callable[[str], "Completion"] | None = None,
                 history: list[str] | None = None, on_cancel: Callable[[], Any] | None = None,
                 close_keys: tuple[str, ...] = ()) -> None:
        self.label = label
        self.text = initial
        self.pos = len(initial)
        self.on_submit = on_submit
        self.completer = completer
        self.history = history
        self.hist_index: int | None = None
        self.on_cancel = on_cancel
        self.close_keys = close_keys

    def handle_key(self, editor: "Editor", key: str) -> None:
        t, p = self.text, self.pos
        if key == "Enter":
            self.close(editor)
            if self.history is not None and t.strip():
                if not self.history or self.history[-1] != t:
                    self.history.append(t)
            self.on_submit(t)
        elif key in ("Esc", "C-c") or key in self.close_keys:
            self.close(editor)
            if self.on_cancel:
                self.on_cancel()
            else:
                editor.info("CANCELLED", "cancelled")
        elif key == "Tab" and self.completer is not None:
            comp = self.completer(t[:p])
            self.text = comp.text + t[p:]
            self.pos = len(comp.text)
            if len(comp.candidates) > 1:
                shown = "  ".join(comp.candidates)
                editor.show(f"Possible completions: {shown}", "I", log=False)
            elif not comp.candidates:
                editor.show("No completions. Press Esc to leave the command line.", "I", log=False)
        elif key == "Backspace":
            if p > 0:
                self.text, self.pos = t[:p - 1] + t[p:], p - 1
        elif key == "Delete":
            self.text = t[:p] + t[p + 1:]
        elif key == "Left":
            self.pos = max(0, p - 1)
        elif key == "Right":
            self.pos = min(len(t), p + 1)
        elif key in ("Home", "C-a"):
            self.pos = 0
        elif key in ("End", "C-e"):
            self.pos = len(t)
        elif key == "C-u":
            self.text, self.pos = t[p:], 0
        elif key in ("Up", "Down") and self.history:
            h = self.history
            if self.hist_index is None:
                self.hist_index = len(h)
            self.hist_index += -1 if key == "Up" else 1
            self.hist_index = max(0, min(self.hist_index, len(h)))
            self.text = h[self.hist_index] if self.hist_index < len(h) else ""
            self.pos = len(self.text)
        elif is_printable(key):
            self.text, self.pos = t[:p] + key + t[p:], p + 1
        else:
            editor.show(f"{describe_key(key)} does nothing on the command line. "
                        "Enter runs it, Esc leaves.", "I", log=False)

    def draw(self, editor: "Editor", scr: "VirtualScreen") -> None:
        rows = scr.regions.get("command") or [scr.height - 1]
        row = rows[0]
        scr.fill(row, "command")
        width = scr.width - len(self.label) - 1
        start = max(0, self.pos - width + 1)
        scr.put(row, 0, self.label, "command")
        scr.put(row, len(self.label), self.text[start:start + width], "command")
        scr.cursor = (row, len(self.label) + self.pos - start)


class QuestionOverlay(Overlay):
    """A single-key question on the command row, e.g. save before quitting."""

    def __init__(self, question: str, answers: dict[str, Callable[[], Any]],
                 on_cancel: Callable[[], Any] | None = None) -> None:
        self.question = question
        self.answers = {k.lower(): v for k, v in answers.items()}
        self.on_cancel = on_cancel

    def handle_key(self, editor: "Editor", key: str) -> None:
        k = key.lower() if len(key) == 1 else key
        if k in self.answers:
            self.close(editor)
            self.answers[k]()
        elif key in ("Esc", "C-c"):
            self.close(editor)
            if self.on_cancel:
                self.on_cancel()
            else:
                editor.info("CANCELLED", "cancelled")
        else:
            keys = "/".join(a.upper() for a in self.answers)
            editor.show(f"Please answer {keys}, or press Esc to cancel.", "W", log=False)

    def draw(self, editor: "Editor", scr: "VirtualScreen") -> None:
        rows = scr.regions.get("command") or [scr.height - 1]
        row = rows[0]
        scr.fill(row, "command")
        end = scr.put(row, 0, self.question + " ", "command")
        scr.cursor = (row, min(end, scr.width - 1))


@dataclass
class MenuItem:
    label: str
    detail: str = ""
    value: Any = None


class MenuOverlay(Overlay):
    """A bordered popup list near the cursor; Up/Down, Enter, Esc."""

    def __init__(self, title: str, items: list[MenuItem], on_select: Callable[[MenuItem], Any], *,
                 on_cancel: Callable[[], Any] | None = None,
                 on_help: Callable[[MenuItem], Any] | None = None, selected: int = 0,
                 on_tab: Callable[[], Any] | None = None,
                 on_shift_tab: Callable[[], Any] | None = None) -> None:
        self.title = title
        self.items = items
        self.on_select = on_select
        self.on_cancel = on_cancel
        self.on_help = on_help
        self.on_tab = on_tab
        self.on_shift_tab = on_shift_tab
        self.index = selected
        self.scroll = 0
        self.visible = len(items)

    @property
    def current(self) -> MenuItem:
        return self.items[self.index]

    def handle_key(self, editor: "Editor", key: str) -> None:
        n = len(self.items)
        if key in ("Down", "C-n"):
            self.index = (self.index + 1) % n
        elif key in ("Up", "C-p"):
            self.index = (self.index - 1) % n
        elif key == "PageDown":
            self.index = min(n - 1, self.index + max(1, self.visible - 1))
        elif key == "PageUp":
            self.index = max(0, self.index - max(1, self.visible - 1))
        elif key == "Home":
            self.index = 0
        elif key == "End":
            self.index = n - 1
        elif key == "Tab" and self.on_tab is not None:
            self.close(editor)
            self.on_tab()
        elif key == "S-Tab" and self.on_shift_tab is not None:
            self.close(editor)
            self.on_shift_tab()
        elif key in ("Enter", "Tab"):
            self.close(editor)
            self.on_select(self.current)
        elif key in ("Esc", "C-c", "Left"):
            self.close(editor)
            if self.on_cancel:
                self.on_cancel()
        elif key == "F1" and self.on_help:
            self.on_help(self.current)
        elif is_printable(key) and key.strip():
            ch = key.upper()
            order = list(range(self.index + 1, n)) + list(range(0, self.index + 1))
            for i in order:
                if self.items[i].label.upper().startswith(ch):
                    self.index = i
                    break
            else:
                editor.show(f"No choice starts with {key!r}. Use Up/Down and Enter, Esc to cancel.",
                            "I", log=False)

    def draw(self, editor: "Editor", scr: "VirtualScreen") -> None:
        label_w = max(len(i.label) for i in self.items)
        detail_w = max((len(i.detail) for i in self.items), default=0)
        width = label_w + 4 + (detail_w + 2 if detail_w else 0)
        width = max(width, len(self.title) + 8, 24)
        width = min(width, scr.width)
        text_rows = scr.regions.get("text_area", list(range(scr.height - 2)))
        area_top, area_bottom = (text_rows[0], text_rows[-1]) if text_rows else (0, scr.height - 1)
        avail = area_bottom - area_top + 1
        height = min(len(self.items) + 2, max(3, avail))
        self.visible = height - 2
        crow, ccol = getattr(scr, "buffer_cursor", None) or (area_top, 0)
        top = crow + 1
        if top + height - 1 > area_bottom:
            top = max(area_top, crow - height)
        left = max(0, min(ccol, scr.width - width))
        if self.index < self.scroll:
            self.scroll = self.index
        elif self.index >= self.scroll + self.visible:
            self.scroll = self.index - self.visible + 1
        scr.box(top, left, height, width, "menu_border", title=self.title, fill_role="menu")
        for i in range(self.visible):
            idx = self.scroll + i
            if idx >= len(self.items):
                break
            item = self.items[idx]
            role = "menu_selected" if idx == self.index else "menu"
            row = top + 1 + i
            scr.fill(row, role, start=left + 1, end=left + width - 1)
            text = f" {item.label.ljust(label_w)}"
            if item.detail:
                text += f"  {item.detail}"
            room = width - 2
            if len(text) > room:
                text = text[: room - 3] + "..."
            scr.put(row, left + 1, text, role)
        scr.regions["menu"] = list(range(top, top + height))
        scr.cursor = (top + 1 + self.index - self.scroll, left + 2)


class TextViewOverlay(Overlay):
    """A full-screen bordered text page (help screens, listings)."""

    full_screen = True

    def __init__(self, title: str, lines: list[str], *,
                 footer: str = "Esc returns to your program.  Up/Down/PageUp/PageDown scroll.",
                 on_close: Callable[[], Any] | None = None, wrap: bool = True) -> None:
        self.title = title
        self.lines = lines
        self.footer = footer
        self.offset = 0
        self.on_close = on_close
        self.wrap = wrap
        self._page = 10

    def handle_key(self, editor: "Editor", key: str) -> None:
        if key in ("Esc", "Enter", "F1", "q", "Q", "C-c", "C-q"):
            self.close(editor)
            if self.on_close:
                self.on_close()
        elif key in ("Down", "C-n"):
            self.offset += 1
        elif key in ("Up", "C-p"):
            self.offset = max(0, self.offset - 1)
        elif key in ("PageDown", " "):
            self.offset += self._page
        elif key == "PageUp":
            self.offset = max(0, self.offset - self._page)
        elif key == "Home":
            self.offset = 0
        else:
            editor.show("Esc returns to your program.", "I", log=False)

    def _wrapped(self, width: int) -> list[str]:
        if not self.wrap:
            return list(self.lines)
        out: list[str] = []
        for line in self.lines:
            if len(line) <= width:
                out.append(line)
            else:
                indent = len(line) - len(line.lstrip())
                out.extend(textwrap.wrap(line, width, subsequent_indent=" " * (indent + 2))
                           or [""])
        return out

    def draw(self, editor: "Editor", scr: "VirtualScreen") -> None:
        h, w = page_height(scr), scr.width
        for r in range(h):
            scr.fill(r, "help")
        scr.box(0, 0, h, w, "border", title=self.title)
        inner = w - 4
        body = self._wrapped(inner)
        rows = h - 3
        self._page = max(1, rows - 1)
        self.offset = max(0, min(self.offset, max(0, len(body) - rows)))
        for i in range(rows):
            idx = self.offset + i
            if idx >= len(body):
                break
            scr.put(1 + i, 2, body[idx][:inner], "help")
        more = self.offset + rows < len(body)
        footer = self.footer + ("  (more below)" if more else "")
        scr.put(h - 2, 2, footer[:inner], "help_title")
        scr.regions["help"] = list(range(h))
        scr.cursor = None


KEYTEST_KEYS = [
    ("F1", "Help"), ("F3", "Find next"), ("F5", "Compile, link, run"), ("F7", "Compile"),
    ("F8", "Next error"), ("S-F8", "Previous error"), ("F10", "Command line"),
    ("Tab", "Expand / next placeholder"), ("S-Tab", "Previous placeholder"),
    ("C-k", "Erase placeholder"), ("C-Delete", "Erase placeholder"),
    ("C-s", "Save"), ("C-q", "Quit"), ("C-z", "Undo"), ("C-y", "Redo"),
    ("C-p", "Command line"), ("C-f", "Find"), ("C-g", "Go to line"),
    ("C-w", "Switch window"), ("C-b", "Buffer list"),
    ("Up", "Cursor up"), ("Down", "Cursor down"), ("Left", "Cursor left"),
    ("Right", "Cursor right"), ("Home", "Line start"), ("End", "Line end"),
    ("PageUp", "Page up"), ("PageDown", "Page down"),
    ("Backspace", "Delete left"), ("Delete", "Delete right"), ("Enter", "New line"),
]


class KeyTestOverlay(Overlay):
    """``lse --keytest``: shows which keys reach the editor."""

    full_screen = True

    def __init__(self, on_close: Callable[[], Any] | None = None) -> None:
        self.received: set[str] = set()
        self.last: str | None = None
        self.on_close = on_close
        self._esc = 0

    def handle_key(self, editor: "Editor", key: str) -> None:
        if key == "Esc":
            self._esc += 1
            if self._esc >= 2:
                self.close(editor)
                if self.on_close:
                    self.on_close()
                return
        else:
            self._esc = 0
        self.last = key
        self.received.add(key)

    def draw(self, editor: "Editor", scr: "VirtualScreen") -> None:
        h, w = scr.height, scr.width
        for r in range(h):
            scr.fill(r, "help")
        scr.box(0, 0, h, w, "border", title="Key test")
        put = scr.put
        put(1, 2, "Press keys to see whether they reach LSE. Press Esc twice to leave.", "help_title")
        if self.last is None:
            last = "Last key: (none yet)"
        else:
            cmd = editor.keymap.lookup(self.last)
            does = cmd if cmd else ("types the character" if is_printable(self.last) else "not used")
            last = f"Last key: {describe_key(self.last)}   ->   {does}"
        put(2, 2, last[: w - 4], "help")
        col_w = (w - 4) // 2
        rows_avail = h - 9
        for i, (key, label) in enumerate(KEYTEST_KEYS):
            col = i // rows_avail
            if col > 1:
                break
            row = 4 + i % rows_avail
            ok = key in self.received
            mark = "[x]" if ok else "[ ]"
            put(row, 2 + col * col_w, f"{mark} {describe_key(key):<11}{label}"[: col_w - 1],
                "keytest_ok" if ok else "help")
        put(h - 4, 2, "Keys that never show up are taken by your terminal. Use instead:", "help")
        put(h - 3, 2, "Esc then a digit = F-key (Esc 1 = F1 ... Esc 0 = F10).  Ctrl-P opens LSE>,"
            [: w - 4], "help")
        put(h - 2, 2, "where every action is a command (Tab completes). Example: LSE> COMPILE"
            [: w - 4], "help")
        scr.regions["keytest"] = list(range(h))
        scr.cursor = None

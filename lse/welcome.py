"""The welcome screen: what ``lse`` shows once the tutorial is finished.

``lse`` with no file name starts the tutorial until it has been finished
(``~/.lse/state`` remembers that); after that, and with ``--no-tutorial``,
it shows this screen: resume or restart the tutorial, a new file, open a
file, or quit. Up/Down and Enter choose; the first letter works too.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .commands import Command, complete_files
from .keys import is_printable
from .overlays import Overlay, page_height

if TYPE_CHECKING:
    from .editor import Editor
    from .vscreen import VirtualScreen

LOGO = [
    "#     ####  #####",
    "#     #     #    ",
    "#     ####  #### ",
    "#        #  #    ",
    "####  ####  #####",
]


@dataclass
class Choice:
    key: str
    label: str
    detail: str
    action: Callable[[], None]


class WelcomeOverlay(Overlay):
    full_screen = True
    guidance_kind = "welcome"

    def __init__(self, editor: "Editor") -> None:
        self.index = 0
        self.choices = self._choices(editor)

    def _choices(self, ed: "Editor") -> list[Choice]:
        tutor = getattr(ed, "tutor", None)
        out: list[Choice] = []
        if tutor is not None:
            tut_file = tutor.lesson.file
            if tutor.load_progress() and os.path.exists(tutor.path):
                where = f"step {tutor.index + 1} of {tutor.total}: {tutor.step.title}"
                out.append(Choice("r", "Resume the tutorial", where,
                                  lambda: self._then(ed, lambda: tutor.start(resume=True))))
            out.append(Choice("t", "Restart the tutorial",
                              f"Guess My Number from step 1 (in {tut_file})",
                              lambda: self._then(ed, tutor.restart)))
        out += [
            Choice("n", "New file", "start a new Pascal program from a template",
                   lambda: self._then(ed, lambda: _new_file(ed))),
            Choice("o", "Open file", "edit a file that is already there",
                   lambda: self._then(ed, lambda: ed.execute("GOTO FILE"))),
            Choice("q", "Quit", "leave LSE", lambda: self._then(ed, ed.request_quit)),
        ]
        return out

    def _then(self, ed: "Editor", fn: Callable[[], None]) -> None:
        self.close(ed)
        fn()

    def handle_key(self, editor: "Editor", key: str) -> None:
        n = len(self.choices)
        if key in ("Down", "C-n", "Tab"):
            self.index = (self.index + 1) % n
        elif key in ("Up", "C-p", "S-Tab"):
            self.index = (self.index - 1) % n
        elif key == "Home":
            self.index = 0
        elif key == "End":
            self.index = n - 1
        elif key == "Enter":
            self.choices[self.index].action()
        elif key in ("C-q",):
            self.close(editor)
            editor.request_quit()
        elif key in ("Esc", "C-c"):
            self.close(editor)
            editor.info("WELCOME", "Ctrl-O opens a file, Ctrl-P then TUTORIAL starts the "
                        "tutorial, Ctrl-Q quits")
        elif is_printable(key) and key.strip():
            for i, c in enumerate(self.choices):
                if c.key == key.lower():
                    self.index = i
                    c.action()
                    return
            editor.show("Use Up/Down and Enter, or the first letter of a choice.", "I", log=False)
        else:
            editor.show("Use Up/Down and Enter to choose; Ctrl-Q quits.", "I", log=False)

    def draw(self, editor: "Editor", scr: "VirtualScreen") -> None:
        w = scr.width
        box_h = max(3, page_height(scr))
        for r in range(box_h):
            scr.fill(r, "help")
        scr.box(0, 0, box_h, w, "border", title="LSE for Pascal")
        row = 1
        logo_w = max(len(l) for l in LOGO)
        if box_h >= len(self.choices) * 2 + len(LOGO) + 8:
            for line in LOGO:
                scr.put(row, (w - logo_w) // 2, line, "welcome_title")
                row += 1
            row += 1
        title = "Language-Sensitive Editor, VAX/VMS style, for Pascal"
        scr.put(row, max(2, (w - len(title)) // 2), title, "welcome_title")
        row += 2
        label_w = max(len(c.label) for c in self.choices) + 4
        left = max(2, (w - label_w - 40) // 2)
        for i, c in enumerate(self.choices):
            if row >= box_h - 2:
                break
            role = "welcome_selected" if i == self.index else "welcome_item"
            text = f" {c.label:<{label_w - 2}}"
            scr.put(row, left, text, role)
            scr.put(row, left + label_w + 1, c.detail[: max(0, w - left - label_w - 3)], "help")
            if i == self.index:
                scr.cursor = (row, left + 1)
            row += 2 if box_h > len(self.choices) * 2 + 6 else 1
        tip = "Up/Down and Enter choose. Ctrl-Q quits. F1 inside the editor always helps."
        if box_h - 2 > row:
            scr.put(box_h - 2, max(2, (w - len(tip)) // 2), tip[: w - 4], "help")
        scr.regions["welcome"] = list(range(box_h))


def _new_file(ed: "Editor") -> None:
    def submit(name: str) -> None:
        name = name.strip() or "PROGRAM.PAS"
        ed.execute(f'GOTO FILE "{name}"')

    def complete(partial: str):
        from .commands import Completion
        cands = complete_files(ed.cwd, partial)
        return Completion(cands[0] if len(cands) == 1 else partial, cands)

    ed.prompt("New file name [PROGRAM.PAS]: ", submit, completer=complete,
              on_cancel=lambda: show(ed))


def show(ed: "Editor") -> WelcomeOverlay:
    overlay = WelcomeOverlay(ed)
    ed.push_overlay(overlay)
    return overlay


def install(ed: "Editor") -> None:
    ed.commands.register(Command("WELCOME", lambda e, a: show(e),
                                 "Show the welcome screen (tutorial, new file, open file, quit).",
                                 group="Help"))

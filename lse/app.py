"""``lse`` command: start the editor in the terminal.

    lse HELLO.PAS        edit a file (a new file starts from the template)
    lse --keytest        show which keys reach the editor
    lse --theme AMBER    start with the amber (or GREEN) theme
"""

from __future__ import annotations

import argparse
import locale
import os
import sys
import time
from typing import Any

from . import __version__
from .host import Host, ProgramFn
from .themes import THEMES

IDLE_MS = 1000
ESC_WAIT_MS = 1000


class CursesHost(Host):
    """Suspends curses so a program can use the real terminal (RUN)."""

    def __init__(self, screen) -> None:
        self.screen = screen

    def run_program(self, before: str, after: str, fn: ProgramFn) -> Any:
        import curses

        curses.def_prog_mode()
        curses.endwin()
        out = sys.stdout
        out.write("\n" + before + "\n\n")
        out.flush()
        result = None
        try:
            result = fn(sys.stdin, sys.stdout)
        except KeyboardInterrupt:
            out.write("\n%LSE-W-INTERRUPTED, the program was stopped with Ctrl-C\n")
        out.write("\n" + after + "\n")
        out.flush()
        try:
            sys.stdin.readline()
        except (KeyboardInterrupt, EOFError):
            pass
        curses.reset_prog_mode()
        self.screen.stdscr.clear()
        self.screen.stdscr.refresh()
        return result

    def bell(self) -> None:
        import curses
        try:
            curses.beep()
        except curses.error:
            pass


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="lse", description="LSE-style editor for Pascal.")
    p.add_argument("file", nargs="?", help="file to edit, e.g. HELLO.PAS")
    p.add_argument("--keytest", action="store_true", help="show which keys reach the editor")
    p.add_argument("--theme", default="VT220", type=str.upper, choices=list(THEMES),
                   help="colour theme (VT220, AMBER or GREEN)")
    p.add_argument("--version", action="version", version=f"lse {__version__}")
    return p.parse_args(argv)


def start_editor(editor, args: argparse.Namespace) -> None:
    """Apply the command-line options to a fresh editor (shared with tests)."""
    from .overlays import KeyTestOverlay

    editor.theme = args.theme
    if args.keytest:
        editor.push_overlay(KeyTestOverlay(on_close=editor.request_quit))
    elif args.file:
        editor.execute(f'GOTO FILE "{args.file}"')
    else:
        editor.info("WELCOME", "LSE for Pascal. Ctrl-O opens a file, F1 shows the keys, "
                    "Ctrl-Q quits.")


def _run(stdscr, args: argparse.Namespace) -> None:
    from .editor import Editor
    from .screen import CursesScreen

    screen = CursesScreen(stdscr)
    h, w = screen.size()
    editor = Editor(cwd=os.getcwd(), host=CursesHost(screen), height=h, width=w)
    start_editor(editor, args)
    last = time.monotonic()
    while not editor.quit_requested:
        screen.apply_theme(editor.theme)
        screen.draw(editor.render(), editor.line_drawing)
        key = screen.read_key(ESC_WAIT_MS if editor.decoder.waiting else IDLE_MS)
        now = time.monotonic()
        if key is None:
            if editor.decoder.waiting:
                editor.flush_keys()
            else:
                editor.idle()
            continue
        if key == "Resize":
            editor.resize(*screen.size())
            continue
        editor.feed_key(key, now - last)
        last = now


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("lse: needs a terminal (run it in a terminal window, not through a pipe)",
              file=sys.stderr)
        return 2
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    import curses

    curses.wrapper(_run, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

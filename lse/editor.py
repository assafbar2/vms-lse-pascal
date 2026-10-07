"""The editor core: all state and behaviour, no curses.

``Editor`` owns the buffers, windows, key map, command registry, message
line and modal overlays. Keys go in through ``feed_key`` (raw terminal
keys, decoded for Esc + digit and escape sequences) or ``handle_key``
(already-decoded keys); ``render()`` returns a ``VirtualScreen``. The
curses app and the test harness both drive it exactly this way.

Extension points for later layers (tutor, NEXT line, key bar):

* ``commands.register(...)`` and ``keymap.bind(...)``
* ``after_key_hooks``: ``fn(editor, key)`` after every key
* ``idle_hooks``: ``fn(editor)`` when the terminal has been quiet a while
* ``status_providers``: ``fn(editor, window) -> str | None``, extra
  ``[ ... ]`` segments in the middle of each status line
* ``bottom_panels``: ordered ``(name, fn(editor, width) -> lines)`` list;
  insert e.g. ``("next", ...)`` before ``"command"`` and ``("keybar", ...)``
  after it. The rows land in ``VirtualScreen.regions[name]``.
* ``help_topics``: ``HELP <topic>`` handlers, ``fn(editor, rest)``
* ``builds``: per-source compile/link/run state for NEXT-line logic
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from . import files
from . import placeholders as ph
from .buffer import Buffer, ReadOnlyError
from .commands import CommandError, CommandRegistry, Completion, quote
from .host import HeadlessHost, Host
from .keymap import Keymap
from .keys import KeyDecoder, describe_key, is_printable
from .langdef import Language, LanguageRegistry
from .overlays import MenuItem, MenuOverlay, Overlay, PromptOverlay, QuestionOverlay, TextViewOverlay
from .themes import DEFAULT_THEME
from .toolchain import Toolchain, ToolchainUnavailable
from .windows import MAX_WINDOWS, Window

MAX_MESSAGE_LINES = 4


@dataclass
class Message:
    text: str
    severity: str = "I"
    hint: bool = False

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")


@dataclass
class BuildState:
    """What happened to one source file in the COMPILE / LINK / RUN cycle.

    The ``*_state`` fields hold the buffer ``state_id`` at the time, so a
    later layer can tell whether the source changed since (stale).
    """

    source: str
    compiled_state: int | None = None
    compile_ok: bool | None = None
    diagnostics: list[Any] = field(default_factory=list)
    obj_path: str | None = None
    linked_state: int | None = None
    link_ok: bool | None = None
    link_diagnostics: list[Any] = field(default_factory=list)
    exe_path: str | None = None
    map_path: str | None = None
    ran_state: int | None = None
    run_result: Any = None


@dataclass
class Review:
    diagnostics: list[Any]
    source: Buffer | None
    index: int = -1
    entry_rows: list[int] = field(default_factory=list)


@dataclass
class OverTyped:
    """A list placeholder the user just typed over (for duplication on expand)."""

    buffer: Buffer
    row: int
    col: int
    placeholder: ph.Placeholder


class Editor:
    def __init__(self, *, cwd: str | None = None, toolchain: Toolchain | None = None,
                 host: Host | None = None, languages: LanguageRegistry | None = None,
                 height: int = 24, width: int = 80, raise_errors: bool = False) -> None:
        from . import actions

        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.toolchain = toolchain or Toolchain()
        self.host = host or HeadlessHost()
        self.languages = languages or LanguageRegistry()
        self.height, self.width = height, width
        self.raise_errors = raise_errors

        self.keymap = Keymap()
        self.commands = CommandRegistry()
        self.decoder = KeyDecoder()
        self.help_topics: dict[str, Callable[["Editor", str], Any]] = {}
        actions.register_all(self)

        self.buffers: dict[str, Buffer] = {}
        self.messages_buffer = self.system_buffer("$MESSAGES")
        main = Buffer("MAIN")
        self.add_buffer(main)
        self.windows: list[Window] = [Window(main)]
        self.current_window = 0

        self.overlays: list[Overlay] = []
        self.message: Message | None = None
        self.insert_mode = True
        self.direction = "FORWARD"
        self.theme = DEFAULT_THEME
        self.explain_messages = True
        self.quit_requested = False
        self.last_search = ""
        self.command_history: list[str] = []
        self.typing_streak = False
        self._prev_typing = False
        self.overtyped: OverTyped | None = None
        self.builds: dict[str, BuildState] = {}
        self.review: Review | None = None
        self.on_quit: list[Callable[["Editor"], Any]] = []

        self.after_key_hooks: list[Callable[["Editor", str], Any]] = []
        self.idle_hooks: list[Callable[["Editor"], Any]] = []
        self.status_providers: list[Callable[["Editor", Window], str | None]] = []
        from .render import command_panel, message_panel
        self.bottom_panels: list[tuple[str, Callable[["Editor", int], list]]] = [
            ("message", message_panel),
            ("command", command_panel),
        ]
        self._message_this_key = False
        self.languages_errors_reported = False

    # ----- current window / buffer --------------------------------------------

    @property
    def window(self) -> Window:
        return self.windows[self.current_window]

    @property
    def buffer(self) -> Buffer:
        return self.window.buffer

    @property
    def language(self) -> Language | None:
        return self.buffer.language

    # ----- keys ---------------------------------------------------------------

    def feed_key(self, key: str, elapsed: float | None = None) -> None:
        """Feed a raw key from the terminal (goes through the Esc decoder)."""
        for k in self.decoder.feed(key, elapsed):
            self.handle_key(k)

    def flush_keys(self) -> None:
        """Release a pending lone Esc (call after a short quiet period)."""
        for k in self.decoder.flush():
            self.handle_key(k)

    def handle_key(self, key: str) -> None:
        """Process one decoded key."""
        self._message_this_key = False
        self._prev_typing = self.typing_streak
        self.typing_streak = False
        try:
            if key.startswith("Unknown:"):
                seq = key.split(":", 1)[1].replace("ESC", "Esc ")
                self.warn("UNKNOWNKEY", f"the terminal sent a key LSE does not know ({seq}). "
                          "Try Esc then a digit for F-keys, or Ctrl-P for commands.")
            elif self.overlays:
                self.overlays[-1].handle_key(self, key)
            else:
                command = self.buffer.local_keys.get(key) or self.keymap.lookup(key)
                if command:
                    self.execute(command)
                elif is_printable(key):
                    self.type_char(key)
                else:
                    self.show(f"{describe_key(key)} is not used in LSE. Press F1 to see the keys.",
                              "I", log=False)
        except Exception as e:  # never let a bug kill the editor session
            self._internal_error(e)
        self._after_key(key)

    def _after_key(self, key: str) -> None:
        if not self._message_this_key and not self.overlays:
            hint = self.placeholder_hint()
            if hint:
                self.message = Message(hint, "I", hint=True)
            elif self.message is not None and self.message.hint:
                self.message = None
        for hook in list(self.after_key_hooks):
            try:
                hook(self, key)
            except Exception as e:
                self._internal_error(e)

    def idle(self) -> None:
        for hook in list(self.idle_hooks):
            try:
                hook(self)
            except Exception as e:
                self._internal_error(e)

    def _internal_error(self, e: BaseException) -> None:
        if self.raise_errors:
            raise e
        self.messages_buffer.append_line(traceback.format_exc())
        self.show(f"%LSE-F-BUG, internal error: {type(e).__name__}: {e} "
                  "(details in buffer $MESSAGES)", "F")

    # ----- commands -----------------------------------------------------------

    def execute(self, text: str) -> bool:
        """Run one ``LSE>`` command line. Returns False if it could not be parsed."""
        text = text.strip()
        if not text:
            return False
        try:
            parsed = self.commands.parse(text, self)
        except CommandError as e:
            self.error(e.ident, e.text)
            return False
        if parsed.missing:
            param = parsed.missing[0]
            initial = param.initial(self) if param.initial else ""

            def submit(value: str, text: str = text) -> None:
                if value.strip() == "":
                    self.info("CANCELLED", f"{parsed.command.name} cancelled")
                    return
                self.execute(f"{text} {quote(value)}")

            def complete(partial: str, text: str = text) -> Completion:
                comp = self.commands.complete(f"{text} {partial}", self)
                return Completion(comp.text[len(text) + 1:], comp.candidates)

            self.prompt(param.prompt or f"_{param.name.capitalize()}: ", submit,
                        initial=initial, completer=complete)
            return True
        cmd = parsed.command
        if cmd.typing:
            self.typing_streak = True
        try:
            cmd.handler(self, parsed.args)
        except ReadOnlyError as e:
            self.warn("READONLY", f"buffer {e} is read-only; switch back with Ctrl-W or Ctrl-B")
        except ToolchainUnavailable as e:
            self.error("NOTOOLCHAIN", str(e))
        except CommandError as e:
            self.error(e.ident, e.text)
        return True

    def command_line(self) -> None:
        """Open the ``LSE>`` prompt."""
        def complete(partial: str) -> Completion:
            return self.commands.complete(partial, self)

        self.prompt("LSE> ", self.execute, completer=complete, history=self.command_history,
                    close_keys=("F10", "C-p"),
                    on_cancel=lambda: None)

    # ----- messages -----------------------------------------------------------

    def show(self, text: str, severity: str = "I", *, log: bool = True) -> None:
        self.message = Message(text, severity)
        self._message_this_key = True
        if log:
            self.messages_buffer.append_line(text)

    def _fmt(self, sev: str, ident: str, text: str) -> None:
        self.show(f"%LSE-{sev}-{ident}, {text}", sev)

    def info(self, ident: str, text: str) -> None:
        self._fmt("I", ident, text)

    def success(self, ident: str, text: str) -> None:
        self._fmt("S", ident, text)

    def warn(self, ident: str, text: str) -> None:
        self._fmt("W", ident, text)

    def error(self, ident: str, text: str) -> None:
        self._fmt("E", ident, text)

    def placeholder_hint(self) -> str | None:
        buf = self.buffer
        found = ph.placeholder_at(buf.lines, buf.row, buf.col)
        if found is None:
            return None
        lang = buf.language
        defn = lang.placeholder(found.name) if lang else None
        if defn is None:
            return f"{found.text}: placeholder. Type over it, Tab for the next one, Ctrl-K to erase."
        action = {"MENU": "Tab: choose", "NONTERMINAL": "Tab: expand",
                  "TERMINAL": "type over it"}[defn.type]
        head = f"{found.text}: {defn.summary}"
        example = f"  e.g. {defn.example[0].strip()}" if defn.example else ""
        tail = f"  ({action}, F1: more)"
        for text in (head + example + tail, head + tail, head + example, head):
            if len(text) <= self.width:
                return text
        return head

    # ----- overlays -----------------------------------------------------------

    def push_overlay(self, overlay: Overlay) -> Overlay:
        self.overlays.append(overlay)
        return overlay

    def close_overlay(self, overlay: Overlay) -> None:
        if overlay in self.overlays:
            self.overlays.remove(overlay)

    def prompt(self, label: str, on_submit: Callable[[str], Any], **kw: Any) -> PromptOverlay:
        return self.push_overlay(PromptOverlay(label, on_submit, **kw))  # type: ignore[return-value]

    def ask(self, question: str, answers: dict[str, Callable[[], Any]],
            on_cancel: Callable[[], Any] | None = None) -> QuestionOverlay:
        return self.push_overlay(QuestionOverlay(question, answers, on_cancel))  # type: ignore[return-value]

    def menu(self, title: str, items: list[MenuItem], on_select: Callable[[MenuItem], Any],
             **kw: Any) -> MenuOverlay:
        return self.push_overlay(MenuOverlay(title, items, on_select, **kw))  # type: ignore[return-value]

    def view_text(self, title: str, lines: list[str], **kw: Any) -> TextViewOverlay:
        return self.push_overlay(TextViewOverlay(title, lines, **kw))  # type: ignore[return-value]

    # ----- buffers ------------------------------------------------------------

    def add_buffer(self, buf: Buffer) -> Buffer:
        name = buf.name
        n = 2
        while name in self.buffers and self.buffers[name] is not buf:
            name = f"{buf.name}<{n}>"
            n += 1
        buf.name = name
        self.buffers[name] = buf
        return buf

    def system_buffer(self, name: str) -> Buffer:
        buf = self.buffers.get(name)
        if buf is None:
            buf = Buffer(name, read_only=True, system=True)
            self.buffers[name] = buf
        return buf

    def find_file_buffer(self, path: str) -> Buffer | None:
        for buf in self.buffers.values():
            if buf.path and os.path.normcase(buf.path) == os.path.normcase(path):
                return buf
        return None

    def open_file(self, name: str, *, window: Window | None = None) -> Buffer:
        """Open (or switch to) a file; a new file gets the language's initial template."""
        path = files.resolve_name(self.cwd, name, default_type=".PAS")
        base, ver = files.split_version(path)
        existing = self.find_file_buffer(base)
        if existing is not None and ver is None:
            self.show_buffer(existing, window)
            self.info("BUFFER", f"now editing {existing.display_name}")
            return existing
        base, lines, version = files.load(path)
        lang = self.languages.for_file(base)
        new_file = lines is None
        if new_file:
            lines = list(lang.initial_string) if lang and lang.initial_string else [""]
        buf = Buffer(os.path.basename(base), lines, path=base, version=version, language=lang)
        self.add_buffer(buf)
        self.show_buffer(buf, window)
        if new_file:
            found = ph.scan(buf.lines)
            first = found[0] if found else None
            if first:
                buf.set_cursor(first.row, first.start)
            self.info("NEWFILE", f"{self.relative(base)} is a new file"
                      + (" (Tab expands the template)" if first else ""))
        else:
            n = len(buf.lines)
            src = files.versioned_name(self.relative(base), version) if version else self.relative(base)
            self.info("READ", f"{n} line{'s' if n != 1 else ''} read from file {src}")
        return buf

    def show_buffer(self, buf: Buffer, window: Window | None = None) -> None:
        win = window or self.window
        old = win.buffer
        win.buffer = buf
        if old is not buf:
            win.top = 0
            win.left = 0
        main = self.buffers.get("MAIN")
        if (main is not None and main is old and main is not buf and not main.path
                and not main.modified and main.lines == [""]
                and all(w.buffer is not main for w in self.windows)):
            del self.buffers["MAIN"]

    def relative(self, path: str) -> str:
        try:
            rel = os.path.relpath(path, self.cwd)
        except ValueError:
            return path
        return path if rel.startswith("..") else rel

    def file_buffers(self) -> list[Buffer]:
        return [b for b in self.buffers.values() if not b.system]

    def modified_buffers(self) -> list[Buffer]:
        return [b for b in self.file_buffers() if b.modified]

    # ----- windows ------------------------------------------------------------

    def split(self, buffer: Buffer | None = None, *, fixed_height: int | None = None) -> Window:
        """Make sure there are two windows; show ``buffer`` in the other one."""
        if len(self.windows) < MAX_WINDOWS:
            win = Window(buffer or self.buffer, fixed_height=fixed_height)
            self.windows.append(win)
        else:
            win = self.windows[1 - self.current_window]
            if buffer is not None:
                self.show_buffer(buffer, win)
            win.fixed_height = fixed_height
        return win

    def other_window(self) -> Window | None:
        if len(self.windows) < 2:
            return None
        return self.windows[1 - self.current_window]

    def window_showing(self, buf: Buffer) -> Window | None:
        for w in self.windows:
            if w.buffer is buf:
                return w
        return None

    def select_window(self, win: Window) -> None:
        self.current_window = self.windows.index(win)

    def one_window(self) -> None:
        keep = self.window
        self.windows = [keep]
        keep.fixed_height = None
        self.current_window = 0

    def close_window(self, win: Window) -> None:
        if len(self.windows) > 1 and win in self.windows:
            current = self.window
            self.windows.remove(win)
            self.current_window = self.windows.index(current) if current in self.windows else 0
            self.windows[0].fixed_height = None

    # ----- typing -------------------------------------------------------------

    def type_char(self, ch: str) -> None:
        """Self-insert a printable character (typing over a placeholder erases it)."""
        buf = self.buffer
        if buf.read_only:
            self.warn("READONLY", f"buffer {buf.name} is read-only; Ctrl-W goes back to your file")
            return
        if not self._prev_typing:
            found = ph.placeholder_at(buf.lines, buf.row, buf.col)
            if found is not None:
                with buf.change():
                    buf.delete(found.row, found.start, found.row, found.end)
                buf.set_cursor(found.row, found.start)
                if found.is_list:
                    self.overtyped = OverTyped(buf, found.row, found.start, found)
        row, col = buf.cursor
        line = buf.lines[row]
        if not self.insert_mode and col < len(line):
            with buf.change(group=("over", row, col), next_group=("over", row, col + 1)):
                buf.replace_line(row, line[:col] + ch + line[col + 1:])
        else:
            with buf.change(group=("type", row, col), next_group=("type", row, col + 1)):
                buf.insert(row, col, ch)
        buf.set_cursor(row, col + 1)
        self.typing_streak = True

    def ensure_writable(self) -> bool:
        if self.buffer.read_only:
            self.warn("READONLY", f"buffer {self.buffer.name} is read-only; "
                      "Ctrl-W goes back to your file")
            return False
        return True

    # ----- build state --------------------------------------------------------

    def build_for(self, buf: Buffer) -> BuildState:
        key = buf.path or buf.name
        st = self.builds.get(key)
        if st is None:
            st = self.builds[key] = BuildState(source=key)
        return st

    # ----- display ------------------------------------------------------------

    def resize(self, height: int, width: int) -> None:
        self.height, self.width = max(4, height), max(20, width)

    def render(self):
        from .render import render
        return render(self)

    def request_quit(self) -> None:
        self.quit_requested = True
        for fn in list(self.on_quit):
            fn(self)

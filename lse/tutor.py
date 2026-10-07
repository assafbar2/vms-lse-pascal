"""The tutor: runs a lesson (``lse/lessons/*.lesson``) inside the editor.

The screen splits in two: the user's own program on top, and a bordered
LESSON window below with the current step::

    ┌[ Lesson 4 of 10: Variables: boxes that hold values ]──────────────┐
    │ A variable is a named box that holds a value. ...                 │
    │ DO THIS:                                                          │
    │  [x] 1. Go to the end of line 1, press Enter, type VAR, Tab.      │
    │  ==> 2. Type secret, guess, tries and press Tab.                  │
    │  [ ] 3. ...                                                       │
    │ YOU WILL SEE: VAR and secret, guess, tries : INTEGER; ...         │
    └───────────────────────────────────────────────────────────────────┘

* Checks run after every key (and on F2). A DO item is done when its
  checks pass; the step moves on by itself once everything passes.
* The NEXT line shows the current DO item (or, if the program has a
  mistake somewhere else, how to find it).
* Earlier steps are checked again: if something they built is gone (the
  VAR line was deleted, say), the NEXT line says so and F4 puts it back.
* F4 gives escalating help: the hint lines of the step, then "show me",
  which previews the step's finished program and puts it in on Enter.
* No progress for a minute, or two failed checks or compiles, and the
  NEXT line says "Stuck? Press F4 for a hint."
* Ctrl-L hides or shows the lesson; while it is hidden the status line
  says "Lesson 4/10". ``TUTORIAL`` brings it back, ``TUTORIAL OFF`` stops.
* Progress is saved next to the program (``GUESS.TUT``), so ``lse``
  resumes at the same step. ``~/.lse/state`` remembers a finished tutorial.
"""

from __future__ import annotations

import atexit
import difflib
import os
import re
import shutil
import tempfile
import textwrap
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import lesson as lessonfile
from . import placeholders as ph
from .commands import Args, Command, Param
from .guidance import build_states
from .lesson import Check, Lesson, Step
from .overlays import MenuItem, TextViewOverlay
from .userstate import UserState

if TYPE_CHECKING:
    from .buffer import Buffer
    from .editor import Editor
    from .windows import Window

IDLE_NUDGE_SECONDS = 60
STUCK_FAILURES = 2
LESSON_BUFFER = "$LESSON"
STUCK = "Stuck? Press F4 for a hint. "


@dataclass
class Result:
    ok: bool
    why: str = ""


@dataclass
class StepStatus:
    done: list[bool] = field(default_factory=list)
    current: int | None = None
    failing: tuple[Check, str] | None = None
    passed: bool = False


@dataclass
class _Context:
    buf: "Buffer"
    text: str
    state_id: int
    _parsed: Any = None
    _did_parse: bool = False

    def parsed(self, tutor: "Tutor") -> Any:
        if not self._did_parse:
            self._did_parse = True
            self._parsed = tutor.parse(self.text, self.state_id)
        return self._parsed

    def ast(self, tutor: "Tutor") -> Any:
        p = self.parsed(tutor)
        return getattr(p, "ast", None) if p is not None else None

    def errors(self, tutor: "Tutor", severities: str = "EF") -> list[Any]:
        """Problems the compiler would report, apart from leftover placeholders."""
        p = self.parsed(tutor)
        if p is None:
            return []
        return [d for d in p.diagnostics if str(getattr(d, "severity", "E")) in severities
                and getattr(d, "ident", "") != "PLACEHOLDER"]


class PreviewOverlay(TextViewOverlay):
    """'Show me': the step's program with the changes marked; Enter puts it in."""

    guidance_kind = "preview"

    def __init__(self, title: str, lines: list[str], on_accept, on_cancel) -> None:
        super().__init__(title, lines, wrap=False,
                         footer="Enter puts this into your program.  Esc keeps yours.  "
                                "(+ = added, - = taken out)")
        self.on_accept = on_accept
        self.on_cancel_ = on_cancel

    def handle_key(self, editor: "Editor", key: str) -> None:
        if key == "Enter":
            self.close(editor)
            self.on_accept()
        elif key in ("Esc", "C-c", "q", "Q", "C-q", "F1"):
            self.close(editor)
            self.on_cancel_()
        else:
            super().handle_key(editor, key)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _show_input(text: str) -> str:
    parts = [p for p in text.split("\n") if p != ""]
    if len(parts) > 4:
        parts = parts[:3] + ["..."]
    return ", ".join(parts)


class Tutor:
    def __init__(self, editor: "Editor", lesson: Lesson, *,
                 user_state: UserState | None = None) -> None:
        self.ed = editor
        self.lesson = lesson
        self.user_state = user_state or UserState()
        self.active = False
        self.visible = True
        self.index = 0
        self.hint_level = 0
        self.latches: set[str] = set()
        self.fails = 0
        self.last_progress = editor.clock()
        self.window: "Window | None" = None
        self.regression: tuple[int, Check, str] | None = None
        self.status = StepStatus()
        self._done_count = 0
        self._parse_cache: tuple[int, str, Any] | None = None
        self._durable_cache: dict[tuple[int, int, int], Result] = {}
        self._runs: dict[tuple[int, str, int | None], tuple[bool, str]] = {}
        self._tmp: str | None = None
        self._finished_now = False

    # ----- where things are ---------------------------------------------------

    @property
    def path(self) -> str:
        return os.path.join(self.ed.cwd, self.lesson.file)

    @property
    def progress_path(self) -> str:
        return os.path.splitext(self.path)[0] + ".TUT"

    @property
    def step(self) -> Step:
        return self.lesson.steps[self.index]

    @property
    def total(self) -> int:
        return len(self.lesson.steps)

    @property
    def finished(self) -> bool:
        return self.step.final

    @property
    def ever_finished(self) -> bool:
        return self._finished_now or self.user_state.tutorial_finished

    def source(self) -> "Buffer | None":
        return self.ed.find_file_buffer(self.path)

    @property
    def lesson_buffer(self) -> "Buffer":
        return self.ed.system_buffer(LESSON_BUFFER)

    def lesson_window(self) -> "Window | None":
        for w in self.ed.windows:
            if w.buffer is self.lesson_buffer:
                return w
        return None

    @property
    def shown(self) -> bool:
        return self.lesson_window() is not None

    # ----- starting and stopping ----------------------------------------------

    def start(self, *, resume: bool = True) -> None:
        """TUTORIAL: start, or pick up where the user left off."""
        ed = self.ed
        had_progress = resume and self.load_progress()
        existed = os.path.exists(self.path)
        if ed.window is self.lesson_window():
            other = ed.other_window()
            if other is not None:
                ed.select_window(other)
        buf = self.source()
        if buf is None:
            ed.open_file(self.lesson.file)
            buf = self.source()
        else:
            ed.show_buffer(buf)
        self.active = True
        self.visible = True
        self.update()
        n = self.index + 1
        if had_progress and self.index > 0:
            ed.info("TUTORIAL", f"welcome back: step {n} of {self.total}, {self.step.title}. "
                    "The lesson window below says what to do")
        else:
            ed.info("TUTORIAL", f"step {n} of {self.total}: {self.step.title}. "
                    "Read the lesson window below; NEXT says what to press")
        if not had_progress and existed and buf is not None and not self._is_blank(buf):
            self._offer_fresh_file(buf)

    def _is_blank(self, buf: "Buffer") -> bool:
        lang = buf.language
        initial = list(lang.initial_string) if lang and lang.initial_string else [""]
        return [l.strip() for l in buf.lines if l.strip()] in ([], [i.strip() for i in initial])

    def _offer_fresh_file(self, buf: "Buffer") -> None:
        self.ed.ask(f"{self.lesson.file} already has a program in it. Start the tutorial with "
                    "an empty one? Y = yes (the old one stays as a version), N = keep it",
                    {"y": lambda: self._blank_file(buf), "n": lambda: self.ed.info(
                        "TUTORIAL", f"keeping {self.lesson.file} as it is")},
                    on_cancel=lambda: None)

    def _blank_file(self, buf: "Buffer") -> None:
        lang = buf.language
        initial = list(lang.initial_string) if lang and lang.initial_string else [""]
        if buf.modified or not self._is_blank(buf):
            if buf.modified:
                buf.save()
            with buf.change():
                buf.set_lines(initial)
            buf.save()
        found = ph.scan(buf.lines)
        buf.set_cursor(*(found[0].row, found[0].start) if found else (0, 0))
        self.update()
        self.ed.info("TUTORIAL", f"{self.lesson.file} is empty again (the old program is "
                     f"saved as {self.lesson.file};{max(1, (buf.version or 1) - 1)})")

    def stop(self) -> None:
        """TUTORIAL OFF."""
        if not self.active:
            self.ed.info("TUTORIAL", "the tutorial is not running (TUTORIAL starts it)")
            return
        self.save()
        self.active = False
        self.sync_window()
        self.ed.info("TUTORIAL", f"tutorial paused at step {self.index + 1}. TUTORIAL picks it "
                     "up again; your program stays as it is")

    def restart(self) -> None:
        def go() -> None:
            self.goto(0)
            buf = self.source()
            if buf is not None:
                self._blank_file(buf)
            if not self.active:
                self.start(resume=True)
            self.ed.info("TUTORIAL", f"back to step 1 of {self.total}: {self.step.title}")

        buf = self.source()
        if buf is None and os.path.exists(self.path):
            self.ed.open_file(self.lesson.file)
            buf = self.source()
        if buf is not None and not self._is_blank(buf):
            self.ed.ask(f"Start the tutorial again with an empty {self.lesson.file}? "
                        "Y = yes (the old one stays as a version), N = no",
                        {"y": go, "n": lambda: self.ed.info("CANCELLED", "tutorial unchanged")},
                        on_cancel=lambda: self.ed.info("CANCELLED", "tutorial unchanged"))
        else:
            go()

    def goto(self, index: int, *, load_solution: bool = False) -> None:
        self.index = max(0, min(index, self.total - 1))
        self._enter_step()
        if load_solution and self.index > 0:
            prev = self.lesson.steps[self.index - 1].solution
            buf = self.source()
            if prev is not None and buf is not None:
                with buf.change():
                    buf.set_lines(prev)
                buf.save()
        self.save()
        self.update()

    def _enter_step(self) -> None:
        self.latches = set()
        self.hint_level = 0
        self.fails = 0
        self.last_progress = self.ed.clock()
        self._done_count = 0
        self.regression = None
        if self.window is not None:
            self.window.top = 0
        if self.step.final:
            self._finished_now = True
            self.user_state.mark_tutorial_finished()

    # ----- progress file --------------------------------------------------------

    def save(self) -> None:
        lines = ["! LSE tutorial progress. Delete this file to start the tutorial again.",
                 f"LESSON {self.lesson.name}",
                 f"STEP {self.index + 1} {self.step.id}",
                 f"HINT {self.hint_level}"]
        lines += [f"LATCH {k}" for k in sorted(self.latches & self._needed_latches())]
        try:
            tmp = self.progress_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, self.progress_path)
        except OSError:
            pass

    def load_progress(self) -> bool:
        try:
            with open(self.progress_path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return False
        index, hint, latches = None, 0, set()
        for line in text.split("\n"):
            words = line.split()
            if not words or words[0].startswith("!"):
                continue
            key = words[0].upper()
            if key == "STEP" and len(words) >= 2:
                if len(words) >= 3:
                    index = self.lesson.index_of(words[2])
                if index is None:
                    try:
                        index = int(words[1]) - 1
                    except ValueError:
                        index = None
            elif key == "HINT" and len(words) == 2 and words[1].isdigit():
                hint = int(words[1])
            elif key == "LATCH" and len(words) >= 2:
                latches.add(" ".join(words[1:]).upper())
        if index is None or not 0 <= index < self.total:
            return False
        self.index = index
        self._enter_step()
        self.hint_level = hint
        self.latches = latches
        return True

    # ----- parsing and checks ---------------------------------------------------

    def parse(self, text: str, state_id: int) -> Any:
        if self._parse_cache and self._parse_cache[0] == state_id and self._parse_cache[1] == text:
            return self._parse_cache[2]
        try:
            result = self.ed.toolchain.parse(text, self.path)
        except Exception:
            result = None
        self._parse_cache = (state_id, text, result)
        return result

    def _context(self) -> _Context | None:
        buf = self.source()
        if buf is None:
            return None
        return _Context(buf, buf.text, buf.state_id)

    def check(self, c: Check, ctx: _Context) -> Result:
        res = self._check(c, ctx)
        if not res.ok and c.quals.get("FAIL"):
            return Result(False, c.quals["FAIL"])
        return res

    def _check(self, c: Check, ctx: _Context) -> Result:
        kind, args = c.kind, c.args
        if c.latched:
            if c.key in self.latches:
                return Result(True)
            return Result(False, {
                "COMPILE_FAILED": "you have not compiled it with the mistake in it yet (F7)",
                "MADE_ERROR": "the program has no mistake in it yet",
                "REVIEWED": "you have not used F8 to go to the error yet",
                "FILE_OPENED": f"you have not opened {args[0] if args else 'the file'} yet "
                               "(Ctrl-O)",
            }[kind])
        if kind == "CONTAINS_TEXT":
            ok = args[0].lower() in ctx.text.lower()
            return Result(ok, f'the program does not contain "{args[0]}" yet')
        if kind == "CONTAINS_WORD":
            ok = re.search(rf"(?<![\w$]){re.escape(args[0])}(?![\w$])", ctx.text, re.I) is not None
            return Result(ok, f"the program has no {args[0]} yet")
        if kind == "NO_PLACEHOLDERS":
            n = ph.count(ctx.buf.lines)
            return Result(n == 0, f"{_plural(n, 'placeholder')} still to fill in or erase "
                          "(Tab finds them, Ctrl-K erases one)")
        if kind in ("PROGRAM_NAME", "DECLARES", "CONTAINS_STATEMENT", "NO_ERRORS"):
            return self._ast_check(c, ctx)
        if kind in ("COMPILES", "LINKS", "RAN"):
            return self._build_check(c, ctx)
        if kind == "RUN_OUTPUT_CONTAINS":
            return self._run_check(c, ctx)
        if kind == "EDITING":
            want = args[0].upper()
            lesson_win = self.lesson_window()
            wins = [self.ed.window] if self.ed.window is not lesson_win else \
                [w for w in self.ed.windows if w is not lesson_win]
            ok = any(os.path.basename(w.buffer.path or w.buffer.name).upper() == want for w in wins)
            return Result(ok, f"{args[0]} is not in the window (Ctrl-O then Enter goes back)")
        return Result(False, f"unknown check {kind}")

    def _ast_check(self, c: Check, ctx: _Context) -> Result:
        ast = ctx.ast(self)
        kind, args = c.kind, c.args
        if kind == "NO_ERRORS":
            errs = ctx.errors(self)
            if not errs:
                return Result(True)
            d = errs[0]
            return Result(False, f"line {getattr(d, 'line', '?')} has a mistake: "
                          f"{_headline(d)} (F7, then F8 goes there)")
        if ast is None:
            return Result(False, "there is no PROGRAM yet (Tab on %{compilation_unit}% picks one)")
        if kind == "PROGRAM_NAME":
            name = getattr(ast, "name", "")
            ok = getattr(ast, "unit", "PROGRAM") == "PROGRAM" and name.upper() == args[0].upper()
            return Result(ok, f"the program is called {name}, not {args[0]}" if name and
                          not name.startswith("%") else f"the program has no name yet")
        if kind == "DECLARES":
            declares = getattr(ast, "declares", None)
            ok = bool(declares and declares(args[0], args[1] if len(args) > 1 else None))
            what = f" as {args[1]}" if len(args) > 1 else ""
            return Result(ok, f"{args[0]} is not declared{what} in a VAR section yet")
        try:
            ok = any(self.ed.toolchain.find_statements(ast, p) for p in args)
        except Exception:
            ok = False
        return Result(ok, f"the program has no  {pattern_summary(args[0])}  yet")

    def _build_check(self, c: Check, ctx: _Context) -> Result:
        s = build_states(self.ed, ctx.buf)
        if c.kind == "COMPILES":
            if s["compiled"] in ("ok", "warnings"):
                return Result(True)
            if s["compiled"] == "failed":
                return Result(False, "the last compile found mistakes (F8 shows them)")
            return Result(False, "it has not been compiled since your last change (F7)")
        if c.kind == "LINKS":
            if s["linked"] == "ok":
                return Result(True)
            return Result(False, "it has not been linked since your last change (F5)")
        ran = s["ran"]
        if ran == "ok" or (ran == "stopped" and "STOPPED" in c.quals):
            want = c.quals.get("OUTPUT")
            if want:
                st = self.ed.builds.get(ctx.buf.path or ctx.buf.name)
                out = getattr(st.run_result, "output", "") if st else ""
                if want.lower() not in (out or "").lower():
                    return Result(False, f'the last run did not print "{want}" (F5 runs it)')
            return Result(True)
        if ran == "error":
            return Result(False, "the last run stopped with an error (F8 goes to the line)")
        if ran == "stopped":
            return Result(False, "the last run was stopped with Ctrl-C; run it to the end (F5)")
        return Result(False, "you have not run it since your last change (F5)")

    def _tmpdir(self) -> str:
        if self._tmp is None:
            self._tmp = tempfile.mkdtemp(prefix="lse-tutor-")
            atexit.register(shutil.rmtree, self._tmp, True)
        return self._tmp

    def private_run(self, ctx: _Context, input_text: str, seed: int | None) -> tuple[bool, str]:
        """Compile, link and run a copy of the program out of sight; (built, output)."""
        key = (ctx.state_id, input_text, seed)
        if key in self._runs:
            return self._runs[key]
        result = (False, "")
        if not ctx.errors(self) and ph.count(ctx.buf.lines) == 0:
            tc = self.ed.toolchain
            try:
                src = os.path.join(self._tmpdir(), os.path.basename(self.path))
                with open(src, "w", encoding="utf-8") as f:
                    f.write(ctx.text + "\n")
                comp = tc.compile(src)
                if comp.ok:
                    linked = tc.link([comp.obj_path], map_file=False)
                    if linked.ok:
                        run = tc.run(linked.exe_path, input_text=input_text, seed=seed,
                                     explain=False)
                        result = (True, run.output or "")
            except Exception:
                result = (False, "")
        self._runs[key] = result
        if len(self._runs) > 64:
            self._runs.pop(next(iter(self._runs)))
        return result

    def _run_check(self, c: Check, ctx: _Context) -> Result:
        want = c.args[0]
        input_text = c.quals.get("INPUT", "")
        seed = int(c.quals["SEED"]) if "SEED" in c.quals else None
        built, output = self.private_run(ctx, input_text, seed)
        if not built:
            return Result(False, "the program has to compile first (F7 shows what is wrong)")
        if want.lower() in output.lower():
            return Result(True)
        typed = _show_input(input_text)
        when = f"when the player types {typed}, " if typed else ""
        return Result(False, f'{when}the program should print "{want}"')

    # ----- evaluating the step --------------------------------------------------

    def evaluate(self, ctx: _Context | None = None) -> StepStatus:
        ctx = ctx or self._context()
        step = self.step
        if ctx is None:
            return StepStatus([False] * len(step.items), 0 if step.items else None)
        failures: list[tuple[Check, str] | None] = []
        for item in step.items:
            failures.append(self._first_failure(item.checks, ctx))
        done: list[bool] = []
        for f in failures:
            done.append(f is None and all(done))
        current = next((i for i, d in enumerate(done) if not d), None)
        step_failure = self._first_failure(step.checks, ctx)
        failing = failures[current] if current is not None else step_failure
        passed = all(done) and step_failure is None and not step.final
        return StepStatus(done, current, failing, passed)

    def _first_failure(self, checks: list[Check], ctx: _Context) -> tuple[Check, str] | None:
        for c in checks:
            r = self.check(c, ctx)
            if not r.ok:
                return c, r.why
        return None

    def _find_regression(self, ctx: _Context) -> tuple[int, Check, str] | None:
        if self.step.final or ctx.errors(self):
            return None
        for k in range(self.index):
            for c in self.lesson.steps[k].all_checks:
                if not c.durable:
                    continue
                key = (ctx.state_id, k, id(c))
                res = self._durable_cache.get(key)
                if res is None:
                    res = self.check(c, ctx)
                    if len(self._durable_cache) > 512:
                        self._durable_cache.clear()
                    self._durable_cache[key] = res
                if not res.ok:
                    return k, c, res.why
        return None

    def _needed_latches(self) -> set[str]:
        return {c.key for c in self.step.all_checks if c.latched}

    def _observe(self, ctx: _Context) -> None:
        needed = self._needed_latches()
        if not needed:
            return
        if "MADE_ERROR" in needed and ctx.errors(self):
            self.latches.add("MADE_ERROR")
        for w in self.ed.windows:
            key = f"FILE_OPENED {os.path.basename(w.buffer.path or w.buffer.name).upper()}"
            if key in needed and key not in self.latches:
                self.latches.add(key)
                self.save()

    def update(self) -> None:
        if not self.active:
            self.sync_window()
            return
        ctx = self._context()
        if ctx is None:
            self.sync_window()
            return
        self._observe(ctx)
        status = self.evaluate(ctx)
        done = sum(status.done)
        if done > self._done_count:
            self.last_progress = self.ed.clock()
            self.fails = 0
        self._done_count = done
        if status.passed:
            self._advance()
            ctx = self._context() or ctx
            self._observe(ctx)
            status = self.evaluate(ctx)
            self._done_count = sum(status.done)
        self.regression = self._find_regression(ctx)
        self.status = status
        self.sync_window()
        self.refresh_lesson()

    def _advance(self) -> None:
        old = self.index + 1
        self.index += 1
        self._enter_step()
        self.save()
        if self.step.final:
            text = (f"%LSE-S-FINISHED, step {old} done: you finished the tutorial! "
                    "Your game is in GUESS.PAS. The lesson has some challenges to try next.")
        else:
            text = (f"%LSE-S-STEPDONE, step {old} done. Now step {self.index + 1} of "
                    f"{self.total}: {self.step.title}")
        ed = self.ed
        if ed._message_this_key and ed.message is not None and not ed.message.hint \
                and ed.message.severity in "IS":
            text = ed.message.text + "\n" + text
        ed.show(text, "S")

    # ----- what the NEXT line says ------------------------------------------------

    @property
    def stuck(self) -> bool:
        if not self.active or self.step.final:
            return False
        idle = self.ed.clock() - self.last_progress >= IDLE_NUDGE_SECONDS
        return self.fails >= STUCK_FAILURES or idle

    def next_text(self, view: str = "source") -> str | None:
        """The tutorial's NEXT line for this view ("" leaves it to the general rules)."""
        if not self.active:
            return None
        if view == "source":
            text = self._next_text()
        elif view in ("readonly", "text") and self._current_check_kind() == "EDITING":
            text = self.step.items[self.status.current].next_text
        else:
            return ""
        if self.stuck and not self.regression:
            text = STUCK + text
        return text

    def _current_check_kind(self) -> str:
        st = self.status
        if st.current is None or st.failing is None:
            return ""
        return st.failing[0].kind

    def _next_text(self) -> str:
        step = self.step
        if self.regression is not None:
            k, _c, why = self.regression
            return f"Ctrl-Z undoes, F4 puts it back: part of step {k + 1} is gone ({why})"
        ed = self.ed
        buf = self.source()
        if buf is not None and ed.buffer is not buf and ed.buffer.language is not None \
                and not ed.buffer.system and not ed.buffer.read_only:
            return (f"The lesson is about {self.lesson.file}: Ctrl-O, type {self.lesson.file} "
                    "and Enter (TUTORIAL OFF stops the lesson)")
        if step.final:
            if buf is not None and buf.modified:
                return "You finished! Ctrl-S saves your game; then try a challenge or Ctrl-Q"
            return "You finished! Try a challenge from the lesson, or Ctrl-Q to quit"
        st = self.status
        if st.current is not None:
            item = step.items[st.current]
            failing = st.failing
            if failing is not None and failing[0].durable and buf is not None:
                err = self._error_away_from_cursor(buf)
                if err is not None:
                    return err
            return item.next_text
        if st.failing is not None:
            return f"Almost: {st.failing[1]}. F4 gives a hint"
        return "F2 checks your work"

    def _error_away_from_cursor(self, buf: "Buffer") -> str | None:
        ctx = _Context(buf, buf.text, buf.state_id)
        for d in ctx.errors(self, "EFW"):
            line = getattr(d, "line", None)
            if line and line != buf.row + 1:
                return f"Line {line}: {_headline(d)}. F7, then F8 jumps to it"
        return None

    def describe(self) -> str:
        if self.step.final:
            return ("You have finished the tutorial. The lesson window has some challenges; "
                    "TUTORIAL RESTART starts it again from step 1.")
        hidden = "" if self.shown else " (it is hidden: Ctrl-L shows it)"
        return (f"You are on step {self.index + 1} of {self.total} of the tutorial: "
                f"{self.step.title}. The lesson window{hidden} says what to do; F2 checks your "
                "work, F4 gives a hint, Ctrl-L hides or shows the lesson, and TUTORIAL OFF "
                "stops it.")

    def status_segment(self, ed: "Editor", win: "Window"):
        if not self.active or self.shown or win.buffer.system:
            return None
        return [(f"Lesson {self.index + 1}/{self.total}: Ctrl-L", "pipeline_current")]

    # ----- the LESSON window --------------------------------------------------------

    def sync_window(self) -> None:
        ed = self.ed
        lb = self.lesson_buffer
        win = self.lesson_window()
        if self.window is not None and (self.window not in ed.windows or self.window.buffer is not lb):
            if self.window in ed.windows:
                self._plain(self.window, keep_height=True)
            self.window = None
        if not (self.active and self.visible):
            if win is not None:
                if len(ed.windows) > 1:
                    ed.close_window(win)
                else:
                    ed.show_buffer(self.source() or ed.buffer, win)
                    self._plain(win)
            self.window = None
            return
        if win is None and len(ed.windows) == 1:
            win = ed.split(lb, fixed_height=self._height())
        if win is not None:
            self.window = win
            win.border = True
            win.show_status = False
            win.tags.add("lesson")
            win.title = f"Lesson {self.index + 1} of {self.total}: {self.step.title}"
            win.fixed_height = self._height()

    @staticmethod
    def _plain(win: "Window", keep_height: bool = False) -> None:
        """Turn a window that showed the lesson back into an ordinary one."""
        win.border = False
        win.title = None
        win.show_status = True
        win.tags.discard("lesson")
        if not keep_height:
            win.fixed_height = None

    def toggle(self) -> None:
        """Ctrl-L: hide or show the lesson window."""
        ed = self.ed
        if not self.active:
            ed.info("TUTORIAL", "there is no lesson to show; TUTORIAL starts the tutorial")
            return
        if self.shown:
            self.visible = False
            self.sync_window()
            ed.info("LESSON", f"lesson hidden (step {self.index + 1} of {self.total}); "
                    "Ctrl-L shows it again")
            return
        self.visible = True
        if len(ed.windows) > 1:
            other = ed.other_window()
            keep = ed.window
            if other is not None:
                if keep.buffer.system and other.buffer is not keep.buffer:
                    keep, other = other, keep
                ed.select_window(keep)
                ed.show_buffer(self.lesson_buffer, other)
        self.sync_window()
        self.refresh_lesson()
        ed.info("LESSON", "lesson shown (Ctrl-L hides it)")

    def _height(self) -> int:
        lines = len(self.lesson_buffer.lines)
        room = max(5, (self.ed.height - 3) // 2 + 1)
        return max(5, min(lines + 2, room))

    def lesson_lines(self) -> tuple[list[str], int | None]:
        """The lesson window text, and the row of the current DO item."""
        step = self.step
        width = max(20, self.ed.width - 4)
        out: list[str] = []
        for para in step.text:
            out += textwrap.wrap(para, width) or [""]
        current_row = None
        st = self.status
        label = "TRY THIS: " if step.final else "DO THIS:  "
        pad = " " * len(label)
        for i, item in enumerate(step.items):
            if step.final:
                mark = " * "
            elif i < len(st.done) and st.done[i]:
                mark = "[x]"
            elif i == st.current:
                mark = "==>"
            else:
                mark = "[ ]"
            body = textwrap.wrap(f"{i + 1}. {item.text}", width - len(pad) - 4) or [""]
            if i == st.current and not step.final:
                current_row = len(out)
            out.append(f"{label if i == 0 else pad}{mark} {body[0]}")
            out += [f"{pad}       {b}" for b in body[1:]]
            if i == st.current and self.hint_level and not step.final:
                out += self._hint_lines(width, len(pad) + 4)
        if not step.items and self.hint_level and not step.final:
            out += self._hint_lines(width, 4)
        if step.see:
            see = ("YOU WILL SEE: " if not step.final else "") + step.see
            out += textwrap.wrap(see, width, subsequent_indent=" " * 14) or [""]
        return out, current_row

    def _hint_lines(self, width: int, indent: int) -> list[str]:
        hints = self.step.hints
        n = len(hints) + 1
        level = min(self.hint_level, len(hints))
        if level <= 0:
            return []
        more = "  (F4 again: show me)" if level == len(hints) else "  (F4: more help)"
        return textwrap.wrap(f"Hint {level} of {n}: {hints[level - 1]}{more}", width,
                             initial_indent=" " * indent, subsequent_indent=" " * (indent + 3))

    def refresh_lesson(self) -> None:
        if not self.active:
            return
        lb = self.lesson_buffer
        lines, current = self.lesson_lines()
        if lb.lines != lines:
            row = lb.row
            lb.load_text(lines)
            lb.set_cursor(min(row, len(lines) - 1), 0)
        lb.highlight_row = current
        win = self.window
        if win is not None and win.buffer is lb:
            win.fixed_height = self._height()
            h = max(1, win.fixed_height - 2)
            if current is not None:
                if current < win.top:
                    win.top = current
                elif current >= win.top + h - 1:
                    win.top = max(0, current - h + 2)
            win.top = max(0, min(win.top, max(0, len(lines) - h)))
            if self.ed.window is not win:
                lb.set_cursor(win.top, 0)

    # ----- hints, show me, checking -------------------------------------------------

    def hint(self) -> None:
        """F4: the next level of help for this step."""
        ed = self.ed
        if not self.active:
            ed.info("NOTUTORIAL", "hints come with the tutorial; Ctrl-P and TUTORIAL starts it")
            return
        if self.regression is not None:
            self.show_me(restore=True)
            return
        step = self.step
        if step.final:
            ed.info("HINT", "you have finished! The challenges are up to you; HELP PASCAL "
                    "explains REPEAT, IF and PROCEDURE")
            return
        self.fails = 0
        self.last_progress = ed.clock()
        if self.hint_level < len(step.hints):
            self.hint_level += 1
            self.save()
            self.refresh_lesson()
            more = "F4 again for more help" if self.hint_level < len(step.hints) else \
                "F4 again shows you the answer"
            ed.show(f"Hint {self.hint_level} of {len(step.hints) + 1}: "
                    f"{step.hints[self.hint_level - 1]}\n({more})", "I")
            return
        self.hint_level = len(step.hints) + 1
        self.show_me()

    def show_me(self, *, restore: bool = False) -> None:
        ed = self.ed
        buf = self.source()
        if not self.active or buf is None:
            ed.info("NOTUTORIAL", "show me works inside the tutorial (TUTORIAL starts it)")
            return
        if restore and self.regression is not None:
            k = self.regression[0]
            target = self.lesson.steps[self.index - 1].solution if self.index > 0 else None
            title = f"Put back what step {k + 1} made"
        else:
            target = self.step.solution
            title = f"Show me: step {self.index + 1}, {self.step.title}"
        if target is None:
            ed.info("SHOWME", "this step has no ready-made answer; follow DO THIS in the lesson")
            return
        current = [l.rstrip() for l in buf.lines]
        while current and not current[-1]:
            current.pop()
        if current == target:
            nxt = self._next_text()
            ed.info("SHOWME", f"your program already has everything this step needs. Next: {nxt}")
            return
        diff = [l for l in difflib.ndiff(current, target) if not l.startswith("?")]
        lines = ["This is the program as it should be at the end of this step.",
                 "Lines with + are new, lines with - go away.", ""]
        lines += [f"  {l[0]} {l[2:]}" if l[0] in "+-" else f"    {l[2:]}" for l in diff]

        def accept() -> None:
            first = next((i for i, (a, b) in enumerate(zip(current + [None] * len(target), target))
                          if a != b), 0)
            with buf.change():
                buf.set_lines(list(target))
            win = ed.window_showing(buf)
            if win is not None:
                ed.select_window(win)
            buf.set_cursor(min(first, len(buf.lines) - 1), 0)
            self.update()
            ed.info("SHOWME", "done: the step's program is in your file (Ctrl-Z takes it back "
                    "out). Read it, then follow NEXT")

        ed.push_overlay(PreviewOverlay(title, lines, accept,
                                       lambda: ed.info("SHOWME", "kept your program as it is")))

    def check_now(self) -> None:
        """F2: check the step now and say what is missing."""
        ed = self.ed
        if not self.active:
            ed.info("NOTUTORIAL", "F2 checks tutorial steps; Ctrl-P and TUTORIAL starts it")
            return
        before = self.index
        self.update()
        if self.index != before:
            return
        step = self.step
        if step.final:
            ed.success("CHECKED", "you have finished the tutorial; the challenges are optional")
            return
        st = self.status
        n = sum(st.done)
        if self.regression is not None:
            k, _c, why = self.regression
            ed.show(f"%LSE-W-UNDONE, something from step {k + 1} is gone: {why}.\n"
                    "Ctrl-Z undoes your last changes; F4 shows how to put it back.", "W")
        elif st.failing is not None:
            ed.show(f"%LSE-W-NOTYET, {n} of {len(step.items)} done. Not yet: {st.failing[1]}.\n"
                    f"NEXT: {self._next_text()}", "W")
        else:
            ed.info("CHECKED", "everything checks out")
        self.fails += 1

    # ----- events from commands -------------------------------------------------------

    def on_command(self, ed: "Editor", cmd: Command, args: Args) -> None:
        if not self.active:
            return
        name = cmd.name
        buf = self.source()
        st = ed.builds.get(buf.path) if buf is not None and buf.path else None
        if name in ("COMPILE", "BUILD") and st is not None and buf is not None:
            if st.compile_ok is False and st.compiled_state == buf.state_id:
                self.latches.update({"COMPILE_FAILED", "MADE_ERROR"})
                for d in st.diagnostics or []:
                    self.latches.add(f"COMPILE_FAILED {getattr(d, 'ident', '')}".upper())
                self.fails += 1
            elif st.link_ok is False and st.linked_state == buf.state_id:
                self.fails += 1
        if name in ("RUN", "BUILD") and st is not None and st.run_result is not None:
            err = getattr(st.run_result, "error", None)
            if err is not None and getattr(err, "ident", "") != "CONTROLC" and \
                    st.ran_state == (buf.state_id if buf else None):
                self.fails += 1
        if name in ("NEXT ERROR", "PREVIOUS ERROR", "GOTO SOURCE", "REVIEW") \
                and ed.review is not None and ed.review.diagnostics:
            self.latches.add("REVIEWED")
        if name == "ONE WINDOW":
            self.visible = False
        self.update()


def pattern_summary(pattern: str) -> str:
    """A statement pattern as people read it: placeholders become '...'."""
    text = ph.PLACEHOLDER_RE.sub("...", pattern)
    text = re.sub(r"\.\.\.(;\s*\.\.\.)+", "...", text)
    return re.sub(r"\s+", " ", text).strip()


def _headline(d: Any) -> str:
    head = getattr(d, "headline", None)
    if callable(head):
        try:
            text = head()
        except Exception:
            text = ""
    else:
        text = ""
    text = text or getattr(d, "text", "") or str(d)
    text = re.sub(r"^%\w+-\w-\w+,\s*", "", text)
    return re.sub(r"\s+at line \d+(, column \d+)?$", "", text)


# ============================================================================
# Commands and installation
# ============================================================================


def _tutor(ed: "Editor") -> Tutor | None:
    t = getattr(ed, "tutor", None)
    if t is None:
        problem = getattr(ed, "tutor_problem", "") or "it is not installed"
        ed.error("NOTUTOR", f"the tutorial is not available: {problem}")
    return t


def _cmd_tutorial(ed: "Editor", args: Args) -> None:
    t = _tutor(ed)
    if t is not None:
        t.start(resume=True)


def _cmd_tutorial_off(ed: "Editor", args: Args) -> None:
    t = _tutor(ed)
    if t is not None:
        t.stop()


def _cmd_tutorial_restart(ed: "Editor", args: Args) -> None:
    t = _tutor(ed)
    if t is not None:
        t.restart()


def _cmd_tutorial_step(ed: "Editor", args: Args) -> None:
    t = _tutor(ed)
    if t is None:
        return
    n = args.get("number")
    if n is not None:
        _jump(t, n - 1)
        return
    items = []
    for i, st in enumerate(t.lesson.steps):
        mark = "now" if i == t.index and t.active else ("done" if i < t.index else "")
        items.append(MenuItem(f"{i + 1:>2}. {st.title}", mark, i))
    ed.menu("Tutorial steps", items, lambda item: _jump(t, item.value), selected=t.index)


def _jump(t: Tutor, index: int) -> None:
    ed = t.ed
    index = max(0, min(index, t.total - 1))
    if not t.active:
        t.start(resume=True)
    if index <= t.index or index == 0:
        t.goto(index)
        ed.info("TUTORIAL", f"step {index + 1} of {t.total}: {t.step.title}")
        return

    def load() -> None:
        t.goto(index, load_solution=True)
        ed.info("TUTORIAL", f"step {index + 1}: your program now has everything from the "
                "steps before it (the old one is kept as a version)")

    def keep() -> None:
        t.goto(index)
        ed.info("TUTORIAL", f"step {index + 1} of {t.total}: {t.step.title}")

    ed.ask(f"Jump to step {index + 1}. Put the program from the steps before it into "
           f"{t.lesson.file}? Y = yes, N = keep mine", {"y": load, "n": keep},
           on_cancel=lambda: ed.info("CANCELLED", "staying on this step"))


def _cmd_check(ed: "Editor", args: Args) -> None:
    t = _tutor(ed)
    if t is not None:
        t.check_now()


def _cmd_hint(ed: "Editor", args: Args) -> None:
    t = _tutor(ed)
    if t is not None:
        t.hint()


def _cmd_show_me(ed: "Editor", args: Args) -> None:
    t = _tutor(ed)
    if t is not None:
        t.show_me(restore=t.regression is not None)


def _cmd_lesson(ed: "Editor", args: Args) -> None:
    t = _tutor(ed)
    if t is not None:
        t.toggle()


COMMANDS = [
    Command("TUTORIAL", _cmd_tutorial, "Start the Guess My Number tutorial, or carry on where "
            "you left off.", group="Tutorial"),
    Command("TUTORIAL OFF", _cmd_tutorial_off, "Stop the tutorial and just edit (TUTORIAL "
            "picks it up again).", group="Tutorial"),
    Command("TUTORIAL RESTART", _cmd_tutorial_restart, "Start the tutorial again from step 1.",
            group="Tutorial"),
    Command("TUTORIAL STEP", _cmd_tutorial_step, "Jump to a tutorial step (no number: pick "
            "from a list).", [Param("number", "int")], group="Tutorial"),
    Command("CHECK", _cmd_check, "Check the tutorial step now and say what is missing (F2).",
            group="Tutorial"),
    Command("HINT", _cmd_hint, "A hint for the tutorial step; press again for more, then "
            "'show me' (F4).", group="Tutorial"),
    Command("SHOW ME", _cmd_show_me, "Show the tutorial step's answer and offer to put it in.",
            group="Tutorial"),
    Command("LESSON", _cmd_lesson, "Hide or show the lesson window (Ctrl-L).",
            group="Tutorial"),
]


def install(ed: "Editor", lesson_name: str = "guess", *,
            user_state: UserState | None = None) -> Tutor | None:
    for cmd in COMMANDS:
        ed.commands.register(Command(cmd.name, cmd.handler, cmd.help, list(cmd.params),
                                     list(cmd.qualifiers), list(cmd.aliases), cmd.group))
    ed.keymap.bind("F2", "CHECK")
    ed.keymap.bind("F4", "HINT")
    ed.keymap.bind("C-l", "LESSON")
    try:
        lesson = lessonfile.load(lesson_name)
    except (OSError, lessonfile.LessonError) as e:
        ed.tutor = None
        ed.tutor_problem = str(e)
        return None
    tutor = Tutor(ed, lesson, user_state=user_state)
    ed.tutor = tutor
    ed.after_key_hooks.append(lambda e, key: tutor.update())
    ed.idle_hooks.append(lambda e: tutor.update())
    ed.command_hooks.append(tutor.on_command)
    ed.status_providers.append(tutor.status_segment)
    ed.on_quit.append(lambda e: tutor.save() if tutor.active else None)
    return tutor

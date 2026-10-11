"""Guidance: the screen always says what to do next.

* ``next_action(state)`` gives one actionable sentence for the NEXT line.
  It is a pure function of a ``State`` snapshot, so a test can try every
  combination and check that it is never empty.
* ``state_of(editor)`` takes that snapshot from a live editor.
* ``pipeline_of(state)``: EDIT > COMPILE > LINK > RUN for the status line,
  each stage done, current, pending, stale (the source changed since,
  shown with ``*``) or failed (shown with ``!``).
* ``key_bar(editor)``: the VT220-style function-key strip. Its labels
  follow the context, and Quit (or the way out of a popup) is always there.
* ``WHAT NOW`` (and F1 when the cursor is on nothing in particular)
  explains the state in a few plain sentences.

``install(editor)`` adds all of this to an editor; ``lse`` does that at
start-up, the bare editor core (and its tests) runs without it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from . import placeholders as ph
from .commands import Args, Command

if TYPE_CHECKING:
    from .buffer import Buffer
    from .editor import Editor
    from .windows import Window

#: what counts as "actionable": every NEXT text names a key or a thing to type
ACTION_WORDS = re.compile(
    r"\b(Tab|Shift-Tab|Enter|RETURN|Esc|Backspace|Home|End|Up|Down|Ctrl-[A-Z]|F\d{1,2}|"
    r"Y|N|[Tt]ype|[Pp]ress|TUTORIAL)\b")


@dataclass(frozen=True)
class State:
    """Everything ``next_action`` looks at.

    ``view`` is what the current window shows: ``source`` (a Pascal file),
    ``text`` (another file), ``none`` (the empty MAIN buffer), ``readonly``
    (a file the toolchain wrote, such as GUESS.MAP), ``review``,
    ``output``, ``lesson`` or ``system`` (another $ buffer).
    ``overlay`` is the popup on top, if any: ``menu``, ``prompt``,
    ``question``, ``text``, ``keytest``, ``welcome``, ``preview`` or ``help``.
    """

    view: str = "source"
    overlay: str = ""
    overlay_info: str = ""
    file: str = "GUESS.PAS"
    back: str = ""
    placeholders: int = 0
    at_placeholder: str = ""
    at_placeholder_kind: str = ""
    modified: bool = False
    compiled: str = "none"      # none | ok | warnings | failed | stale
    errors: int = 0
    error_index: int = -1
    linked: str = "none"        # none | ok | failed | stale
    ran: str = "none"           # none | ok | error | stopped | stale
    run_error_line: int = 0
    tutor: str = ""             # the tutorial's own next step, when it is running
    tutor_stuck: bool = False
    suggest_tutorial: bool = False

    @property
    def exe(self) -> str:
        base = self.file.rsplit(";", 1)[0]
        return (base.rsplit(".", 1)[0] if "." in base else base) + ".EXE"


VIEWS = ("source", "text", "none", "readonly", "review", "output", "lesson", "system")
OVERLAYS = ("", "menu", "prompt", "question", "text", "keytest", "welcome", "preview", "help")


# ============================================================================
# next_action: one sentence for the NEXT line
# ============================================================================


def next_action(s: State) -> str:
    """What to do next, as one short sentence that names the key to press."""
    return _overlay_action(s) or s.tutor or _view_action(s) or _source_action(s)


def _overlay_action(s: State) -> str:
    o = s.overlay
    if not o:
        return ""
    if o == "menu":
        return "Up/Down to choose, Enter to pick it, Esc closes the menu (F1 explains)"
    if o == "prompt":
        label = s.overlay_info.strip().rstrip(":").strip()
        if label.startswith("LSE>") or not label:
            return "Type a command and press Enter (Tab completes it, Esc cancels)"
        m = re.match(r"(.*?)\s*\[(.*)\]$", label)
        if m:
            return f"{m.group(1)}: type it and press Enter, or just Enter for {m.group(2)}"
        return f"{label}: type it and press Enter (Tab completes, Esc cancels)"
    if o == "question":
        keys = s.overlay_info or "Y or N"
        return f"Press {keys} to answer, or Esc to cancel"
    if o == "keytest":
        return "Press keys to see if they reach LSE; Esc twice leaves the key test"
    if o == "welcome":
        return "Up/Down to choose, Enter to start it (Ctrl-Q quits)"
    if o == "preview":
        return "Enter puts this into your program; Esc keeps yours as it is"
    if o == "help":
        return "Up/Down picks a topic, Enter opens it, Backspace goes back, Esc leaves"
    return "Read it, then press Esc to go back (Up/Down scroll)"


def _back(s: State) -> str:
    return s.back or "Ctrl-O opens a file"


def _view_action(s: State) -> str:
    v = s.view
    if v == "source":
        return ""
    if v == "none":
        return "Ctrl-O opens a file, or Ctrl-P and type TUTORIAL to learn Pascal"
    if v == "text":
        if s.modified:
            return "Ctrl-S saves your changes (Ctrl-Q quits)"
        return "Type to edit it; Ctrl-O opens another file, Ctrl-Q quits"
    if v == "readonly":
        return f"This file is read-only. {_back(s)}"
    if v == "review":
        return "Enter goes to the message under the cursor, F8 to the next; Esc goes back"
    if v == "output":
        return f"Your program's output. {_back(s)}"
    if v == "lesson":
        return f"The lesson; Up/Down scroll it. {_back(s)}"
    return f"Read-only buffer. {_back(s)}"


def _source_action(s: State) -> str:
    if s.placeholders:
        left = f"{s.placeholders} left"
        here = s.at_placeholder
        if here:
            if s.at_placeholder_kind == "MENU":
                return f"Tab shows the choices for {here}, or type over it ({left})"
            if s.at_placeholder_kind == "NONTERMINAL":
                return f"Tab expands {here}, or Ctrl-K erases it if not needed ({left})"
            return f"Type over {here}, then Tab to go on ({left}; Ctrl-K erases one)"
        return f"Tab to the next placeholder ({left})"
    if s.modified:
        return "Ctrl-S saves your changes (F7 saves and compiles)"
    if s.compiled in ("none", "stale"):
        return f"F7 compiles {s.file} (F5 also links and runs it)"
    if s.compiled == "failed":
        n = max(1, s.errors)
        k = min(n, s.error_index + 2) if s.error_index + 1 < n else n
        what = "the error" if n == 1 else f"error {k} of {n}"
        return f"F8 goes to {what}; fix it, then F7 compiles again"
    if s.linked in ("none", "stale"):
        extra = " (F8 shows the warnings)" if s.compiled == "warnings" else ""
        return f"F5 links and runs it{extra}; Ctrl-P LINK links only"
    if s.linked == "failed":
        return "F8 goes to where the missing name is used; fix it, then F5"
    if s.ran in ("none", "stale"):
        return f"F5 runs {s.exe}"
    if s.ran == "error":
        where = f"line {s.run_error_line}" if s.run_error_line else "the line"
        return f"F8 goes to {where} where the program stopped; fix it, then F5"
    if s.ran == "stopped":
        return "F5 runs it again (Ctrl-C stopped it last time)"
    return "Edit and try again (F5 runs it again), or F1 for ideas"


TUTORIAL_TIP = "New? Ctrl-P TUTORIAL"
TUTORIAL_OFFER = "New to Pascal? Press Ctrl-P and type TUTORIAL to learn it step by step."


# ============================================================================
# The snapshot of a live editor
# ============================================================================


def _overlay_kind(ov: Any) -> tuple[str, str]:
    from .overlays import KeyTestOverlay, MenuOverlay, PromptOverlay, QuestionOverlay
    if ov is None:
        return "", ""
    kind = getattr(ov, "guidance_kind", None)
    if kind:
        return kind, ""
    if isinstance(ov, MenuOverlay):
        return "menu", ov.title
    if isinstance(ov, PromptOverlay):
        return "prompt", ov.label
    if isinstance(ov, QuestionOverlay):
        keys = [k.upper() for k in ov.answers if len(k) == 1]
        return "question", " or ".join(keys)
    if isinstance(ov, KeyTestOverlay):
        return "keytest", ""
    return "text", ""


def _is_source(buf: "Buffer | None") -> bool:
    return buf is not None and not buf.system and buf.language is not None and not buf.read_only


def source_of(ed: "Editor") -> "Buffer | None":
    """The Pascal program the user is working on (to go back to, or to build)."""
    tutor = getattr(ed, "tutor", None)
    if tutor is not None and tutor.active and tutor.source() is not None:
        return tutor.source()
    if _is_source(ed.buffer):
        return ed.buffer
    if ed.review is not None and _is_source(ed.review.source):
        return ed.review.source
    for w in ed.windows:
        if _is_source(w.buffer):
            return w.buffer
    if _is_source(ed.previous_file) and ed.buffers.get(ed.previous_file.name) is ed.previous_file:
        return ed.previous_file
    return next((b for b in ed.file_buffers() if _is_source(b)), None)


def _back_phrase(ed: "Editor", win: "Window", target: "Buffer | None") -> str:
    if target is None or target is win.buffer:
        return ""
    if any(w.buffer is target for w in ed.windows if w is not win):
        return f"Ctrl-W goes back to {target.name}"
    prev = ed.previous_file
    if prev is target and ed.previous_file_name():
        return f"Ctrl-O then Enter goes back to {target.name}"
    return f"Ctrl-B, then pick {target.name}, goes back to it"


def view_of(ed: "Editor", win: "Window") -> str:
    buf = win.buffer
    if buf.system:
        if buf.name == "$REVIEW":
            return "review"
        if buf.name == "$OUTPUT":
            return "output"
        if buf.name == "$LESSON" or "lesson" in win.tags:
            return "lesson"
        return "system"
    if buf.read_only:
        return "readonly"
    if buf.language is None:
        if not buf.path and not buf.modified and buf.lines == [""]:
            return "none"
        return "text"
    return "source"


def build_states(ed: "Editor", buf: "Buffer") -> dict[str, Any]:
    """compiled / linked / ran (and error counts) for one source buffer."""
    st = ed.builds.get(buf.path or buf.name)
    sid = buf.state_id
    out: dict[str, Any] = dict(compiled="none", errors=0, error_index=-1, linked="none",
                               ran="none", run_error_line=0)
    if st is None or st.compile_ok is None:
        return out
    diags = st.diagnostics or []
    errors = [d for d in diags if str(getattr(d, "severity", "E")) in "EF"]
    if st.compiled_state != sid:
        out["compiled"] = "stale"
    elif not st.compile_ok:
        out["compiled"] = "failed"
        out["errors"] = len(errors) or len(diags)
    else:
        out["compiled"] = "warnings" if diags else "ok"
    r = ed.review
    if r is not None and r.source is buf:
        out["error_index"] = r.index
    if st.link_ok is not None:
        if st.linked_state != sid:
            out["linked"] = "stale"
        elif not st.link_ok:
            out["linked"] = "failed"
        else:
            out["linked"] = "ok"
    if st.run_result is not None:
        err = getattr(st.run_result, "error", None)
        if st.ran_state != sid:
            out["ran"] = "stale"
        elif err is None:
            out["ran"] = "ok"
        elif getattr(err, "ident", "") == "CONTROLC":
            out["ran"] = "stopped"
        else:
            out["ran"] = "error"
            out["run_error_line"] = getattr(err, "line", 0) or 0
    return out


def state_of(ed: "Editor") -> State:
    ov = ed.overlays[-1] if ed.overlays else None
    overlay, info = _overlay_kind(ov)
    win = ed.window
    buf = win.buffer
    view = view_of(ed, win)
    tutor = getattr(ed, "tutor", None)
    src = buf if view == "source" else source_of(ed)
    kw: dict[str, Any] = dict(view=view, overlay=overlay, overlay_info=info)
    if src is not None:
        kw["file"] = src.name
    kw["back"] = _back_phrase(ed, win, src) if view != "source" else ""
    if view == "source":
        found = ph.placeholder_at(buf.lines, buf.row, buf.col)
        kw["placeholders"] = ph.count(buf.lines)
        if found is not None:
            defn = buf.language.placeholder(found.name) if buf.language else None
            kw["at_placeholder"] = found.text
            kw["at_placeholder_kind"] = defn.type if defn else "TERMINAL"
        kw["modified"] = buf.modified
        kw.update(build_states(ed, buf))
    elif view == "text":
        kw["modified"] = buf.modified
    if tutor is not None and tutor.active:
        kw["tutor"] = tutor.next_text(view) or ""
        kw["tutor_stuck"] = tutor.stuck
    elif tutor is not None and not tutor.ever_finished and not ed.builds:
        kw["suggest_tutorial"] = True
    return State(**kw)


# ============================================================================
# EDIT > COMPILE > LINK > RUN
# ============================================================================


@dataclass(frozen=True)
class Stage:
    name: str
    status: str          # done | current | pending | stale | failed
    stale: bool = False

    @property
    def label(self) -> str:
        return self.name + ("*" if self.stale else "") + ("!" if self.status == "failed" else "")


def pipeline_of(s: State) -> list[Stage]:
    edit_now = bool(s.placeholders) or s.compiled == "failed" or s.linked == "failed" \
        or s.ran == "error"
    stages = [Stage("EDIT", "current" if edit_now else "done")]
    for name, value in (("COMPILE", s.compiled), ("LINK", s.linked), ("RUN", s.ran)):
        if value in ("ok", "warnings", "stopped"):
            stages.append(Stage(name, "done"))
        elif value in ("failed", "error"):
            stages.append(Stage(name, "failed"))
        elif value == "stale":
            stages.append(Stage(name, "stale", stale=True))
        else:
            stages.append(Stage(name, "pending"))
    if not edit_now:
        for i, st in enumerate(stages[1:], 1):
            if st.status in ("pending", "stale"):
                stages[i] = replace(st, status="current")
                break
    return stages


def pipeline_segment(ed: "Editor", win: "Window"):
    if view_of(ed, win) != "source" or not win.buffer.path:
        return None
    buf = win.buffer
    s = State(placeholders=ph.count(buf.lines), **build_states(ed, buf))
    out: list[tuple[str, str]] = []
    for i, st in enumerate(pipeline_of(s)):
        if i:
            out.append((" > ", "status"))
        out.append((st.label, f"pipeline_{st.status}"))
    return out


# ============================================================================
# The key bar
# ============================================================================


def key_items(ed: "Editor") -> list[tuple[str, str]]:
    """(key, label) pairs for the key bar, most important first; the last is the way out."""
    s_overlay, _ = _overlay_kind(ed.overlays[-1] if ed.overlays else None)
    if s_overlay == "menu":
        return [("Up/Down", "Choose"), ("Enter", "Pick"), ("Tab", "Skip"), ("F1", "Explain"),
                ("Esc", "Cancel")]
    if s_overlay == "prompt":
        return [("Enter", "Do it"), ("Tab", "Complete"), ("Up", "History"), ("Esc", "Cancel")]
    if s_overlay == "question":
        ov = ed.overlays[-1]
        names = {"y": "Yes", "n": "No"}
        items = [(k.upper(), names.get(k, k.upper())) for k in ov.answers if len(k) == 1]
        return items + [("Esc", "Cancel")]
    if s_overlay == "keytest":
        return [("Esc Esc", "Leave the key test")]
    if s_overlay == "welcome":
        return [("Up/Down", "Choose"), ("Enter", "Start"), ("^Q", "Quit")]
    if s_overlay == "preview":
        return [("Enter", "Use it"), ("Up/Down", "Scroll"), ("Esc", "Keep mine")]
    if s_overlay == "help":
        return [("Up/Down", "Topic"), ("Enter", "Open"), ("Backspace", "Back"), ("Esc", "Leave")]
    if s_overlay:
        return [("Up/Down", "Scroll"), ("Esc", "Back")]
    view = view_of(ed, ed.window)
    tutor = getattr(ed, "tutor", None)
    tutoring = tutor is not None and tutor.active
    if view == "review":
        return [("Enter", "Go to it"), ("F8", "Next error"), ("S-F8", "Previous"),
                ("Esc", "Back to code"), ("^Q", "Quit")]
    if view in ("output", "lesson", "system", "readonly"):
        win = ed.window
        src = source_of(ed)
        back = _back_phrase(ed, win, src)
        key = "^W" if back.startswith("Ctrl-W") else ("^O Enter" if back.startswith("Ctrl-O")
                                                     else "^B")
        items = [(key, "Back to code"), ("Up/Down", "Scroll")]
        if view == "lesson":
            items.append(("^L", "Hide lesson"))
        if tutoring:
            items += [("F2", "Check"), ("F4", "Hint")]
        return items + [("F1", "Help"), ("^Q", "Quit")]
    if tutoring:
        return [("F1", "Help"), ("F2", "Check"), ("F4", "Hint"), ("F5", "Run"), ("F7", "Compile"),
                ("F8", "Errors"), ("^L", "Lesson"), ("F10", "Cmd"), ("^Q", "Quit")]
    return [("F1", "Help"), ("^S", "Save"), ("^O", "Open"), ("F5", "Run"), ("F7", "Compile"),
            ("F8", "Errors"), ("F10", "Cmd"), ("^Q", "Quit")]


def _prompting(ed: "Editor") -> bool:
    from .overlays import PromptOverlay, QuestionOverlay
    return bool(ed.overlays) and isinstance(ed.overlays[-1], (PromptOverlay, QuestionOverlay))


def command_row(ed: "Editor", width: int) -> list:
    """The LSE> row, only while a prompt or question is open (it takes the key bar's place)."""
    from .render import command_panel
    return command_panel(ed, width) if _prompting(ed) else []


def key_bar(ed: "Editor", width: int) -> list:
    if _prompting(ed):
        return []
    items = key_items(ed)
    last = items[-1]
    body = items[:-1]

    def build(chosen: list[tuple[str, str]]) -> list[tuple[str, str]]:
        segs: list[tuple[str, str]] = []
        for key, label in chosen:
            segs += [(key, "keybar_key"), (f" {label}  ", "keybar")]
        return segs

    while True:
        segs = build(body + [last])
        if sum(len(t) for t, _ in segs) <= width + 2 or not body:
            break
        body = body[:-1]
    if segs:
        segs[-1] = (segs[-1][0].rstrip(), segs[-1][1])
    return [[("", "keybar")] + segs]


def next_panel(ed: "Editor", width: int) -> list:
    s = state_of(ed)
    text = next_action(s)
    label = "NEXT: "
    room = width - len(label)
    if s.suggest_tutorial and len(text) + len(TUTORIAL_TIP) + 5 <= room:
        text = f"{text}  |  {TUTORIAL_TIP}"
    if len(text) > room:
        text = text[: max(0, room - 3)] + "..."
    role = "next_stuck" if s.tutor_stuck and s.tutor and text.startswith("Stuck") else "next"
    return [[(label, "next_label"), (text, role)]]


# ============================================================================
# WHAT NOW
# ============================================================================


def describe(ed: "Editor") -> list[str]:
    """A few plain sentences about where the user is (WHAT NOW)."""
    s = state_of(ed)
    out: list[str] = []
    buf = ed.buffer
    v = s.view
    if v == "none":
        out.append("No file is open yet.")
    elif v == "text":
        out.append(f"You are editing {buf.name}, which is not a Pascal program.")
    elif v == "readonly":
        out.append(f"You are looking at {buf.name}, a file the toolchain wrote. "
                   "It is read-only; change the .PAS file instead.")
    elif v == "review":
        out.append("You are in the REVIEW window: the compiler's messages about your program.")
    elif v == "output":
        out.append("You are looking at $OUTPUT: what your program printed the last time it ran.")
    elif v == "lesson":
        out.append("You are in the lesson window, which explains the current tutorial step.")
    elif v == "system":
        out.append(f"You are looking at {buf.name}, a buffer LSE keeps for you.")
    if v == "source":
        out.append(f"You are editing {s.file}.")
        if s.placeholders:
            n = s.placeholders
            out.append(f"It still has {n} placeholder{'s' if n != 1 else ''} (the %{{...}}% "
                       "and %[...]% words) to fill in, expand or erase.")
        if s.modified:
            out.append("It has changes that are not saved yet.")
        if s.compiled == "none":
            out.append("It has not been compiled yet. COMPILE checks it and turns it into an "
                       "object file (.OBJ).")
        elif s.compiled == "stale":
            out.append("You changed it after the last compile, so it needs compiling again.")
        elif s.compiled == "failed":
            out.append(f"The last compile found {s.errors} error{'s' if s.errors != 1 else ''}; "
                       "F8 takes you to each one.")
        elif s.linked in ("none", "stale"):
            out.append("It compiled, but it hasn't been linked since your last change. LINK "
                       "joins it with the run-time library into an .EXE you can run.")
        elif s.linked == "failed":
            out.append("It compiled, but LINK could not find a name it uses.")
        elif s.ran in ("none", "stale"):
            out.append(f"It is compiled and linked into {s.exe}, ready to run.")
        elif s.ran == "ok":
            out.append("You ran it and it finished normally. Its output is in buffer $OUTPUT.")
        elif s.ran == "stopped":
            out.append("You ran it and stopped it with Ctrl-C.")
        else:
            where = f" on line {s.run_error_line}" if s.run_error_line else ""
            out.append(f"You ran it and it stopped with an error{where}.")
    tutor = getattr(ed, "tutor", None)
    if tutor is not None and tutor.active:
        out.append(tutor.describe())
    elif tutor is not None and not tutor.ever_finished:
        out.append("New to Pascal? The TUTORIAL command teaches it step by step, by writing a "
                   "small game.")
    return out


def what_now_lines(ed: "Editor") -> list[str]:
    from .helpscreen import keypad_lines
    lines = [" ".join(describe(ed)), "", "What to do next:", "    " + next_action(state_of(ed)),
             ""]
    lines += ["The LSE keypad (HELP KEYPAD shows it alone, HELP KEYS lists every key):", ""]
    lines += keypad_lines(ed)
    lines += ["", "More help: HELP PASCAL explains the Pascal language, HELP COMMANDS lists the "
              "LSE> commands, and F1 on a placeholder explains it."]
    return lines


def what_now(ed: "Editor", args: Args) -> None:
    ed.view_text("What now?", what_now_lines(ed), wrap=True)


# ============================================================================
# Installing it
# ============================================================================


def install(ed: "Editor") -> None:
    names = [n for n, _ in ed.bottom_panels]
    if "next" not in names:
        at = names.index("message") if "message" in names else 0
        ed.bottom_panels.insert(at, ("next", next_panel))
    ed.bottom_panels = [(n, command_row if n == "command" else fn) for n, fn in ed.bottom_panels]
    if "keybar" not in names:
        ed.bottom_panels.append(("keybar", key_bar))
    ed.status_providers.append(pipeline_segment)
    ed.commands.register(Command(
        "WHAT NOW", what_now,
        "Explain where you are and what to do next (also F1 when the cursor is on nothing).",
        group="Help"))

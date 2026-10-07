"""Built-in commands: everything a key or an ``LSE>`` command can do."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, Callable

from . import files
from . import placeholders as ph
from .buffer import Buffer
from .commands import Args, Command, Param, Qualifier, complete_files
from .editor import Review
from .keys import describe_key
from .langdef import MenuOption, PlaceholderDef
from .overlays import KeyTestOverlay, MenuItem
from .themes import THEMES, theme_names
from .toolchain import ToolchainUnavailable, format_diagnostic

if TYPE_CHECKING:
    from .editor import Editor

_COMMANDS: list[Command] = []


def command(name: str, help: str, group: str, *, params: tuple[Param, ...] = (),
            quals: tuple[Qualifier, ...] = (), aliases: tuple[str, ...] = (),
            typing: bool = False) -> Callable:
    def deco(fn: Callable[["Editor", Args], Any]) -> Callable:
        _COMMANDS.append(Command(name, fn, help, list(params), list(quals), list(aliases),
                                 group, typing))
        return fn
    return deco


def register_all(editor: "Editor") -> None:
    for cmd in _COMMANDS:
        editor.commands.register(Command(cmd.name, cmd.handler, cmd.help, list(cmd.params),
                                         list(cmd.qualifiers), list(cmd.aliases), cmd.group,
                                         cmd.typing))
    editor.help_topics.update({
        "KEYPAD": lambda ed, rest: show_keypad(ed),
        "KEYS": lambda ed, rest: show_keys(ed),
        "COMMANDS": lambda ed, rest: show_commands(ed),
        "TOKENS": lambda ed, rest: show_tokens(ed, None),
        "PLACEHOLDERS": lambda ed, rest: show_placeholders(ed, None),
        "TOKEN": lambda ed, rest: _help_named(ed, "TOKEN", rest),
        "PLACEHOLDER": lambda ed, rest: _help_named(ed, "PLACEHOLDER", rest),
        "INDICATED": lambda ed, rest: help_indicated(ed, Args()),
    })


# ============================================================================
# Moving
# ============================================================================


def _vertical(ed: "Editor", delta: int) -> None:
    buf = ed.buffer
    goal = buf.goal_col if buf.goal_col is not None else buf.col
    buf.set_cursor(buf.row + delta, goal, keep_goal=True)
    buf.goal_col = goal


@command("MOVE UP", "Move the cursor up one line.", "Moving")
def move_up(ed: "Editor", args: Args) -> None:
    _vertical(ed, -1)


@command("MOVE DOWN", "Move the cursor down one line.", "Moving")
def move_down(ed: "Editor", args: Args) -> None:
    _vertical(ed, 1)


@command("MOVE LEFT", "Move the cursor left one character.", "Moving")
def move_left(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    if buf.col > 0:
        buf.set_cursor(buf.row, buf.col - 1)
    elif buf.row > 0:
        buf.set_cursor(buf.row - 1, len(buf.lines[buf.row - 1]))


@command("MOVE RIGHT", "Move the cursor right one character.", "Moving")
def move_right(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    if buf.col < len(buf.current_line()):
        buf.set_cursor(buf.row, buf.col + 1)
    elif buf.row < len(buf.lines) - 1:
        buf.set_cursor(buf.row + 1, 0)


_WORD = re.compile(r"[A-Za-z0-9_]")


@command("MOVE WORD LEFT", "Move to the start of the previous word.", "Moving")
def move_word_left(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    row, col = buf.cursor
    if col == 0:
        if row > 0:
            buf.set_cursor(row - 1, len(buf.lines[row - 1]))
        return
    line = buf.lines[row]
    c = col
    while c > 0 and not _WORD.match(line[c - 1]):
        c -= 1
    while c > 0 and _WORD.match(line[c - 1]):
        c -= 1
    buf.set_cursor(row, c)


@command("MOVE WORD RIGHT", "Move to the start of the next word.", "Moving")
def move_word_right(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    row, col = buf.cursor
    line = buf.lines[row]
    if col >= len(line):
        if row < len(buf.lines) - 1:
            buf.set_cursor(row + 1, 0)
        return
    c = col
    while c < len(line) and _WORD.match(line[c]):
        c += 1
    while c < len(line) and not _WORD.match(line[c]):
        c += 1
    buf.set_cursor(row, c)


@command("MOVE LINE START", "Go to the first word of the line (again: column 1).", "Moving")
def move_line_start(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    first = len(ph.indent_of(buf.current_line()))
    buf.set_cursor(buf.row, first if buf.col != first else 0)


@command("MOVE LINE END", "Go to the end of the line.", "Moving")
def move_line_end(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    buf.set_cursor(buf.row, len(buf.current_line()))


@command("MOVE PAGE UP", "Scroll up one screen.", "Moving")
def move_page_up(ed: "Editor", args: Args) -> None:
    step = max(1, ed.window.text_height - 1)
    ed.window.top = max(0, ed.window.top - step)
    _vertical(ed, -step)


@command("MOVE PAGE DOWN", "Scroll down one screen.", "Moving")
def move_page_down(ed: "Editor", args: Args) -> None:
    step = max(1, ed.window.text_height - 1)
    ed.window.top = min(max(0, len(ed.buffer.lines) - 1), ed.window.top + step)
    _vertical(ed, step)


@command("GOTO TOP", "Go to the first line of the buffer.", "Moving")
def goto_top(ed: "Editor", args: Args) -> None:
    ed.buffer.set_cursor(0, 0)


@command("GOTO BOTTOM", "Go to the end of the buffer.", "Moving")
def goto_bottom(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    buf.set_cursor(len(buf.lines) - 1, len(buf.lines[-1]))


@command("GOTO LINE", "Go to a line by number.", "Moving",
         params=(Param("line", "int", required=True, prompt="Go to line: "),))
def goto_line(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    n = args["line"]
    if not 1 <= n <= len(buf.lines):
        ed.warn("LINERANGE", f"{buf.name} has lines 1 to {len(buf.lines)}; going to the nearest")
    buf.set_cursor(max(0, min(n - 1, len(buf.lines) - 1)), 0)
    buf.set_cursor(buf.row, len(ph.indent_of(buf.current_line())))


# ============================================================================
# Editing
# ============================================================================

_OPENERS = ("BEGIN", "REPEAT", "THEN", "DO", "ELSE", "OF", "RECORD", "VAR", "CONST", "TYPE")


@command("NEW LINE", "Split the line at the cursor (keeps the indentation).", "Editing",
         typing=True)
def new_line(ed: "Editor", args: Args) -> None:
    if not ed.ensure_writable():
        return
    buf = ed.buffer
    row, col = buf.cursor
    line = buf.lines[row]
    left, right = line[:col], line[col:]
    indent = ph.indent_of(line)[:col]
    lang = buf.language
    if lang is not None:
        words = re.findall(r"[A-Za-z_]+", left.upper())
        if words and words[-1] in _OPENERS and left.rstrip().upper().endswith(words[-1]):
            indent += " " * lang.tab_increment
    if left.strip() == "":
        left = ""
    with buf.change():
        buf.replace_line(row, left.rstrip() if left.strip() else left)
        buf.insert(row, len(buf.lines[row]), "\n" + indent + right.lstrip(" "))
    buf.set_cursor(row + 1, len(indent))
    ed.overtyped = None


@command("DELETE PREVIOUS CHARACTER", "Delete the character left of the cursor (Backspace).",
         "Editing", typing=True)
def delete_previous(ed: "Editor", args: Args) -> None:
    if not ed.ensure_writable():
        return
    buf = ed.buffer
    row, col = buf.cursor
    if col > 0:
        with buf.change(group=("bs", row, col), next_group=("bs", row, col - 1)):
            buf.delete(row, col - 1, row, col)
        buf.set_cursor(row, col - 1)
    elif row > 0:
        prev = len(buf.lines[row - 1])
        with buf.change():
            buf.delete(row - 1, prev, row, 0)
        buf.set_cursor(row - 1, prev)


@command("DELETE CHARACTER", "Delete the character under the cursor (Delete).", "Editing",
         typing=True)
def delete_char(ed: "Editor", args: Args) -> None:
    if not ed.ensure_writable():
        return
    buf = ed.buffer
    row, col = buf.cursor
    if col < len(buf.lines[row]):
        with buf.change(group=("del", row, col), next_group=("del", row, col)):
            buf.delete(row, col, row, col + 1)
    elif row < len(buf.lines) - 1:
        with buf.change():
            buf.delete(row, col, row + 1, 0)
    buf.set_cursor(row, col)


@command("DELETE LINE", "Delete the whole line the cursor is on.", "Editing")
def delete_line(ed: "Editor", args: Args) -> None:
    if not ed.ensure_writable():
        return
    buf = ed.buffer
    row = buf.row
    with buf.change():
        buf.delete_lines(row, row + 1)
    buf.set_cursor(min(row, len(buf.lines) - 1), 0)


@command("CHANGE MODE", "Switch between Insert and Overstrike typing (Insert key).", "Editing")
def change_mode(ed: "Editor", args: Args) -> None:
    ed.insert_mode = not ed.insert_mode
    ed.info("MODE", "Insert mode: typing pushes text right" if ed.insert_mode
            else "Overstrike mode: typing replaces the text under the cursor")


@command("SET MODE", "Choose Insert or Overstrike typing.", "Editing",
         params=(Param("mode", "choice", required=True, prompt="Mode (INSERT or OVERSTRIKE): ",
                       choices=["INSERT", "OVERSTRIKE"]),))
def set_mode(ed: "Editor", args: Args) -> None:
    ed.insert_mode = args["mode"] == "INSERT"
    ed.info("MODE", f"{args['mode'].capitalize()} mode")


@command("UNDO", "Undo the last change.", "Editing")
def undo(ed: "Editor", args: Args) -> None:
    if ed.buffer.undo():
        ed.overtyped = None
        ed.info("UNDONE", "undid the last change (Ctrl-Y redoes it)")
    else:
        ed.info("NOUNDO", "nothing to undo")


@command("REDO", "Redo a change you undid.", "Editing")
def redo(ed: "Editor", args: Args) -> None:
    if ed.buffer.redo():
        ed.info("REDONE", "redid the change")
    else:
        ed.info("NOREDO", "nothing to redo")


def _search(ed: "Editor", text: str, forward: bool) -> None:
    buf = ed.buffer
    exact = text != text.lower()
    needle = text if exact else text.lower()
    lines = buf.lines if exact else [l.lower() for l in buf.lines]
    row, col = buf.cursor
    n = len(lines)
    if forward:
        order = [(row, col + 1)] + [(r % n, 0) for r in range(row + 1, row + n + 1)]
        for i, (r, c) in enumerate(order):
            hit = lines[r].find(needle, c)
            if hit >= 0:
                buf.set_cursor(r, hit)
                if i > 0 and r <= row and (r, hit) <= (row, col):
                    ed.info("WRAPPED", f'found "{text}" after going back to the top')
                return
    else:
        order = [(row, col)] + [(r % n, None) for r in range(row - 1, row - n - 1, -1)]
        for i, (r, c) in enumerate(order):
            hay = lines[r] if c is None else lines[r][:c]
            hit = hay.rfind(needle)
            if hit >= 0:
                buf.set_cursor(r, hit)
                if i > 0 and (r, hit) >= (row, col):
                    ed.info("WRAPPED", f'found "{text}" after going round from the bottom')
                return
    ed.warn("STRNOTFOUND", f'could not find "{text}"')


@command("FIND", "Search for text (lower-case text matches any case).", "Editing",
         params=(Param("text", "rest", required=True, prompt="Find: ",
                       default=lambda ed: ed.last_search),),
         quals=(Qualifier("REVERSE"), Qualifier("FORWARD")), aliases=("SEARCH",))
def find(ed: "Editor", args: Args) -> None:
    ed.last_search = args["text"]
    forward = ed.direction == "FORWARD"
    if args.qual("REVERSE"):
        forward = False
    if args.qual("FORWARD"):
        forward = True
    _search(ed, args["text"], forward)


@command("FIND NEXT", "Find the next place the last search text appears (F3).", "Editing")
def find_next(ed: "Editor", args: Args) -> None:
    if not ed.last_search:
        ed.execute("FIND")
        return
    _search(ed, ed.last_search, ed.direction == "FORWARD")


@command("SET FORWARD", "Searches go towards the end of the buffer.", "Editing")
def set_forward(ed: "Editor", args: Args) -> None:
    ed.direction = "FORWARD"
    ed.info("DIRECTION", "searching forward")


@command("SET REVERSE", "Searches go towards the start of the buffer.", "Editing")
def set_reverse(ed: "Editor", args: Args) -> None:
    ed.direction = "REVERSE"
    ed.info("DIRECTION", "searching in reverse")


# ============================================================================
# Placeholders and templates
# ============================================================================


def _apply(ed: "Editor", buf: Buffer, row: int, start: int, end: int, body: list[str],
           dup: ph.Duplication | None) -> None:
    res = ph.apply_template(buf.lines, row, start, end, body, dup)
    with buf.change():
        buf.set_lines(res.lines)
    buf.set_cursor(*res.cursor)
    ed.overtyped = None


def token_at_cursor(ed: "Editor", *, just_typed: bool = False):
    """The template word at the cursor; with ``just_typed`` it must end at the cursor."""
    buf = ed.buffer
    lang = buf.language
    if lang is None:
        return None
    w = ph.word_at(buf.current_line(), buf.col)
    if w is None or (just_typed and w[1] != buf.col):
        return None
    tok = lang.token(w[2])
    return (w, tok) if tok else None


def expand_token(ed: "Editor") -> bool:
    found = token_at_cursor(ed, just_typed=True)
    if found is None:
        return False
    (start, end, _), tok = found
    if not ed.ensure_writable():
        return True
    buf = ed.buffer
    lang = buf.language
    dup = None
    ot = ed.overtyped
    if ot and ot.buffer is buf and ot.row == buf.row and ot.col == start:
        old = ot.placeholder
        stand_in = ph.Placeholder(buf.row, start, end, old.name, old.optional, old.is_list)
        dup = ph.duplication_for(stand_in, lang.placeholder(old.name), buf.current_line())
    _apply(ed, buf, buf.row, start, end, tok.body, dup)
    return True


def finish_list_item(ed: "Editor") -> bool:
    """After typing over a vertical list placeholder, add the separator and a
    fresh copy of the placeholder on the next line (what expanding would do)."""
    ot = ed.overtyped
    buf = ed.buffer
    lang = buf.language
    if ot is None or ot.buffer is not buf or ot.row != buf.row or lang is None:
        return False
    line = buf.current_line()
    if buf.col <= ot.col or line[buf.col:].strip():
        return False
    old = ot.placeholder
    typed = line[ot.col:buf.col].rstrip()
    if not typed:
        return False
    stand_in = ph.Placeholder(buf.row, ot.col, buf.col, old.name, old.optional, old.is_list)
    dup = ph.duplication_for(stand_in, lang.placeholder(old.name), line)
    if dup is None or not dup.vertical:
        return False
    if dup.separator.strip() and typed.endswith(dup.separator.strip()):
        dup = ph.Duplication(dup.text, "", True)
    row = buf.row
    _apply(ed, buf, row, ot.col, buf.col, [typed], dup)
    buf.set_cursor(row + 1, len(ph.base_indent(buf.lines[row], ot.col)))
    return True


def expand_placeholder(ed: "Editor", cur: ph.Placeholder) -> None:
    buf = ed.buffer
    lang = buf.language
    defn = lang.placeholder(cur.name) if lang else None
    if defn is None:
        ed.warn("NOTDEFINED", f"{cur.text} is not defined for "
                f"{lang.display_name if lang else 'this buffer'}; type over it instead")
        return
    if not ed.ensure_writable():
        return
    dup = ph.duplication_for(cur, defn, buf.lines[cur.row])
    if defn.type == "NONTERMINAL":
        _apply(ed, buf, cur.row, cur.start, cur.end, defn.body, dup)
    elif defn.type == "MENU":
        _open_menu(ed, buf, cur, defn, dup)
    else:
        example = f" For example: {defn.example[0].strip()}" if defn.example else ""
        ed.info("TERMINAL", f"type your own text over {cur.text}: {defn.summary}{example}")


def _option_detail(lang, opt: MenuOption) -> str:
    if opt.description:
        return opt.description
    if opt.kind == "TOKEN" and lang.token(opt.text):
        return lang.token(opt.text).summary
    if opt.kind == "PLACEHOLDER" and lang.placeholder(opt.text):
        return lang.placeholder(opt.text).summary
    return ""


def _open_menu(ed: "Editor", buf: Buffer, cur: ph.Placeholder, defn: PlaceholderDef,
               dup: ph.Duplication | None) -> None:
    lang = buf.language
    items = [MenuItem(opt.text, _option_detail(lang, opt), opt) for opt in defn.options]

    def select(item: MenuItem) -> None:
        if ph.placeholder_at(buf.lines, cur.row, cur.start) != cur:
            ed.warn("MOVED", "the placeholder changed while the menu was open")
            return
        _choose(ed, buf, cur, item.value, dup)

    def help_for(item: MenuItem) -> None:
        opt = item.value
        if opt.kind == "TOKEN":
            token_help(ed, lang.token(opt.text))
        elif opt.kind == "PLACEHOLDER":
            placeholder_help(ed, opt.text)
        else:
            ed.info("CHOICE", f"{opt.text}: {item.detail or 'inserted as it is'}")

    ed.menu(cur.name, items, select, on_help=help_for,
            on_cancel=lambda: ed.info("CANCELLED", f"menu closed; {cur.text} is unchanged"),
            on_tab=lambda: _goto_placeholder(ed, True),
            on_shift_tab=lambda: _goto_placeholder(ed, False))
    ed.show(f"{cur.text}: Enter picks, Tab skips it, Esc cancels, F1 explains", "I", log=False)


def _choose(ed: "Editor", buf: Buffer, cur: ph.Placeholder, opt: MenuOption,
            dup: ph.Duplication | None) -> None:
    lang = buf.language
    if opt.kind == "TOKEN":
        body = lang.token(opt.text).body
    elif opt.kind == "PLACEHOLDER":
        target = lang.placeholder(opt.text)
        if target.type == "MENU":
            _open_menu(ed, buf, cur, target, dup)
            return
        body = target.body if target.type == "NONTERMINAL" else [ph.make_placeholder(target.name)]
    else:
        body = [opt.text]
    _apply(ed, buf, cur.row, cur.start, cur.end, body, dup)


def _goto_placeholder(ed: "Editor", forward: bool) -> bool:
    buf = ed.buffer
    finder = ph.next_placeholder if forward else ph.previous_placeholder
    found = finder(buf.lines, buf.row, buf.col)
    if found is None:
        if ph.placeholder_at(buf.lines, buf.row, buf.col):
            ed.info("LASTPLACEHOLDER", "this is the only placeholder left")
        else:
            ed.info("NOPLACEHOLDERS", "there are no placeholders left in this buffer")
        return False
    target, _wrapped = found
    buf.set_cursor(target.row, target.start)
    return True


@command("TAB", "Expand the template word or placeholder at the cursor; after typing over "
         "a list placeholder, start the next item; otherwise go to the next placeholder (Tab).",
         "Placeholders")
def tab(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    lang = buf.language
    cur = ph.placeholder_at(buf.lines, buf.row, buf.col)
    if cur is not None:
        defn = lang.placeholder(cur.name) if lang else None
        if defn is not None and defn.expandable:
            expand_placeholder(ed, cur)
        else:
            _goto_placeholder(ed, True)
        return
    if expand_token(ed):
        return
    if finish_list_item(ed):
        return
    if ph.scan(buf.lines):
        _goto_placeholder(ed, True)
        return
    if not ed.ensure_writable():
        return
    step = lang.tab_increment if lang else 4
    spaces = step - (buf.col % step)
    row, col = buf.cursor
    with buf.change():
        buf.insert(row, col, " " * spaces)
    buf.set_cursor(row, col + spaces)


@command("EXPAND", "Expand the placeholder or template word at the cursor (Ctrl-E).",
         "Placeholders")
def expand(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    cur = ph.placeholder_at(buf.lines, buf.row, buf.col)
    if cur is not None:
        expand_placeholder(ed, cur)
        return
    if expand_token(ed):
        return
    ed.warn("NOTHINGTOEXPAND", "nothing to expand here: put the cursor on a placeholder, "
            "or just after a template word such as IF, and press Tab")


@command("NEXT PLACEHOLDER", "Go to the next placeholder without expanding (Ctrl-N).",
         "Placeholders")
def next_placeholder(ed: "Editor", args: Args) -> None:
    _goto_placeholder(ed, True)


@command("PREVIOUS PLACEHOLDER", "Go back to the previous placeholder (Shift-Tab).",
         "Placeholders")
def previous_placeholder(ed: "Editor", args: Args) -> None:
    _goto_placeholder(ed, False)


@command("GOTO PLACEHOLDER", "Go to the next (or with /REVERSE the previous) placeholder.",
         "Placeholders", quals=(Qualifier("FORWARD"), Qualifier("REVERSE")))
def goto_placeholder(ed: "Editor", args: Args) -> None:
    _goto_placeholder(ed, not args.qual("REVERSE"))


@command("ERASE PLACEHOLDER", "Remove the placeholder at the cursor; an optional list "
         "placeholder takes its separator with it (Ctrl-K).", "Placeholders")
def erase_placeholder(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    cur = ph.placeholder_at(buf.lines, buf.row, buf.col)
    if cur is None:
        ed.warn("NOPLACEHOLDER", "the cursor is not on a placeholder (Tab moves to the next one)")
        return
    if not ed.ensure_writable():
        return
    lang = buf.language
    defn = lang.placeholder(cur.name) if lang else None
    res = ph.erase(buf.lines, cur, defn)
    with buf.change():
        buf.set_lines(res.lines)
    buf.set_cursor(*res.cursor)
    ed.overtyped = None


@command("SHOW TOKENS", "List the template words you can expand with Tab.", "Placeholders")
def show_tokens_cmd(ed: "Editor", args: Args) -> None:
    show_tokens(ed, None)


@command("SHOW PLACEHOLDERS", "List the placeholders of the current language.", "Placeholders")
def show_placeholders_cmd(ed: "Editor", args: Args) -> None:
    show_placeholders(ed, None)


def _language_or_warn(ed: "Editor"):
    lang = ed.buffer.language
    if lang is None:
        for buf in ed.file_buffers():
            if buf.language:
                return buf.language
        lang = ed.languages.get("PASCAL")
    if lang is None:
        ed.warn("NOLANGUAGE", "no language definitions are loaded")
    return lang


def show_tokens(ed: "Editor", _unused: Any) -> None:
    lang = _language_or_warn(ed)
    if lang is None:
        return
    lines = [f"Template words for {lang.display_name}. Type one and press Tab to expand it.", ""]
    for tok in sorted(lang.tokens.values(), key=lambda t: t.name):
        lines.append(f"  {tok.name:<12} {tok.summary}")
    lines += ["", "HELP TOKEN name shows one in full, with an example."]
    ed.view_text(f"{lang.display_name} tokens", lines)


def show_placeholders(ed: "Editor", _unused: Any) -> None:
    lang = _language_or_warn(ed)
    if lang is None:
        return
    lines = [f"Placeholders for {lang.display_name}. %{{name}}% is required, "
             "%[name]% optional, ... means it can repeat.", ""]
    for p in sorted(lang.placeholders.values(), key=lambda p: p.name.lower()):
        lines.append(f"  {p.name:<22} {p.type.lower():<12} {p.summary}")
    lines += ["", "HELP PLACEHOLDER name shows one in full, with an example."]
    ed.view_text(f"{lang.display_name} placeholders", lines)


_TYPE_WORDS = {
    "MENU": "Tab opens a menu of choices",
    "NONTERMINAL": "Tab expands it into more Pascal",
    "TERMINAL": "you type your own text over it",
}


def placeholder_help(ed: "Editor", target: ph.Placeholder | str) -> None:
    lang = _language_or_warn(ed)
    if lang is None:
        return
    if isinstance(target, str):
        name, text, optional, is_list = target, ph.make_placeholder(target), False, False
    else:
        name, text, optional, is_list = target.name, target.text, target.optional, target.is_list
    defn = lang.placeholder(name)
    if defn is None:
        ed.warn("NOTDEFINED", f"{text} is not defined for {lang.display_name}")
        return
    kind = "optional" if optional else "required"
    if is_list:
        kind += ", can repeat"
    lines = [f"Placeholder {text}   ({kind}; {_TYPE_WORDS[defn.type]})", ""]
    lines += defn.description + [""]
    if defn.example:
        lines += ["Example:"] + [f"    {e}" for e in defn.example] + [""]
    if defn.type == "MENU":
        lines.append("Choices:")
        for opt in defn.options:
            lines.append(f"    {opt.text:<18} {_option_detail(lang, opt)}")
        lines.append("")
    elif defn.type == "NONTERMINAL":
        lines += ["Tab turns it into:"] + [f"    {b}" for b in defn.body] + [""]
    lines.append("What you can do here:")
    lines.append("    Type          replace the placeholder with your own text")
    if defn.expandable:
        lines.append("    Tab           " + ("open the menu" if defn.type == "MENU" else "expand it"))
    else:
        lines.append("    Tab           go to the next placeholder")
    lines.append("    Shift-Tab     go back to the previous placeholder")
    lines.append("    Ctrl-K        erase it" + (" (it is optional, so that is fine)" if optional
                                               else " (it is required: Pascal needs something here)"))
    ed.view_text(f"Help: {text}", lines)


def token_help(ed: "Editor", tok) -> None:
    if tok is None:
        return
    lang = _language_or_warn(ed)
    lines = [f"Template word {tok.name}" + (f" ({lang.display_name})" if lang else ""), ""]
    lines += tok.description + [""]
    if tok.example:
        lines += ["Example:"] + [f"    {e}" for e in tok.example] + [""]
    lines += [f"Type {tok.name} and press Tab to get:"] + [f"    {b}" for b in tok.body]
    lines += ["", "Then Tab moves from placeholder to placeholder so you can fill them in."]
    ed.view_text(f"Help: {tok.name}", lines)


def _help_named(ed: "Editor", kind: str, name: str) -> None:
    name = name.strip()
    lang = _language_or_warn(ed)
    if lang is None:
        return
    if not name:
        (show_tokens if kind == "TOKEN" else show_placeholders)(ed, None)
        return
    if kind == "TOKEN":
        tok = lang.token(name)
        if tok is None:
            ed.warn("NOTOKEN", f"{name.upper()} is not a template word; SHOW TOKENS lists them")
        else:
            token_help(ed, tok)
    else:
        placeholder_help(ed, name.strip("%{}[].").strip())


# ============================================================================
# Files and buffers
# ============================================================================


def _save(ed: "Editor", buf: Buffer, path: str | None = None) -> None:
    if path is not None and not os.path.isabs(path):
        path = os.path.join(ed.cwd, path)
    version = buf.save(path)
    if buf.language is None:
        buf.language = ed.languages.for_file(buf.path or "")
    n = len(buf.lines)
    ed.info("WRITTEN", f"{n} line{'s' if n != 1 else ''} written to file "
            f"{ed.relative(buf.path)};{version}")


def _ask_file_name(ed: "Editor", buf: Buffer, then: Callable[[], Any] | None = None) -> None:
    def submit(name: str) -> None:
        if not name.strip():
            ed.info("CANCELLED", "not saved")
            return
        _save(ed, buf, name.strip())
        if then:
            then()

    ed.prompt(f"Write {buf.name} to file: ", submit,
              completer=lambda t: _file_completion(ed, t))


def _file_completion(ed: "Editor", partial: str):
    from .commands import Completion, _common_prefix
    cands = complete_files(ed.cwd, partial)
    if len(cands) == 1:
        return Completion(cands[0], cands)
    common = _common_prefix(cands)
    return Completion(common if len(common) > len(partial) else partial, cands)


@command("WRITE FILE", "Save the buffer as a new version (HELLO.PAS;1, ;2, ...) (Ctrl-S).",
         "Files", params=(Param("file", "file"),), aliases=("SAVE", "SAVE FILE", "WRITE"))
def write_file(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    if buf.system:
        ed.warn("SYSBUFFER", f"{buf.name} is a system buffer and is not saved; "
                "Ctrl-W goes back to your file")
        return
    name = args.get("file")
    if name:
        _save(ed, buf, name)
    elif buf.path:
        _save(ed, buf)
    else:
        _ask_file_name(ed, buf)


@command("GOTO FILE", "Open a file, or switch to it if it is already open (Ctrl-O).", "Files",
         params=(Param("file", "file", required=True, prompt="Open file: "),),
         aliases=("OPEN", "EDIT"))
def goto_file(ed: "Editor", args: Args) -> None:
    try:
        ed.open_file(args["file"])
    except FileNotFoundError as e:
        ed.error("FILENOTFOUND", str(e))
    except IsADirectoryError:
        ed.error("ISDIR", f"{args['file']} is a directory")
    except OSError as e:
        ed.error("OPENIN", f"cannot open {args['file']}: {e.strerror or e}")


@command("INCLUDE FILE", "Insert the contents of a file at the cursor.", "Files",
         params=(Param("file", "file", required=True, prompt="Include file: "),))
def include_file(ed: "Editor", args: Args) -> None:
    if not ed.ensure_writable():
        return
    path = files.resolve_name(ed.cwd, args["file"])
    try:
        _base, lines, _ = files.load(path)
    except OSError as e:
        ed.error("OPENIN", f"cannot read {args['file']}: {e}")
        return
    if lines is None:
        ed.error("FILENOTFOUND", f"{args['file']} does not exist")
        return
    buf = ed.buffer
    with buf.change():
        end = buf.insert(buf.row, buf.col, "\n".join(lines))
    buf.set_cursor(*end)
    ed.info("INCLUDED", f"{len(lines)} lines inserted from {ed.relative(path)}")


@command("GOTO BUFFER", "Show another buffer in this window.", "Files",
         params=(Param("buffer", "buffer", required=True, prompt="Buffer: "),))
def goto_buffer(ed: "Editor", args: Args) -> None:
    name = args["buffer"]
    hits = [b for b in ed.buffers.values() if b.name.upper() == name.upper()] or \
           [b for b in ed.buffers.values() if b.name.upper().startswith(name.upper())]
    if len(hits) != 1:
        ed.error("NOSUCHBUF", f"no buffer called {name}; Ctrl-B lists them" if not hits else
                 f"{name} could be: {', '.join(b.name for b in hits)}")
        return
    ed.show_buffer(hits[0])


def buffer_detail(buf: Buffer) -> str:
    parts = []
    if buf.modified:
        parts.append("modified")
    if buf.read_only:
        parts.append("read-only")
    parts.append(f"{len(buf.lines)} line{'s' if len(buf.lines) != 1 else ''}")
    return ", ".join(parts)


@command("SHOW BUFFERS", "Pick a buffer from a list (Ctrl-B).", "Files")
def show_buffers(ed: "Editor", args: Args) -> None:
    bufs = list(ed.buffers.values())
    items = [MenuItem(b.display_name, buffer_detail(b), b) for b in bufs]
    current = bufs.index(ed.buffer) if ed.buffer in bufs else 0
    ed.menu("Buffers", items, lambda item: ed.show_buffer(item.value), selected=current)


@command("PURGE", "Delete old versions of the file, keeping the newest (/KEEP=n).", "Files",
         quals=(Qualifier("KEEP", "int"),))
def purge(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    if not buf.path:
        ed.warn("NOFILE", "this buffer has no file")
        return
    keep = max(1, args.qual("KEEP", 1))
    removed = files.purge(buf.path, keep)
    ed.info("PURGED", f"{len(removed)} old version{'s' if len(removed) != 1 else ''} of "
            f"{buf.name} deleted")


def _quit_saving(ed: "Editor", bufs: list[Buffer]) -> None:
    for buf in bufs:
        if not buf.modified:
            continue
        if buf.path:
            _save(ed, buf)
        else:
            ed.show_buffer(buf)
            _ask_file_name(ed, buf, then=lambda: _quit_saving(ed, bufs))
            return
    ed.request_quit()


@command("EXIT", "Save every changed file, then leave LSE.", "Files")
def exit_cmd(ed: "Editor", args: Args) -> None:
    _quit_saving(ed, ed.modified_buffers())


@command("QUIT", "Leave LSE; asks first if there are unsaved changes (Ctrl-Q).", "Files")
def quit_cmd(ed: "Editor", args: Args) -> None:
    mods = ed.modified_buffers()
    if not mods:
        ed.request_quit()
        return
    names = ", ".join(b.display_name for b in mods)
    verb = "has" if len(mods) == 1 else "have"
    ed.ask(f"{names} {verb} unsaved changes. Save first? Y = save and quit, "
           "N = quit without saving, Esc = keep editing",
           {"y": lambda: _quit_saving(ed, mods), "n": ed.request_quit},
           on_cancel=lambda: ed.info("CANCELLED", "still editing"))


# ============================================================================
# Windows
# ============================================================================


@command("NEXT WINDOW", "Move to the other window (Ctrl-W).", "Windows",
         aliases=("OTHER WINDOW",))
def next_window(ed: "Editor", args: Args) -> None:
    if len(ed.windows) < 2:
        ed.info("ONEWINDOW", "there is only one window (TWO WINDOWS splits the screen)")
        return
    ed.current_window = (ed.current_window + 1) % len(ed.windows)


@command("TWO WINDOWS", "Split the screen into two windows.", "Windows",
         aliases=("SPLIT WINDOW",))
def two_windows(ed: "Editor", args: Args) -> None:
    if len(ed.windows) >= 2:
        ed.info("TWOWINDOWS", "there are already two windows (Ctrl-W moves between them)")
        return
    ed.split(ed.buffer)
    ed.current_window = 1


@command("ONE WINDOW", "Go back to a single window.", "Windows")
def one_window(ed: "Editor", args: Args) -> None:
    ed.one_window()


# ============================================================================
# COMPILE / LINK / RUN / REVIEW (through lse.toolchain)
# ============================================================================


def source_buffer(ed: "Editor") -> Buffer | None:
    """The Pascal file the build commands work on."""
    buf = ed.buffer
    if not buf.system:
        return buf
    if ed.review and ed.review.source:
        return ed.review.source
    for w in ed.windows:
        if not w.buffer.system:
            return w.buffer
    files_ = [b for b in ed.file_buffers() if b.path]
    return files_[0] if files_ else None


def _sev(d: Any) -> str:
    return str(getattr(d, "severity", "E"))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def fill_review_buffer(ed: "Editor") -> Buffer:
    rv = ed.system_buffer("$REVIEW")
    rv.local_keys = {"Enter": "GOTO SOURCE", "Esc": "END REVIEW"}
    r = ed.review
    lines: list[str] = []
    rows: list[int] = []
    if r is None or not r.diagnostics:
        lines.append("No errors. (F7 compiles again.)")
    else:
        src = r.source.name if r.source else "the program"
        lines.append(f"{_plural(len(r.diagnostics), 'message')} for {src}. "
                     "Enter goes to one, F8 next, Esc closes this window.")
        for i, d in enumerate(r.diagnostics, 1):
            rows.append(len(lines))
            text = format_diagnostic(d, ed.explain_messages).split("\n")
            lines.append(f"{i:>2}. {text[0]}")
            lines.extend(f"    {t}" for t in text[1:])
    if r is not None:
        r.entry_rows = rows
    rv.load_text(lines)
    rv.highlight_row = None
    return rv


class _ToolchainFailed(Exception):
    pass


def _call(ed: "Editor", what: str, fn: Callable[[], Any]) -> Any:
    """Call the toolchain; a crash in it becomes a message, not an editor crash."""
    try:
        return fn()
    except ToolchainUnavailable:
        raise
    except Exception as e:
        import traceback
        ed.messages_buffer.append_line(traceback.format_exc())
        ed.show(f"%LSE-F-TOOLFAIL, {what} stopped with an internal error: "
                f"{type(e).__name__}: {e} (details in buffer $MESSAGES)", "F")
        raise _ToolchainFailed() from e


def do_compile(ed: "Editor", list_file: bool = False) -> bool:
    try:
        return _do_compile(ed, list_file)
    except _ToolchainFailed:
        return False


def _do_compile(ed: "Editor", list_file: bool) -> bool:
    buf = source_buffer(ed)
    if buf is None:
        ed.error("NOSOURCE", "there is no Pascal file to compile; open one with Ctrl-O")
        return False
    if not buf.path:
        ed.error("NOFILE", f"{buf.name} has no file name yet; save it first with Ctrl-S")
        return False
    if buf.modified:
        buf.save()
    result = _call(ed, "COMPILE", lambda: ed.toolchain.compile(buf.path, list_file=list_file))
    st = ed.build_for(buf)
    st.compiled_state = buf.state_id
    st.compile_ok = bool(result.ok)
    st.diagnostics = list(result.diagnostics or [])
    st.obj_path = getattr(result, "obj_path", None)
    st.link_ok = None
    st.linked_state = None
    ed.review = Review(st.diagnostics, buf)
    fill_review_buffer(ed)
    errors = [d for d in st.diagnostics if _sev(d) in ("E", "F")]
    warnings = [d for d in st.diagnostics if _sev(d) == "W"]
    if result.ok and not errors:
        if warnings:
            ed.show(f"%LSE-W-COMPWARN, {buf.name} compiled with "
                    f"{_plural(len(warnings), 'warning')}. Press F8 to see them.", "W")
        else:
            ed.success("COMPILED", f"{buf.display_name} compiled with no errors")
        return True
    first = errors[0] if errors else (st.diagnostics[0] if st.diagnostics else None)
    count = len(errors) or len(st.diagnostics)
    text = f"%LSE-E-COMPERR, {buf.name} has {_plural(count, 'error')}. " \
           "Press F8 to go to the first one."
    if first is not None:
        text += "\n" + format_diagnostic(first, ed.explain_messages)
    ed.show(text, "E")
    return False


@command("COMPILE", "Compile the Pascal file (saving it first) (F7).", "Build",
         quals=(Qualifier("LIST", negatable=True, help="also write a .LIS listing"),))
def compile_cmd(ed: "Editor", args: Args) -> None:
    do_compile(ed, bool(args.qual("LIST", False)))


def _resolve_many(ed: "Editor", text: str, default_type: str) -> list[str]:
    names = [n for n in re.split(r"[,\s]+", text) if n]
    return [files.resolve_name(ed.cwd, n, default_type=default_type) for n in names]


def _missing_files(ed: "Editor", paths: list[str], what: str, maker: str) -> bool:
    for p in paths:
        if not os.path.isfile(p):
            ed.error("NOFILE", f"{ed.relative(p)} is not {what}; {maker} makes it")
            return True
    return False


def do_link(ed: "Editor", names: str | None = None, map_file: bool = True) -> bool:
    try:
        return _do_link(ed, names, map_file)
    except _ToolchainFailed:
        return False


def _do_link(ed: "Editor", names: str | None, map_file: bool) -> bool:
    buf = source_buffer(ed)
    st = ed.build_for(buf) if buf is not None else None
    if names:
        objs = _resolve_many(ed, names, ".OBJ")
        if not objs or _missing_files(ed, objs, "an object file", "COMPILE"):
            return False
    else:
        if buf is None or st is None:
            ed.error("NOSOURCE", "there is no program to link; open a .PAS file first")
            return False
        if st.compile_ok is None:
            ed.error("NOTCOMPILED", f"{buf.name} has not been compiled yet. Press F7 to compile "
                     "(or F5 to compile, link and run).")
            return False
        if not st.compile_ok:
            ed.error("COMPERR", f"{buf.name} did not compile. Fix the errors first "
                     "(F8 goes to them), then F7.")
            return False
        objs = [st.obj_path or os.path.splitext(buf.path or buf.name)[0] + ".OBJ"]
    result = _call(ed, "LINK", lambda: ed.toolchain.link(objs, map_file=map_file))
    diags = list(result.diagnostics or [])
    if st is not None and not names:
        st.linked_state = st.compiled_state
        st.link_ok = bool(result.ok)
        st.link_diagnostics = diags
        st.exe_path = getattr(result, "exe_path", None)
        st.map_path = getattr(result, "map_path", None)
    if result.ok:
        exe = getattr(result, "exe_path", None) or "the image"
        extra = ""
        warn = [d for d in diags if _sev(d) == "W"]
        if warn:
            ed.show(f"%LSE-W-LINKWARN, {ed.relative(exe)} written with "
                    f"{_plural(len(warn), 'warning')}\n" + format_diagnostic(warn[0], ed.explain_messages),
                    "W")
            return True
        if getattr(result, "map_path", None):
            extra = f"; the map is in {ed.relative(result.map_path)}"
        ed.success("LINKED", f"{ed.relative(exe)} written{extra}")
        return True
    text = "%LSE-E-LINKERR, LINK failed."
    if diags:
        text += "\n" + format_diagnostic(diags[0], ed.explain_messages)
    ed.show(text, "E")
    return False


@command("LINK", "Link the compiled program with the runtime library into an .EXE.", "Build",
         params=(Param("files", "rest"),),
         quals=(Qualifier("MAP", negatable=True, help="write a .MAP file (default)"),))
def link_cmd(ed: "Editor", args: Args) -> None:
    do_link(ed, args.get("files"), map_file=args.qual("MAP", True))


def do_run(ed: "Editor", name: str | None = None, seed: int | None = None,
           input_text: str | None = None) -> bool:
    try:
        return _do_run(ed, name, seed, input_text)
    except _ToolchainFailed:
        return False


def _do_run(ed: "Editor", name: str | None, seed: int | None, input_text: str | None) -> bool:
    buf = source_buffer(ed)
    st = ed.build_for(buf) if buf is not None else None
    if name:
        found = _resolve_many(ed, name, ".EXE")
        if not found:
            ed.error("NOIMAGE", "RUN needs the name of a program image, e.g. RUN GUESS")
            return False
        exe = found[0]
    else:
        if st is None or not st.link_ok or not st.exe_path:
            what = buf.name if buf is not None else "The program"
            ed.error("NOTLINKED", f"{what} has not been linked yet. Press F5 to compile, "
                     "link and run it.")
            return False
        exe = st.exe_path
    if not os.path.isfile(exe):
        ed.error("NOIMAGE", f"{ed.relative(exe)} does not exist; LINK makes it")
        return False
    label = os.path.basename(exe)
    if input_text is not None:
        text_in = input_text.replace("\\n", "\n")
        result = _call(ed, "RUN", lambda: ed.toolchain.run(exe, input_text=text_in, seed=seed))
    else:
        before = (f"Running {label}. Type your answers and press RETURN. "
                  "Ctrl-C stops the program.")
        after = "Program finished. Press RETURN to go back to LSE."
        result = _call(ed, "RUN", lambda: ed.host.run_program(
            before, after,
            lambda stdin, stdout: ed.toolchain.run(exe, stdin=stdin, stdout=stdout, seed=seed)))
    if result is None:
        ed.warn("INTERRUPTED", f"{label} was stopped with Ctrl-C")
        return False
    if st is not None and not name:
        st.ran_state = st.linked_state
        st.run_result = result
    out = ed.system_buffer("$OUTPUT")
    text = result.output or ""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    error = getattr(result, "error", None)
    if error is not None:
        lines += [""] + format_diagnostic(error, ed.explain_messages).split("\n")
        lines += list(getattr(result, "traceback", []) or [])
    out.load_text(lines or ["(the program printed nothing)"])
    if error is not None:
        ed.show(format_diagnostic(error, ed.explain_messages)
                + "\n(The output and traceback are in buffer $OUTPUT.)", "E")
        return False
    n = len([l for l in (result.output or "").split("\n") if l])
    ed.success("RAN", f"{label} finished (exit status {result.exit_status}); "
               f"{_plural(n, 'line')} of output in buffer $OUTPUT")
    return True


@command("RUN", "Run the linked program (/SEED=n repeats random numbers, "
         "/INPUT=\"text\" supplies its input).", "Build",
         params=(Param("file", "file"),),
         quals=(Qualifier("SEED", "int"), Qualifier("INPUT", "text")))
def run_cmd(ed: "Editor", args: Args) -> None:
    do_run(ed, args.get("file"), args.qual("SEED"), args.qual("INPUT"))


@command("BUILD", "COMPILE, LINK and RUN in one step (F5).", "Build",
         quals=(Qualifier("SEED", "int"), Qualifier("INPUT", "text")))
def build_cmd(ed: "Editor", args: Args) -> None:
    if do_compile(ed) and do_link(ed):
        do_run(ed, None, args.qual("SEED"), args.qual("INPUT"))


def _goto_diagnostic(ed: "Editor", index: int) -> None:
    r = ed.review
    assert r is not None
    r.index = index
    d = r.diagnostics[index]
    src = r.source
    dfile = getattr(d, "file", None)
    if dfile and src is not None and src.path:
        dpath = dfile if os.path.isabs(dfile) else os.path.join(ed.cwd, dfile)
        if os.path.normcase(files.split_version(dpath)[0]) != os.path.normcase(src.path) \
                and os.path.exists(dpath):
            src = ed.open_file(dfile)
    if src is not None:
        win = ed.window_showing(src)
        if win is None:
            win = next((w for w in ed.windows if not w.buffer.system), ed.window)
            ed.show_buffer(src, win)
        ed.select_window(win)
        line = getattr(d, "line", None) or 1
        col = getattr(d, "column", None) or 1
        src.set_cursor(line - 1, col - 1)
    rv = ed.buffers.get("$REVIEW")
    if rv is not None and index < len(r.entry_rows):
        rv.highlight_row = r.entry_rows[index]
        rv.set_cursor(r.entry_rows[index], 0)
        rwin = ed.window_showing(rv)
        if rwin is not None:
            rwin.top = max(0, r.entry_rows[index] - 1)
    ed.show(f"({index + 1} of {len(r.diagnostics)}) "
            + format_diagnostic(d, ed.explain_messages), _sev(d) if _sev(d) in "IWEF" else "E")


@command("NEXT ERROR", "Go to the next compiler message in the source (F8).", "Build")
def next_error(ed: "Editor", args: Args) -> None:
    r = ed.review
    if r is None or not r.diagnostics:
        ed.info("NOERRORS", "no errors to review (F7 compiles the program)")
        return
    index = r.index + 1
    if index >= len(r.diagnostics):
        index = len(r.diagnostics) - 1
        _goto_diagnostic(ed, index)
        ed.message.text += "\n(That is the last one; Shift-F8 goes back.)"
        return
    _goto_diagnostic(ed, index)


@command("PREVIOUS ERROR", "Go to the previous compiler message (Shift-F8).", "Build")
def previous_error(ed: "Editor", args: Args) -> None:
    r = ed.review
    if r is None or not r.diagnostics:
        ed.info("NOERRORS", "no errors to review (F7 compiles the program)")
        return
    _goto_diagnostic(ed, max(0, r.index - 1))


@command("REVIEW", "Show the compiler messages in a window below the code.", "Build")
def review_cmd(ed: "Editor", args: Args) -> None:
    if ed.review is None:
        ed.info("NOREVIEW", "nothing to review yet: compile first with F7")
        return
    rv = fill_review_buffer(ed)
    height = min(10, max(4, len(rv.lines) + 1))
    source_win = ed.window if not ed.buffer.system else None
    win = ed.split(rv, fixed_height=height)
    win.tags.add("review")
    if source_win is not None and ed.review.source is not None:
        ed.show_buffer(ed.review.source, source_win)
    ed.select_window(win)
    if ed.review.diagnostics:
        ed.review.index = -1
        rv.set_cursor(ed.review.entry_rows[0], 0)
        rv.highlight_row = ed.review.entry_rows[0]
        ed.info("REVIEW", "Enter goes to the message under the cursor; F8 next; Esc closes")


@command("GOTO SOURCE", "From the REVIEW window, go to the code for the message.", "Build")
def goto_source(ed: "Editor", args: Args) -> None:
    r = ed.review
    rv = ed.buffers.get("$REVIEW")
    if r is None or not r.diagnostics or rv is None:
        ed.info("NOERRORS", "no compiler messages to go to")
        return
    row = rv.row
    index = 0
    for i, start in enumerate(r.entry_rows):
        if start <= row:
            index = i
    _goto_diagnostic(ed, index)


@command("END REVIEW", "Close the REVIEW window and go back to the code.", "Build")
def end_review(ed: "Editor", args: Args) -> None:
    rv = ed.buffers.get("$REVIEW")
    win = ed.window_showing(rv) if rv is not None else None
    if win is None:
        ed.info("NOREVIEW", "the REVIEW window is not open")
        return
    ed.close_window(win)
    ed.info("REVIEWDONE", "back to your code")


@command("SET MESSAGES", "Turn the plain-English explanation of messages on or off.", "Build",
         quals=(Qualifier("EXPLAIN", negatable=True),))
def set_messages(ed: "Editor", args: Args) -> None:
    if "EXPLAIN" not in args.quals:
        ed.info("MESSAGES", "explanations are " + ("on" if ed.explain_messages else "off")
                + "; SET MESSAGES /EXPLAIN or /NOEXPLAIN changes it")
        return
    ed.explain_messages = bool(args.qual("EXPLAIN"))
    if ed.review is not None:
        fill_review_buffer(ed)
    ed.info("MESSAGES", "messages now come with an explanation and a hint"
            if ed.explain_messages else "messages are shown without explanations")


# ============================================================================
# Help, display, command line
# ============================================================================


def show_keypad(ed: "Editor") -> None:
    from .helpscreen import keypad_lines
    ed.view_text("LSE keypad", keypad_lines(ed), wrap=False,
                 footer="Esc returns to your program.  HELP KEYS lists every key.")


def show_keys(ed: "Editor") -> None:
    by_group: dict[str, list[str]] = {}
    for key, line in sorted(ed.keymap.bindings.items(), key=lambda kv: kv[1]):
        try:
            cmd = ed.commands.parse(line, ed).command
        except Exception:
            continue
        by_group.setdefault(cmd.group, []).append(f"  {describe_key(key):<12} {cmd.name:<26} {cmd.help}")
    lines = ["Every key runs an LSE> command; you can type the command instead (Ctrl-P).",
             "If your terminal keeps an F-key for itself, press Esc then the digit (Esc 5 = F5).",
             ""]
    for group in ("Placeholders", "Files", "Build", "Editing", "Moving", "Windows", "Help"):
        if group in by_group:
            lines += [group, *by_group[group], ""]
    ed.view_text("Keys", lines, wrap=False)


def show_commands(ed: "Editor") -> None:
    lines = ["Type these at LSE> (Ctrl-P or F10). Abbreviate any word (GO F = GOTO FILE);",
             "Tab completes. HELP name explains one command.", ""]
    groups: dict[str, list[Command]] = {}
    for cmd in ed.commands:
        groups.setdefault(cmd.group, []).append(cmd)
    for group in sorted(groups):
        lines.append(group)
        for cmd in groups[group]:
            keys = ed.keymap.describe_keys_for(cmd.name)
            lines.append(f"  {cmd.usage()}" + (f"   [{keys}]" if keys else ""))
            lines.append(f"      {cmd.help}")
        lines.append("")
    ed.view_text("Commands", lines)


def _help_topic_names(ed: "Editor") -> list[str]:
    return sorted(set(ed.help_topics) | {c.name for c in ed.commands})


@command("HELP", "Help on a topic: KEYPAD, KEYS, COMMANDS, TOKENS, PLACEHOLDERS, or a "
         "command name.", "Help",
         params=(Param("topic", "rest", completer=lambda ed, p: [
             t for t in _help_topic_names(ed) if t.startswith(p.upper())]),))
def help_cmd(ed: "Editor", args: Args) -> None:
    topic = (args.get("topic") or "").strip()
    if not topic:
        show_keypad(ed)
        return
    word, _, rest = topic.partition(" ")
    up = word.upper()
    hits = [k for k in ed.help_topics if k.startswith(up)]
    exact = [k for k in hits if k == up]
    if exact or len(hits) == 1:
        ed.help_topics[(exact or hits)[0]](ed, rest)
        return
    try:
        cmd = ed.commands.parse(topic, ed).command
    except Exception:
        cmd = None
    if cmd is not None:
        keys = ed.keymap.describe_keys_for(cmd.name)
        lines = [cmd.usage(), "", cmd.help]
        if keys:
            lines += ["", f"Key: {keys}"]
        if cmd.aliases:
            lines += ["", "Also: " + ", ".join(cmd.aliases)]
        for q in cmd.qualifiers:
            if q.help:
                lines.append(f"  /{q.name}: {q.help}")
        ed.view_text(f"Help: {cmd.name}", lines)
        return
    lang = _language_or_warn(ed)
    if lang is not None and lang.token(topic):
        token_help(ed, lang.token(topic))
        return
    if lang is not None and lang.placeholder(topic.strip("%{}[].")):
        placeholder_help(ed, topic.strip("%{}[]."))
        return
    ed.warn("NOHELP", f"no help on {topic}. Try HELP KEYS, HELP COMMANDS or HELP KEYPAD")


@command("HELP INDICATED", "Explain the placeholder or template word at the cursor; "
         "elsewhere show the keypad (F1).", "Help")
def help_indicated(ed: "Editor", args: Args) -> None:
    buf = ed.buffer
    cur = ph.placeholder_at(buf.lines, buf.row, buf.col)
    if cur is not None and buf.language is not None:
        placeholder_help(ed, cur)
        return
    found = token_at_cursor(ed)
    if found is not None:
        token_help(ed, found[1])
        return
    show_keypad(ed)


@command("SET THEME", "Change the colours: VT220 (white), AMBER or GREEN.", "Help",
         params=(Param("theme", "choice", required=True,
                       prompt=f"Theme ({', '.join(THEMES)}): ", choices=theme_names()),))
def set_theme(ed: "Editor", args: Args) -> None:
    ed.theme = args["theme"]
    ed.info("THEME", f"theme is now {ed.theme} ({THEMES[ed.theme].description})")


LINE_DRAWINGS = ["ACS", "UNICODE", "ASCII"]


@command("SET LINE_DRAWING", "How boxes are drawn: ACS (DEC graphics), UNICODE or ASCII; "
         "use ASCII if borders look like lqqqk.", "Help",
         params=(Param("style", "choice", required=True, prompt="Line drawing (ACS, UNICODE, ASCII): ",
                       choices=LINE_DRAWINGS),))
def set_line_drawing(ed: "Editor", args: Args) -> None:
    ed.line_drawing = args["style"]
    ed.info("LINEDRAWING", f"boxes are now drawn with {ed.line_drawing} characters")


@command("KEYTEST", "Show which keys reach LSE (same as lse --keytest).", "Help")
def keytest(ed: "Editor", args: Args) -> None:
    ed.push_overlay(KeyTestOverlay(on_close=lambda: ed.info("KEYTEST", "key test finished")))


@command("COMMAND", "Open the LSE> command line (Ctrl-P or F10).", "Help", aliases=("DO",))
def command_cmd(ed: "Editor", args: Args) -> None:
    ed.command_line()


@command("CANCEL", "Close the REVIEW window, or explain how to quit (Esc).", "Help")
def cancel(ed: "Editor", args: Args) -> None:
    rv = ed.buffers.get("$REVIEW")
    if rv is not None and ed.window_showing(rv) is not None:
        end_review(ed, args)
        return
    if ed.buffer.system and len(ed.windows) > 1:
        ed.close_window(ed.window)
        return
    ed.show("Nothing to cancel. To leave LSE press Ctrl-Q (or type QUIT after Ctrl-P).",
            "I", log=False)

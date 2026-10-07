"""Draw the editor state onto a ``VirtualScreen``.

Layout, top to bottom::

    window 0 text rows        regions["window0"]
    window 0 status line      regions["status0"]
    (window 1 text + status)  regions["window1"], regions["status1"]
    bottom panels             regions["message"], regions["command"], ...

Bottom panels come from ``editor.bottom_panels``; each returns a list of
lines, where a line is ``(text, role)`` or a list of such segments.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from . import placeholders as ph
from .vscreen import VirtualScreen
from .windows import Window, layout

if TYPE_CHECKING:
    from .editor import Editor

_SEV_ROLE = {"I": "message", "S": "message", "W": "message_warning",
             "E": "message_error", "F": "message_error"}


def message_panel(editor: "Editor", width: int) -> list:
    from .editor import MAX_MESSAGE_LINES
    msg = editor.message
    if msg is None:
        return [("", "message")]
    role = "message_hint" if msg.hint else _SEV_ROLE.get(msg.severity, "message")
    if msg.hint:
        text = msg.text
        return [(text if len(text) <= width else text[: width - 3] + "...", role)]
    out: list[str] = []
    for line in msg.lines:
        indent = len(line) - len(line.lstrip())
        wrapped = textwrap.wrap(line, width, subsequent_indent=" " * (indent + 2)) or [""]
        out.extend(wrapped)
    if len(out) > MAX_MESSAGE_LINES:
        out = out[:MAX_MESSAGE_LINES]
        last = out[-1]
        out[-1] = (last[: width - 4] + " ...") if len(last) > width - 4 else last + " ..."
    return [(line, role) for line in out]


def command_panel(editor: "Editor", width: int) -> list:
    return [[("LSE> ", "command"),
             ("Ctrl-P or F10 to type a command, F1 for help", "command_hint")]]


def status_text(editor: "Editor", win: Window, width: int) -> str:
    buf = win.buffer
    name = buf.display_name + (" *" if buf.modified else "")
    lang = buf.language.display_name if buf.language else ("System" if buf.system else "Text")
    mode = "Read-only" if buf.read_only else ("Insert" if editor.insert_mode else "Overstrike")
    position = f"{buf.row + 1}/{len(buf.lines)}"
    direction = "Forward" if editor.direction == "FORWARD" else "Reverse"
    middle = []
    for provider in editor.status_providers:
        seg = provider(editor, win)
        if seg:
            middle.append(seg)

    def compose(right_parts: list[str], mid: list[str], left: str) -> str:
        out = f"[ {left} ]"
        for seg in mid:
            out += f"--[ {seg} ]"
        right = "[ " + " | ".join(right_parts) + " ]"
        tail = "----"
        fill = width - len(out) - len(right) - len(tail)
        if fill < 2:
            return ""
        return out + "-" * fill + right + tail

    attempts = [
        ([lang, mode, direction, position], middle),
        ([lang, mode, position], middle),
        ([mode, position], middle),
        ([lang, mode, position], []),
        ([position], []),
    ]
    for right_parts, mid in attempts:
        text = compose(right_parts, mid, name)
        if text:
            return text
    return f"[ {name} ] {position}"[:width].ljust(width, "-")


def _draw_line(scr: VirtualScreen, row: int, line) -> None:
    segments = [line] if isinstance(line, tuple) else line
    base_role = segments[0][1] if segments else "text"
    scr.fill(row, base_role)
    col = 0
    for text, role in segments:
        col = scr.put(row, col, text, role)


def _draw_text_rows(editor: "Editor", scr: VirtualScreen, win: Window, top: int, left_col: int,
                    rows: int, cols: int) -> list[int]:
    buf = win.buffer
    win.text_height, win.text_width = rows, cols
    win.scroll_into_view()
    used = []
    for i in range(rows):
        r = win.top + i
        srow = top + i
        used.append(srow)
        if r < len(buf.lines):
            line = buf.lines[r]
            visible = line[win.left: win.left + cols]
            role = "highlight" if buf.highlight_row == r else "text"
            scr.put(srow, left_col, visible, role)
            if role == "highlight":
                scr.set_role(srow, left_col, left_col + cols, "highlight")
            elif "%" in line:
                for p in ph.scan_line(line, r):
                    s = max(p.start, win.left) - win.left
                    e = min(p.end, win.left + cols) - win.left
                    if e > s:
                        scr.set_role(srow, left_col + s, left_col + e, "placeholder")
        elif r == len(buf.lines):
            scr.put(srow, left_col, "[End of file]", "eof")
    return used


def draw_window(editor: "Editor", scr: VirtualScreen, win: Window, index: int, top: int,
                height: int, current: bool) -> None:
    w = scr.width
    if win.border:
        scr.box(top, 0, height, w, "border", title=win.title)
        rows = _draw_text_rows(editor, scr, win, top + 1, 1, max(1, height - 2), w - 2)
        win.screen_top = top + 1
        left_col = 1
    else:
        text_rows = height - (1 if win.show_status else 0)
        rows = _draw_text_rows(editor, scr, win, top, 0, max(1, text_rows), w)
        win.screen_top = top
        left_col = 0
        if win.show_status:
            srow = top + height - 1
            scr.fill(srow, "status" if current else "status_inactive")
            scr.put(srow, 0, status_text(editor, win, w), "status" if current else "status_inactive")
            scr.regions[f"status{index}"] = [srow]
    scr.regions[f"window{index}"] = rows
    scr.regions.setdefault("text_area", []).extend(rows)
    if current:
        buf = win.buffer
        crow = win.screen_top + buf.row - win.top
        ccol = left_col + buf.col - win.left
        scr.cursor = (crow, min(ccol, w - 1))


def render(editor: "Editor") -> VirtualScreen:
    h, w = editor.height, editor.width
    scr = VirtualScreen(h, w)
    panels = []
    for name, provider in editor.bottom_panels:
        lines = provider(editor, w) or []
        panels.append((name, lines))
    nbottom = sum(len(lines) for _, lines in panels)
    avail = max(2, h - nbottom)
    for index, (win, top, height) in enumerate(layout(editor.windows, avail)):
        draw_window(editor, scr, win, index, top, height, index == editor.current_window)
    row = avail
    for name, lines in panels:
        rows = []
        for line in lines:
            if row >= h:
                break
            _draw_line(scr, row, line)
            rows.append(row)
            row += 1
        scr.regions[name] = rows
    scr.buffer_cursor = scr.cursor
    for overlay in editor.overlays:
        overlay.draw(editor, scr)
    return scr

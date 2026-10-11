"""Windows: views onto buffers, and how the screen is shared between them.

There are at most two text windows (``TWO WINDOWS`` / ``ONE WINDOW``).
A window may ask for a fixed height (the REVIEW list, or a later LESSON
pane) and may be drawn with a border and title instead of a status line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .buffer import Buffer

MAX_WINDOWS = 2


@dataclass
class Window:
    buffer: Buffer
    border: bool = False
    title: str | None = None
    show_status: bool = True
    fixed_height: int | None = None
    top: int = 0
    left: int = 0
    text_height: int = 20
    text_width: int = 80
    screen_top: int = 0
    tags: set[str] = field(default_factory=set)

    def scroll_into_view(self) -> None:
        buf = self.buffer
        h = max(1, self.text_height)
        if buf.row < self.top:
            self.top = buf.row
        elif buf.row >= self.top + h:
            self.top = buf.row - h + 1
        self.top = max(0, min(self.top, max(0, len(buf.lines) - 1)))
        w = max(2, self.text_width)
        if buf.col < self.left:
            self.left = max(0, buf.col - w // 4)
        elif buf.col >= self.left + w - 1:
            self.left = buf.col - w + w // 4
        self.left = max(0, self.left)


def layout(windows: list[Window], rows: int) -> list[tuple[Window, int, int]]:
    """Split ``rows`` screen rows between windows; return (window, top, height)."""
    if not windows:
        return []
    if len(windows) == 1:
        return [(windows[0], 0, rows)]
    fixed = [w.fixed_height for w in windows]
    heights: list[int] = []
    if any(f is not None for f in fixed):
        free = rows - sum(min(f, rows - 3) for f in fixed if f is not None)
        flex = [i for i, f in enumerate(fixed) if f is None]
        for i, f in enumerate(fixed):
            if f is not None:
                heights.append(min(f, rows - 3))
            else:
                heights.append(max(3, free // max(1, len(flex))))
        if flex:
            heights[flex[-1]] += rows - sum(heights)
    else:
        first = (rows + 1) // 2
        heights = [first, rows - first]
    out = []
    top = 0
    for w, h in zip(windows, heights):
        out.append((w, top, max(1, h)))
        top += h
    return out

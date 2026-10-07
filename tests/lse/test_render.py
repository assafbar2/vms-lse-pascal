from lse_helpers import new_program

from lse.helpscreen import keypad_diagram, keypad_lines
from lse.overlays import KeyTestOverlay, TextViewOverlay
from lse.themes import ROLES, THEMES
from lse.vscreen import VirtualScreen


def test_layout_regions_24x80(hello):
    scr = hello.screen
    assert scr.height == 24 and scr.width == 80
    assert scr.regions["window0"] == list(range(0, 21))
    assert scr.regions["status0"] == [21]
    assert scr.regions["message"] == [22]
    assert scr.regions["command"] == [23]
    assert scr.line(0) == "PROGRAM Hello(INPUT, OUTPUT);"
    assert scr.line(4) == "[End of file]"
    assert scr.cursor == (0, 0)


def test_status_line_looks_like_lse(hello):
    status = hello.status
    assert len(status) == 80
    assert status.startswith("[ HELLO.PAS ]---")
    assert status.endswith("[ Pascal | Insert | Forward | 1/4 ]----")
    assert hello.screen.role_at(21, 0) == "status"
    hello.type("x").press("C-s")
    assert hello.status.startswith("[ HELLO.PAS;2 ]")


def test_status_line_providers_add_segments(hello):
    hello.editor.status_providers.append(lambda ed, win: "EDIT > COMPILE > LINK > RUN")
    assert "]--[ EDIT > COMPILE > LINK > RUN ]--" in hello.status


def test_status_line_squeezes_on_narrow_screens(tmp_path):
    from lse.testing import EditorHarness
    h = EditorHarness(tmp_path, size=(24, 40), files={"A.PAS": "x\n"})
    h.open("A.PAS")
    assert len(h.status) == 40 and "1/1" in h.status


def test_bottom_panels_are_extensible(hello):
    hello.editor.bottom_panels.insert(1, ("next", lambda ed, w: [("NEXT: press F7", "message")]))
    hello.editor.bottom_panels.append(("keybar", lambda ed, w: [("F1 Help  ^Q Quit", "status")]))
    scr = hello.screen
    assert scr.region("next") == ["NEXT: press F7"]
    assert scr.region("keybar") == ["F1 Help  ^Q Quit"]
    assert scr.regions["keybar"] == [23]
    assert scr.regions["status0"] == [19]


def test_placeholders_are_highlighted(h):
    new_program(h)
    scr = h.screen
    row = scr.regions["window0"][1]
    assert scr.role_at(row, 0) == "placeholder"
    assert scr.role_at(row, len("%[declarations]%...") - 1) == "placeholder"
    assert scr.role_at(0, 0) == "text"


def test_long_messages_wrap_to_five_lines(hello):
    hello.editor.show("x" * 500, "E")
    scr = hello.screen
    assert len(scr.regions["message"]) == 5
    assert scr.region("message")[-1].endswith("...")
    assert scr.role_at(scr.regions["message"][0], 0) == "message_error"


def test_long_explanations_are_trimmed_before_the_hint(hello):
    hello.editor.show("%LSE-E-COMPERR, X.PAS has 1 error.\n"
                      "%PASCAL-E-SEMIEXP, \";\" expected at line 5, column 3\n"
                      "  Explanation: " + "words " * 60 + "\n"
                      "  Hint: Add \";\" at the end of line 4.", "E")
    lines = hello.screen.region("message")
    assert len(lines) == 5
    assert lines[0].startswith("%LSE-E-COMPERR")
    assert lines[2].startswith("  Explanation:") and lines[3].endswith("...")
    assert lines[4] == '  Hint: Add ";" at the end of line 4.'


def test_horizontal_scroll_keeps_cursor_visible(tmp_path):
    from lse.testing import EditorHarness
    h = EditorHarness(tmp_path, files={"W.TXT": "a" * 200 + "END\n"})
    h.open("W.TXT").feed("<End>")
    scr = h.screen
    r, c = scr.cursor
    assert 0 <= c < 80 and "END" in scr.line(r)


def test_command_line_shows_hint_when_idle(hello):
    assert hello.command_line.startswith("LSE> Ctrl-P or F10")
    assert hello.screen.role_at(23, 0) == "command"
    assert hello.screen.role_at(23, 6) == "command_hint"


def test_themes_cover_every_role():
    assert set(THEMES) == {"VT220", "AMBER", "GREEN"}
    for theme in THEMES.values():
        for role in ROLES:
            fg, attrs = theme.style(role)
            assert fg in ("normal", "bright")
    assert "reverse" in THEMES["VT220"].style("status")[1]


def test_screen_only_uses_known_roles(h):
    new_program(h)
    for spec in ("", "<Tab>", "<Esc><F1>", "<Esc><C-p>"):
        h.feed(spec)
        scr = h.screen
        used = {role for row in scr.roles for role in row}
        assert used <= set(ROLES), used - set(ROLES)


def test_set_theme(hello):
    hello.command("SET THEME AMBER")
    assert hello.editor.theme == "AMBER"
    assert "amber phosphor" in hello.message


def test_box_drawing_and_ascii_view():
    scr = VirtualScreen(4, 10)
    scr.box(0, 0, 4, 10, title="T")
    assert scr.line(0) == "┌─[ T ]──┐"
    assert scr.line(3, ascii=True) == "+--------+"
    assert scr.runs(1)[0] == (0, "│", "border")


def test_keypad_help_screen(hello):
    hello.feed("<C-End>")
    hello.press("F1")
    assert isinstance(hello.overlay, TextViewOverlay)
    text = hello.screen.text()
    for label in ("PF1", "PF2", "GOLD", "HELP", "COMMAND", "EXPAND", "COMPILE", "ENTER",
                  "Ctrl-K", "Ctrl-P", "F7", "F8", "Esc then 1-9", "lse --keytest"):
        assert label in text, label
    assert "┌────────┬" in text
    hello.press("Esc")
    assert hello.overlay is None


def test_keypad_labels_follow_the_keymap(hello):
    ed = hello.editor
    ed.keymap.bind("F9", "COMPILE")
    ed.keymap.unbind("F7")
    assert "F9" in "\n".join(keypad_diagram(ed))


def test_keypad_fits_80_columns(hello):
    for line in keypad_lines(hello.editor):
        assert len(line) <= 76, line
    widths = {len(line) for line in keypad_diagram(hello.editor)}
    assert widths == {37}


def test_bordered_fixed_height_window_for_panes(hello):
    from lse.buffer import Buffer
    ed = hello.editor
    pane = Buffer("$LESSON", ["DO THIS: press Tab", "YOU WILL SEE: a menu"], read_only=True,
                  system=True)
    win = ed.split(pane, fixed_height=5)
    win.border, win.title, win.show_status = True, "Lesson 1 of 10: Welcome", False
    scr = hello.screen
    rows = scr.regions["window1"]
    assert len(rows) == 3
    top = rows[0] - 1
    assert scr.line(top).startswith("┌─[ Lesson 1 of 10: Welcome ]")
    assert scr.line(rows[0]) == "│DO THIS: press Tab" + " " * 60 + "│"
    assert "status1" not in scr.regions
    assert scr.regions["status0"] == [top - 1]
    assert ed.current_window == 0 and scr.cursor == (0, 0)


def test_set_line_drawing(hello):
    hello.command("SET LINE_DRAWING ASCII")
    assert hello.editor.line_drawing == "ASCII"
    hello.command("SET LINE_DRAWING uni")
    assert hello.editor.line_drawing == "UNICODE"


def test_keytest_overlay(h):
    h.command("KEYTEST")
    assert isinstance(h.overlay, KeyTestOverlay)
    assert "[ ] F5" in h.screen.text()
    h.press("F5")
    text = h.screen.text()
    assert "[x] F5" in text and "BUILD" in text
    h.feed("<Esc>7")  # Esc 7 arrives as F7
    assert "[x] F7" in h.screen.text()
    h.press("C-s")
    assert "WRITE FILE" in h.screen.text()
    h.feed("<Esc><Esc>")
    assert h.overlay is None

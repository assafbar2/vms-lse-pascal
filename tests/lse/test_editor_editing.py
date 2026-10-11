from lse.testing import EditorHarness


def plain(tmp_path, text="", name="T.TXT"):
    h = EditorHarness(tmp_path, files={name: text})
    h.open(name)
    return h


def test_typing_and_cursor(tmp_path):
    h = plain(tmp_path)
    h.type("hello")
    assert h.lines == ["hello"] and h.cursor == (0, 5)
    h.feed("<Left><Left>X")
    assert h.lines == ["helXlo"]
    h.feed("<Home>>")
    assert h.lines == [">helXlo"]
    h.feed("<End>!")
    assert h.lines == [">helXlo!"]


def test_enter_splits_and_keeps_indent(tmp_path):
    h = plain(tmp_path, "    abc def\n")
    h.feed("<End><Left><Left><Left><Enter>")
    assert h.lines == ["    abc", "    def"]
    assert h.cursor == (1, 4)


def test_pascal_enter_indents_after_begin(tmp_path):
    h = EditorHarness(tmp_path, files={"X.PAS": "BEGIN\n"})
    h.open("X.PAS")
    h.feed("<End><Enter>x := 1")
    assert h.lines[:2] == ["BEGIN", "  x := 1"]


def test_backspace_and_delete_join_lines(tmp_path):
    h = plain(tmp_path, "ab\ncd\n")
    h.feed("<Down><Backspace>")
    assert h.lines == ["abcd"] and h.cursor == (0, 2)
    h.feed("<Left><Delete><Delete>")
    assert h.lines == ["ad"]
    h.feed("<End><Delete>")
    assert h.lines == ["ad"]


def test_typing_is_one_undo_step(tmp_path):
    h = plain(tmp_path, "x\n")
    h.feed("<End> more words")
    h.press("C-z")
    assert h.lines == ["x"]
    assert "UNDONE" in h.message
    h.press("C-y")
    assert h.lines == ["x more words"]


def test_undo_after_moving_is_separate(tmp_path):
    h = plain(tmp_path)
    h.type("ab").feed("<Home>").type("X")
    h.press("C-z")
    assert h.lines == ["ab"]
    h.press("C-z")
    assert h.lines == [""]
    h.press("C-z")
    assert "NOUNDO" in h.message


def test_overstrike_mode(tmp_path):
    h = plain(tmp_path, "abcd\n")
    h.press("Insert")
    assert "Overstrike" in h.status
    h.type("XY")
    assert h.lines == ["XYcd"]
    h.command("SET MODE INSERT")
    h.type("_")
    assert h.lines == ["XY_cd"]


def test_vertical_motion_keeps_goal_column(tmp_path):
    h = plain(tmp_path, "abcdef\nab\nabcdef\n")
    h.feed("<End><Down>")
    assert h.cursor == (1, 2)
    h.feed("<Down>")
    assert h.cursor == (2, 6)


def test_word_motion(tmp_path):
    h = plain(tmp_path, "one two  three\n")
    h.feed("<C-Right>")
    assert h.cursor == (0, 4)
    h.feed("<C-Right>")
    assert h.cursor == (0, 9)
    h.feed("<C-Left>")
    assert h.cursor == (0, 4)


def test_home_toggles_between_indent_and_column_one(tmp_path):
    h = plain(tmp_path, "    x\n")
    h.feed("<End><Home>")
    assert h.cursor == (0, 4)
    h.feed("<Home>")
    assert h.cursor == (0, 0)


def test_page_and_top_bottom(tmp_path):
    h = plain(tmp_path, "".join(f"line {i}\n" for i in range(100)))
    h.feed("<PageDown>")
    assert h.cursor[0] > 10
    h.feed("<C-End>")
    assert h.cursor == (99, 7)
    assert "line 99" in h.window_lines()[-2] or "line 99" in "\n".join(h.window_lines())
    h.feed("<C-Home>")
    assert h.cursor == (0, 0)


def test_goto_line_prompts(tmp_path):
    h = plain(tmp_path, "a\nb\n  c\n")
    h.press("C-g")
    assert "Go to line:" in h.command_line
    h.feed("3<Enter>")
    assert h.cursor == (2, 2)
    h.command("GOTO LINE 99")
    assert "LINERANGE" in h.message and h.cursor[0] == 2


def test_find_and_find_next(tmp_path):
    h = plain(tmp_path, "alpha beta\nBeta gamma\nbeta\n")
    h.press("C-f")
    assert "Find:" in h.command_line
    h.feed("beta<Enter>")
    assert h.cursor == (0, 6)
    h.press("F3")
    assert h.cursor == (1, 0)
    h.press("F3")
    assert h.cursor == (2, 0)
    h.press("F3")
    assert h.cursor == (0, 6) and "WRAPPED" in h.message
    h.press("C-f")
    assert "Find [beta]:" in h.command_line
    h.press("Enter")
    assert h.cursor == (1, 0)
    h.command('FIND "Beta"')
    assert h.cursor == (1, 0)
    h.command("FIND nothing-like-this")
    assert "STRNOTFOUND" in h.message


def test_find_reverse(tmp_path):
    h = plain(tmp_path, "x\nx\nx\n")
    h.feed("<C-End>")
    h.command("FIND/REVERSE x")
    assert h.cursor == (2, 0)
    h.command("SET REVERSE")
    h.press("F3")
    assert h.cursor == (1, 0)
    assert "Reverse" in h.status


def test_delete_line(tmp_path):
    h = plain(tmp_path, "a\nb\nc\n")
    h.feed("<Down>")
    h.command("DELETE LINE")
    assert h.lines == ["a", "c"]


def test_tab_indents_when_there_are_no_placeholders(tmp_path):
    h = plain(tmp_path, "x\n")
    h.feed("<Tab>")
    assert h.lines == ["    x"]


def test_read_only_buffer_refuses_typing(tmp_path):
    h = plain(tmp_path, "x\n")
    h.command("GOTO BUFFER $MESSAGES")
    h.type("z")
    assert "READONLY" in h.message


def test_unknown_key_explains(tmp_path):
    h = plain(tmp_path)
    h.press("F12")
    assert "F12 is not used" in h.message


def test_ctrl_c_explains_how_to_quit(tmp_path):
    h = plain(tmp_path)
    h.press("C-c")
    assert "Ctrl-Q" in h.message
    assert not h.editor.quit_requested

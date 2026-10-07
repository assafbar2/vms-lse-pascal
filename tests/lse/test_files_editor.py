from conftest import HELLO

from lse.overlays import MenuOverlay, QuestionOverlay


def test_open_existing_file(hello):
    assert hello.lines[0] == "PROGRAM Hello(INPUT, OUTPUT);"
    assert "4 lines read from file HELLO.PAS" in hello.message
    assert hello.status.startswith("[ HELLO.PAS ]")
    assert "Pascal" in hello.status


def test_ctrl_s_writes_numbered_versions(hello):
    hello.feed("<C-End><Enter>{ more }")
    assert "HELLO.PAS *" in hello.status
    hello.press("C-s")
    assert "lines written to file HELLO.PAS;2" in hello.message
    assert hello.file("HELLO.PAS;1") == HELLO
    assert hello.status.startswith("[ HELLO.PAS;2 ]")
    hello.type("!").press("C-s")
    assert hello.status.startswith("[ HELLO.PAS;3 ]")
    assert hello.ls() == ["HELLO.PAS", "HELLO.PAS;1", "HELLO.PAS;2", "HELLO.PAS;3"]
    assert hello.file("HELLO.PAS") == hello.file("HELLO.PAS;3")
    assert hello.file("HELLO.PAS").endswith("{ more }!\n")


def test_new_file_saves_as_version_1(h):
    h.open("NEW.PAS").feed("<Tab><Enter>Demo")
    h.press("C-s")
    assert h.ls() == ["NEW.PAS", "NEW.PAS;1"]
    assert h.file("NEW.PAS;1").startswith("PROGRAM Demo(INPUT, OUTPUT);\n")


def test_open_specific_version(hello):
    hello.type("x").press("C-s")
    hello.command("GOTO FILE HELLO.PAS;1")
    assert hello.buffer.display_name.endswith(";1")
    assert hello.lines[0] == "PROGRAM Hello(INPUT, OUTPUT);"


def test_write_file_with_new_name(hello):
    hello.command("WRITE FILE COPY.PAS")
    assert hello.exists("COPY.PAS;1")
    assert hello.buffer.name == "COPY.PAS"


def test_unnamed_buffer_asks_for_a_name(h):
    h.type("hello")
    h.press("C-s")
    assert "to file:" in h.command_line
    h.type("NOTE.TXT").press("Enter")
    assert h.file("NOTE.TXT;1") == "hello\n"


def test_quit_without_changes_quits(hello):
    hello.press("C-q")
    assert hello.editor.quit_requested


def test_quit_with_changes_asks(hello):
    hello.type("x").press("C-q")
    assert isinstance(hello.overlay, QuestionOverlay)
    assert "unsaved changes" in hello.command_line
    hello.press("z")
    assert "Please answer" in hello.message and not hello.editor.quit_requested
    hello.press("Esc")
    assert hello.overlay is None and not hello.editor.quit_requested
    hello.press("C-q", "n")
    assert hello.editor.quit_requested
    assert not hello.exists("HELLO.PAS;2")


def test_quit_and_save(hello):
    hello.type("x").press("C-q", "y")
    assert hello.editor.quit_requested
    assert hello.exists("HELLO.PAS;2")


def test_exit_saves_everything(hello):
    hello.type("x")
    hello.command("EXIT")
    assert hello.editor.quit_requested and hello.exists("HELLO.PAS;2")


def test_goto_file_switches_buffers(hello):
    hello.write_file("OTHER.PAS", "x\n")
    hello.command("GOTO FILE other")
    assert hello.buffer.name == "OTHER.PAS"
    hello.command("GOTO FILE HELLO.PAS")
    assert hello.buffer.name == "HELLO.PAS" and "now editing" in hello.message


def test_buffer_list(hello):
    hello.press("C-b")
    assert isinstance(hello.overlay, MenuOverlay)
    menu = "\n".join(hello.screen.region("menu"))
    assert "HELLO.PAS" in menu and "$MESSAGES" in menu
    hello.feed("<Home><Enter>")
    assert hello.buffer.name == "$MESSAGES"
    assert "lines read from file HELLO.PAS" in hello.text


def test_two_windows_and_switch(hello):
    hello.command("TWO WINDOWS")
    scr = hello.screen
    assert "window0" in scr.regions and "window1" in scr.regions
    assert hello.editor.current_window == 1
    hello.press("C-w")
    assert hello.editor.current_window == 0
    hello.command("GOTO BUFFER $MESSAGES")
    assert hello.window_lines(1)[0].startswith("PROGRAM Hello")
    hello.command("ONE WINDOW")
    assert "window1" not in hello.screen.regions


def test_include_file(hello):
    hello.write_file("PART.PAS", "{ part }\n")
    hello.feed("<C-End><Enter>")
    hello.command("INCLUDE FILE PART.PAS")
    assert hello.lines[-1] == "{ part }"


def test_purge(hello):
    for _ in range(3):
        hello.type("x").press("C-s")
    hello.command("PURGE")
    assert hello.ls() == ["HELLO.PAS", "HELLO.PAS;4"]


def test_broken_language_file_is_reported(tmp_path):
    from lse.editor import Editor
    from lse.langdef import LanguageRegistry
    langs = tmp_path / "langs"
    langs.mkdir()
    (langs / "bad.lse").write_text("DEFINE LANGUAGE BAD\n/FILE_TYPES=(.BAD)\n")
    ed = Editor(cwd=str(tmp_path), languages=LanguageRegistry(str(langs)), raise_errors=True)
    ed.open_file("X.BAD")
    assert "%LSE-W-LANGDEF" in ed.message.text and "has no END DEFINE" in ed.message.text


def test_missing_version_is_an_error(hello):
    hello.command("GOTO FILE HELLO.PAS;7")
    assert "FILENOTFOUND" in hello.message

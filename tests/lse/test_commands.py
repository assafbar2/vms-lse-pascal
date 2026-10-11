import pytest

from lse.commands import CommandError
from lse.editor import Editor
from lse.overlays import PromptOverlay


@pytest.fixture
def ed(tmp_path):
    return Editor(cwd=str(tmp_path), raise_errors=True)


@pytest.mark.parametrize("text,name", [
    ("COMPILE", "COMPILE"), ("comp", "COMPILE"), ("GO F x", "GOTO FILE"),
    ("goto line 5", "GOTO LINE"), ("SET TH AMB", "SET THEME"), ("NEXT ERR", "NEXT ERROR"),
    ("EXI", "EXIT"), ("RU", "RUN"), ("SAVE", "WRITE FILE"), ("WRITE", "WRITE FILE"),
    ("FIND NEXT", "FIND NEXT"), ("FIND fred", "FIND"), ("HELP KEYS", "HELP"),
    ("HELP INDICATED", "HELP INDICATED"), ("OTHER WINDOW", "NEXT WINDOW"),
])
def test_abbreviations_resolve(ed, text, name):
    assert ed.commands.parse(text, ed).command.name == name


def test_ambiguous_and_unknown(ed):
    with pytest.raises(CommandError) as e:
        ed.commands.parse("EX", ed)
    assert e.value.ident == "AMBIGUOUS" and "EXIT" in e.value.text and "EXPAND" in e.value.text
    with pytest.raises(CommandError) as e:
        ed.commands.parse("FROBNICATE", ed)
    assert e.value.ident == "NOSUCHCMD"


def test_qualifiers(ed):
    p = ed.commands.parse("RUN/SEED=5 /INPUT=\"50\"", ed)
    assert p.args.quals == {"SEED": 5, "INPUT": "50"}
    p = ed.commands.parse("COMPILE /LIS", ed)
    assert p.args.quals == {"LIST": True}
    p = ed.commands.parse("COMPILE/NOLIST", ed)
    assert p.args.quals == {"LIST": False}
    p = ed.commands.parse("SET MESSAGES /NOEXPLAIN", ed)
    assert p.args.quals == {"EXPLAIN": False}
    with pytest.raises(CommandError) as e:
        ed.commands.parse("COMPILE/BOGUS", ed)
    assert e.value.ident == "IVQUAL"
    with pytest.raises(CommandError) as e:
        ed.commands.parse("RUN/SEED=abc", ed)
    assert e.value.ident == "IVNUMBER"


def test_params(ed):
    p = ed.commands.parse("GOTO FILE examples/HELLO.PAS", ed)
    assert p.args["file"] == "examples/HELLO.PAS"
    p = ed.commands.parse('FIND "two words"', ed)
    assert p.args["text"] == "two words"
    p = ed.commands.parse("FIND two words", ed)
    assert p.args["text"] == "two words"
    p = ed.commands.parse("SET THEME gr", ed)
    assert p.args["theme"] == "GREEN"
    p = ed.commands.parse("GOTO FILE", ed)
    assert [m.name for m in p.missing] == ["file"]
    with pytest.raises(CommandError):
        ed.commands.parse("GOTO LINE x", ed)
    with pytest.raises(CommandError):
        ed.commands.parse("SET THEME PURPLE", ed)
    with pytest.raises(CommandError):
        ed.commands.parse("UNDO now", ed)


def test_every_key_binding_is_a_valid_command(ed):
    for key, line in ed.keymap.bindings.items():
        cmd = ed.commands.parse(line, ed).command
        assert cmd.help, line


def test_every_command_has_help_and_group(ed):
    for cmd in ed.commands:
        assert cmd.help and cmd.group, cmd.name


def comp(ed, text):
    return ed.commands.complete(text, ed)


def test_complete_command_words(ed):
    assert comp(ed, "COMP").text == "COMPILE "
    assert comp(ed, "comp").text == "COMPILE "
    c = comp(ed, "GOTO ")
    assert {"FILE", "LINE", "TOP", "BOTTOM", "BUFFER", "PLACEHOLDER", "SOURCE"} <= set(c.candidates)
    assert comp(ed, "GOTO F").text == "GOTO FILE "
    c = comp(ed, "E")
    assert "EXIT" in c.candidates and "EXPAND" in c.candidates
    assert comp(ed, "NEXT E").text == "NEXT ERROR "
    assert len(comp(ed, "").candidates) > 20


def test_complete_params_and_qualifiers(ed, tmp_path):
    assert comp(ed, "SET THEME A").text == "SET THEME AMBER "
    assert set(comp(ed, "SET THEME ").candidates) == {"VT220", "AMBER", "GREEN"}
    (tmp_path / "GUESS.PAS").write_text("x\n")
    (tmp_path / "GUESS.PAS;1").write_text("x\n")
    (tmp_path / "HELLO.PAS").write_text("x\n")
    (tmp_path / "sub").mkdir()
    assert comp(ed, "GOTO FILE gu").text == "GOTO FILE GUESS.PAS "
    assert set(comp(ed, "GOTO FILE ").candidates) == {"GUESS.PAS", "HELLO.PAS", "sub/"}
    assert comp(ed, "GOTO FILE su").text == "GOTO FILE sub/"
    assert comp(ed, "RUN /SE").text == "RUN /SEED="
    assert "/NOLIST" in comp(ed, "COMPILE /").candidates
    assert "KEYPAD" in comp(ed, "HELP K").candidates


def test_command_line_prompt_and_tab(h):
    h.open("NEW.PAS")
    h.press("C-p")
    assert isinstance(h.overlay, PromptOverlay)
    assert h.command_line == "LSE>"
    assert h.screen.cursor == (23, 5)
    h.type("set th")
    h.press("Tab")
    assert h.command_line == "LSE> SET THEME"
    h.press("Tab")
    assert "AMBER" in h.message and "GREEN" in h.message
    h.type("g").press("Tab")
    assert h.command_line == "LSE> SET THEME GREEN"
    h.press("Enter")
    assert h.editor.theme == "GREEN" and "THEME" in h.message
    assert h.overlay is None


def test_f10_and_esc_digit_open_command_line(h):
    h.press("F10")
    assert isinstance(h.overlay, PromptOverlay)
    h.press("F10")
    assert h.overlay is None
    h.feed("<Esc>0")
    assert isinstance(h.overlay, PromptOverlay)
    h.feed("<Esc>")
    assert h.overlay is None


def test_command_history(h):
    h.command("SET THEME AMBER")
    h.command("SET THEME VT220")
    h.press("C-p", "Up")
    assert h.command_line == "LSE> SET THEME VT220"
    h.press("Up")
    assert h.command_line == "LSE> SET THEME AMBER"
    h.press("Enter")
    assert h.editor.theme == "AMBER"


def test_command_line_editing_keys(h):
    h.press("C-p")
    h.type("UNDX")
    h.press("Backspace").type("O").press("Home").type("RE").press("End")
    assert h.command_line == "LSE> REUNDO"
    h.press("C-u")
    assert h.command_line == "LSE>"


def test_missing_parameter_prompts_vms_style(h):
    h.command("GOTO FILE")
    assert "Open file:" in h.command_line
    h.type("NEW").press("Enter")
    assert h.buffer.name == "NEW.PAS"


def test_prompt_tab_completes_files(h):
    h.write_file("GUESS.PAS", "x\n")
    h.press("C-o")
    h.type("gu").press("Tab")
    assert h.command_line == "Open file: GUESS.PAS"


def test_errors_show_on_message_line(h):
    h.command("FROB")
    assert "%LSE-E-NOSUCHCMD" in h.message


def test_help_for_a_command(h):
    h.command("HELP COMPILE")
    text = h.screen.text()
    assert "COMPILE [/[NO]LIST]" in text and "F7" in text


def test_unknown_help_topic(h):
    h.command("HELP NOSUCHTOPIC")
    assert "NOHELP" in h.message


def test_help_keys_and_commands_lists(h):
    h.command("HELP KEYS")
    assert "Ctrl-S" in h.screen.text()
    h.press("Esc")
    h.command("HELP COMMANDS")
    assert "GOTO FILE" in h.screen.text()

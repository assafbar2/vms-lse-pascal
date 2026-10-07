from conftest import new_program

from lse import placeholders as ph
from lse.overlays import MenuOverlay, TextViewOverlay


def test_new_file_starts_with_template(h):
    h.open("NEW.PAS")
    assert h.lines == ["%{compilation_unit}%"]
    assert h.cursor == (0, 0)
    assert "NEWFILE" in h.message and "Tab" in h.message
    assert not h.buffer.modified


def test_tab_on_menu_placeholder_opens_menu(h):
    h.open("NEW.PAS").feed("<Tab>")
    assert isinstance(h.overlay, MenuOverlay)
    menu = h.screen.region("menu")
    assert any("PROGRAM" in line for line in menu)
    assert any("MODULE" in line for line in menu)
    h.feed("<Down><Enter>")
    assert h.lines[0] == "MODULE %{module_name}%;"


def test_escape_closes_menu_unchanged(h):
    h.open("NEW.PAS").feed("<Tab><Esc>")
    assert h.overlay is None
    assert h.lines == ["%{compilation_unit}%"]
    assert "unchanged" in h.message


def test_menu_letter_jumps(h):
    h.open("NEW.PAS").feed("<Tab>m<Enter>")
    assert h.lines[0].startswith("MODULE")


def test_program_flow_to_hello_world(h):
    new_program(h, "Hello")
    assert h.lines == ["PROGRAM Hello(INPUT, OUTPUT);", "%[declarations]%...", "BEGIN",
                       "  %{statement}%...", "END."]
    assert h.cursor == (1, 0)
    h.feed("<C-k>")
    assert h.lines[1] == "BEGIN"
    h.feed("<Tab>")
    assert h.cursor == (2, 2)
    h.feed("<Tab><Enter>")  # statement menu -> WRITELN
    assert h.lines[2:4] == ["  WRITELN(%{write_item}%...);", "  %[statement]%..."]
    h.feed("'Hello, world'<Tab><C-k>")
    assert h.lines == ["PROGRAM Hello(INPUT, OUTPUT);", "BEGIN", "  WRITELN('Hello, world')",
                       "END."]
    assert ph.count(h.lines) == 0


def test_typing_over_placeholder_replaces_it(h):
    new_program(h)
    h.feed("<C-n>")
    h.type("x := 1")
    assert h.lines[3] == "  x := 1"
    h.press("C-z")
    assert h.lines[3] == "  %{statement}%..."


def test_tab_twice_skips_a_menu_placeholder(h):
    new_program(h)
    h.feed("<Tab>")
    assert isinstance(h.overlay, MenuOverlay)
    assert "Tab skips" in h.message
    h.feed("<Tab>")
    assert h.overlay is None and h.cursor == (3, 2)
    h.feed("<Tab><S-Tab>")
    assert h.overlay is None and h.cursor == (1, 0)


def test_typed_word_then_tab_expands_and_keeps_list(h):
    new_program(h)
    h.feed("<C-k><Tab>IF<Tab>")
    assert h.lines[1:] == ["BEGIN", "  IF %{boolean_expression}% THEN", "    %{statement}%",
                           "  %[else_part]%;", "  %[statement]%...", "END."]
    assert h.cursor == (2, 5)
    h.feed("guess < secret<Tab>WRITELN<Tab>'Too low!'<Tab>")
    assert h.lines[3] == "    WRITELN('Too low!')"
    assert h.cursor == (4, 2)
    h.feed("<C-k>")
    assert h.lines[2:5] == ["  IF guess < secret THEN", "    WRITELN('Too low!');",
                            "  %[statement]%..."]


def test_else_if_chain_like_guess(h):
    new_program(h)
    h.feed("<C-k><Tab>IF<Tab>a<Tab>WRITELN<Tab>'low'<Tab>")
    h.feed("<Tab><Down><Enter>")  # else_part -> else_if_branch
    assert "  ELSE IF %{boolean_expression}% THEN" in h.lines
    h.feed("b<Tab>WRITELN<Tab>'high'<Tab><Tab><Enter>")  # nested else_part -> else_branch
    h.feed("WRITELN<Tab>'ok'<Tab>")
    text = "\n".join(h.lines)
    assert "  IF a THEN\n    WRITELN('low')\n  ELSE IF b THEN\n    WRITELN('high')\n" \
           "  ELSE\n    WRITELN('ok');\n  %[statement]%..." in text


def test_var_declaration_flow(h):
    new_program(h, "Guess")
    h.feed("<Tab><Enter>")  # declarations menu -> VAR
    assert h.lines[1:5] == ["VAR", "  %{identifier}%... : %{type}%;",
                            "  %[variable_declaration]%...", "%[declarations]%..."]
    h.feed("secret, guess, tries<Tab><Tab><Enter>")  # type menu -> INTEGER
    assert h.lines[2] == "  secret, guess, tries : INTEGER;"
    h.feed("<Tab><C-k>")
    assert ph.placeholder_at(h.lines, *h.cursor).name == "declarations"
    h.feed("<C-k>")
    assert h.lines[:4] == ["PROGRAM Guess(INPUT, OUTPUT);", "VAR",
                           "  secret, guess, tries : INTEGER;", "BEGIN"]


def test_shift_tab_goes_back(h):
    new_program(h)
    h.feed("<C-n>")
    assert h.cursor == (3, 2)
    h.feed("<S-Tab>")
    assert h.cursor == (1, 0)
    h.feed("<S-Tab>")
    assert h.cursor == (3, 2)  # wraps round


def test_ctrl_n_moves_without_expanding(h):
    new_program(h)
    h.feed("<C-n>")
    assert h.overlay is None and h.cursor == (3, 2)


def test_ctrl_delete_erases_too(h):
    new_program(h)
    h.feed("<C-Delete>")
    assert "%[declarations]%..." not in h.lines


def test_erase_off_placeholder_warns(h):
    new_program(h)
    h.feed("<C-Home><C-k>")
    assert "NOPLACEHOLDER" in h.message


def test_terminal_placeholder_tab_moves_on(h):
    h.open("NEW.PAS").feed("<Tab><Enter>")
    assert h.cursor == (0, 8)  # on %{program_name}%
    h.feed("<Tab>")
    assert h.overlay is None and h.cursor == (1, 0)


def test_expand_terminal_explains(h):
    h.open("NEW.PAS").feed("<Tab><Enter><C-e>")
    assert "TERMINAL" in h.message and "Guess" in h.message


def test_placeholder_hint_follows_cursor(h):
    new_program(h)
    assert h.message.startswith("%[declarations]%...:")
    assert h.screen.role_at(h.screen.regions["message"][0], 0) == "message_hint"
    h.feed("<C-Home>")
    assert h.message == ""
    h.feed("<Tab>")
    assert "%[declarations]%..." in h.message


def test_f1_on_placeholder_shows_description_and_example(h):
    new_program(h)
    h.feed("<C-k><Tab><Tab><Down><Down><Enter>")  # statement menu -> IF
    assert ph.placeholder_at(h.lines, *h.cursor).name == "boolean_expression"
    h.press("F1")
    assert isinstance(h.overlay, TextViewOverlay)
    screen = h.screen.text()
    assert "A test that is either TRUE or FALSE." in screen
    assert "guess < secret" in screen
    assert "Ctrl-K" in screen
    h.press("Esc")
    assert h.overlay is None


def test_f1_on_token_word(h):
    h.write_file("W.PAS", "WHILE x DO\n")
    h.open("W.PAS").feed("<Right>")
    h.press("F1")
    assert "Template word WHILE" in h.screen.text()


def test_f1_in_menu_explains_choice(h):
    h.open("NEW.PAS").feed("<Tab><F1>")
    assert "Template word PROGRAM" in h.screen.text()
    h.feed("<Esc>")
    assert isinstance(h.overlay, MenuOverlay)


def test_undo_expansion_is_one_step(h):
    new_program(h)
    h.feed("<C-z>")
    assert h.lines[0] == "PROGRAM %{program_name}%(INPUT, OUTPUT);"
    h.feed("<C-z>")
    assert h.lines == ["%{compilation_unit}%"]


def test_typing_next_to_following_placeholder_does_not_erase_it(h):
    h.write_file("P.PAS", "PROCEDURE %{procedure_name}%%[formal_parameters]%;\n")
    h.open("P.PAS")
    h.feed("<Tab>Show")
    assert h.lines[0] == "PROCEDURE Show%[formal_parameters]%;"
    h.feed("<Backspace>w")
    assert h.lines[0] == "PROCEDURE Show%[formal_parameters]%;"


def test_show_tokens_and_placeholders(h):
    h.open("NEW.PAS")
    h.command("SHOW TOKENS")
    assert "WHILE" in h.screen.text()
    h.press("Esc")
    h.command("SHOW PLACEHOLDERS")
    assert "boolean_expression" in h.screen.text()


def test_help_named_token_and_placeholder(h):
    h.open("NEW.PAS")
    h.command("HELP TOKEN REPEAT")
    assert "UNTIL guess = secret" in h.screen.text()
    h.press("Esc")
    h.command("HELP PLACEHOLDER statement")
    assert "Choices:" in h.screen.text()

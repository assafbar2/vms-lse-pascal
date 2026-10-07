"""A worked example of the headless harness: a newcomer writes most of GUESS.PAS.

This doubles as documentation for scripted walkthrough tests: every step
types keys exactly as a person would and checks what the screen says.
"""

from lse import placeholders as ph
from lse.testing import EditorHarness


def test_newcomer_builds_guess_with_templates(tmp_path):
    h = EditorHarness(tmp_path, program_input="50\n")
    h.open("GUESS.PAS")
    assert "GUESS.PAS is a new file (Tab expands the template)" in h.message

    # PROGRAM from the menu, then the program name typed over its placeholder
    h.feed("<Tab>")
    assert "PROGRAM" in "\n".join(h.screen.region("menu"))
    h.feed("<Enter>Guess<Tab>")
    assert h.message.startswith("%[declarations]%...:")

    # VAR from the declarations menu
    h.feed("<Tab><Enter>secret, guess, tries<Tab><Tab>i<Enter>")
    assert h.lines[2] == "  secret, guess, tries : INTEGER;"
    h.feed("<Tab><C-k><C-k>")  # no more variables, no more declarations

    # A wrong turn: an unused key just explains itself
    h.press("F12")
    assert "not used" in h.message

    # Statements: type one over the placeholder and press Tab; LSE adds the
    # semicolon and a fresh %[statement]%... for the next one
    h.feed("<Tab>")
    assert ph.placeholder_at(h.lines, *h.cursor).name == "statement"
    h.feed("RANDOMIZE<Tab>")
    assert h.lines[4:6] == ["  RANDOMIZE;", "  %[statement]%..."]
    assert h.cursor == (5, 2)
    h.feed("secret := RANDOM(100) + 1<Tab>")
    # A template word typed over the placeholder expands and keeps the list too
    h.feed("WRITELN<Tab>'I am thinking of a number from 1 to 100.'<Tab>")
    h.feed("REPEAT<Tab>WRITE<Tab>'Your guess? '<Tab>READLN<Tab>guess<Tab>")
    assert ph.placeholder_at(h.lines, *h.cursor).name == "statement"
    h.feed("<C-k><Tab>guess = secret<Tab>")
    assert "  REPEAT" in h.lines and "  UNTIL guess = secret;" in h.lines
    h.feed("<C-k>")  # the last statement placeholder, and its semicolon, go away

    assert h.lines == [
        "PROGRAM Guess(INPUT, OUTPUT);",
        "VAR",
        "  secret, guess, tries : INTEGER;",
        "BEGIN",
        "  RANDOMIZE;",
        "  secret := RANDOM(100) + 1;",
        "  WRITELN('I am thinking of a number from 1 to 100.');",
        "  REPEAT",
        "    WRITE('Your guess? ');",
        "    READLN(guess)",
        "  UNTIL guess = secret",
        "END.",
    ]
    assert ph.count(h.lines) == 0

    # Save, then compile, link and run with F5; the fake toolchain echoes WRITEs
    h.press("C-s")
    assert "written to file GUESS.PAS;1" in h.message
    h.press("F5")
    assert "%LSE-S-RAN, GUESS.EXE finished" in h.message
    assert h.editor.buffers["$OUTPUT"].lines == [
        "I am thinking of a number from 1 to 100.", "Your guess? 50"]
    assert h.host.transcripts[-1].startswith("Running GUESS.EXE.")
    assert h.ls() == ["GUESS.DIA", "GUESS.EXE", "GUESS.MAP", "GUESS.OBJ", "GUESS.PAS",
                      "GUESS.PAS;1"]


def test_newcomer_leaves_a_placeholder_and_f8_finds_it(tmp_path):
    h = EditorHarness(tmp_path)
    h.open("OOPS.PAS")
    h.feed("<Tab><Enter>Oops<Tab><C-k><Tab><Tab><Enter>")  # WRITELN(%{write_item}%...)
    h.press("F7")  # compile without filling it in
    assert "OOPS.PAS has 2 errors" in h.message
    h.feed("<C-Home><F8>")
    assert h.cursor == (2, 10)
    assert "unexpanded placeholder %{write_item}%..." in h.message
    h.feed("'fixed'<Tab><C-k><F7>")
    assert "compiled with no errors" in h.message

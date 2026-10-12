"""WRITELN 'hi' without brackets: one clear message, with the fixed line as the hint."""

import pytest

from pascal import api

STUCK_ON_LESSON_2 = """PROGRAM Guess(INPUT, OUTPUT);
BEGIN
  WRITELN 'hi'
END.
"""


def problems(src):
    return api.parse_source(src).diagnostics


def test_the_program_a_newcomer_got_stuck_on():
    diags = problems(STUCK_ON_LESSON_2)
    assert [d.ident for d in diags] == ["NOPARENS"]
    d = diags[0]
    assert d.format() == (
        "%PASCAL-E-NOPARENS, WRITELN needs brackets around what it prints at line 3, column 11\n"
        "  Explanation: WRITE, WRITELN, READ and READLN take what they print, or the variables "
        "they read into, in round brackets right after their name, like WRITELN('Hello') or "
        "READLN(guess). Without the brackets the compiler cannot tell that the rest belongs "
        "to them.\n"
        "  Hint: Write WRITELN('hi') instead.")


def test_compile_reports_it_and_writes_no_object(tmp_path):
    src = tmp_path / "GUESS.PAS"
    src.write_text(STUCK_ON_LESSON_2)
    result = api.compile_file(src)
    assert not result.ok and result.obj_path is None
    assert [d.ident for d in result.diagnostics] == ["NOPARENS"]
    assert "NOPARENS" in (tmp_path / "GUESS.DIA").read_text()


@pytest.mark.parametrize("statement,line,col,text,hint", [
    ("WRITE 'Your guess? '", 4, 9, "WRITE needs brackets around what it prints",
     "Write WRITE('Your guess? ') instead."),
    ("READLN guess", 4, 10, "READLN needs brackets around the variables it reads into",
     "Write READLN(guess) instead."),
    ("READ guess", 4, 8, "READ needs brackets around the variables it reads into",
     "Write READ(guess) instead."),
    ("WRITELN 'Correct! ', guess:1, ' tries.'", 4, 11,
     "WRITELN needs brackets around what it prints",
     "Write WRITELN('Correct! ', guess:1, ' tries.') instead."),
    ("writeln guess", 4, 11, "WRITELN needs brackets around what it prints",
     "Write writeln(guess) instead."),
])
def test_write_writeln_read_readln(statement, line, col, text, hint):
    src = f"PROGRAM Guess(INPUT, OUTPUT);\nVAR guess : INTEGER;\nBEGIN\n  {statement}\nEND.\n"
    diags = problems(src)
    assert [d.ident for d in diags] == ["NOPARENS"], [d.headline() for d in diags]
    d = diags[0]
    assert (d.line, d.column, d.text, d.hint) == (line, col, text, hint)


def test_each_slip_is_reported_once_and_the_rest_still_checks():
    src = ("PROGRAM Guess(INPUT, OUTPUT);\nVAR guess : INTEGER;\nBEGIN\n"
           "  WRITE 'Your guess? ';\n  READLN guess;\n  WRITELN 'You said ', guss\nEND.\n")
    assert [(d.ident, d.line) for d in problems(src)] == [
        ("NOPARENS", 4), ("NOPARENS", 5), ("NOPARENS", 6), ("UNDECLID", 6)]


def test_a_stray_closing_bracket_is_taken_too():
    diags = problems("PROGRAM G(OUTPUT);\nBEGIN\n  WRITELN 'a', 'b')\nEND.\n")
    assert [d.ident for d in diags] == ["NOPARENS"]
    assert diags[0].hint == "Write WRITELN('a', 'b') instead."


def test_the_brackets_themselves_still_work():
    assert problems("PROGRAM G(OUTPUT);\nBEGIN\n  WRITELN('hi');\n  WRITELN ('hi');\n"
                    "  WRITELN\nEND.\n") == []


def test_a_missing_semicolon_after_writeln_is_still_a_missing_semicolon():
    src = "PROGRAM G(INPUT, OUTPUT);\nVAR x : INTEGER;\nBEGIN\n  WRITELN\n  x := 1\nEND.\n"
    assert [d.ident for d in problems(src)] == ["SEMIEXP"]
    src = "PROGRAM G(INPUT, OUTPUT);\nVAR x : INTEGER;\nBEGIN\n  WRITELN x := 1\nEND.\n"
    assert "NOPARENS" not in [d.ident for d in problems(src)]


def test_the_message_is_in_the_catalog_with_help():
    m = api.get_message("PASCAL", "NOPARENS")
    assert m.severity == "E" and m.explanation and m.hint
    assert "WRITELN('Hello')" in m.hint

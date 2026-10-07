"""The lesson file format (lse/lesson.py)."""

import pytest

from lse.lesson import LessonError, parse

GOOD = '''! a comment
LESSON DEMO
  TITLE "A demo"
  FILE DEMO.PAS
END LESSON

STEP variables
  TITLE "Variables: boxes that hold values"
  TEXT
    A variable is a named box.
    INTEGER means whole numbers.

    A second paragraph.
  END TEXT
  CHECK NO_ERRORS
  DO "Type VAR and press Tab."
    NEXT "VAR, then Tab"
    CHECK CONTAINS_WORD VAR
  DO "Declare secret."
    CHECK DECLARES secret INTEGER
    CHECK RUN_OUTPUT_CONTAINS "Too low" /INPUT="0\\n1" /SEED=7 /FAIL="say ""Too low"""
  SEE "VAR and secret : INTEGER;"
  SEE "above BEGIN."
  HINT "first"
  HINT "second"
  SOLUTION
    PROGRAM Demo;
    VAR
      secret : INTEGER;
    BEGIN
    END.
  END SOLUTION
END STEP

STEP done
  TITLE "Done"
  DO "Try something else."
END STEP
'''


def test_parse_a_lesson():
    lesson = parse(GOOD, "demo.lesson")
    assert (lesson.name, lesson.title, lesson.file) == ("DEMO", "A demo", "DEMO.PAS")
    step = lesson.steps[0]
    assert step.title == "Variables: boxes that hold values"
    assert step.text == ["A variable is a named box. INTEGER means whole numbers.",
                         "A second paragraph."]
    assert [c.kind for c in step.checks] == ["NO_ERRORS"]
    assert step.items[0].next_text == "VAR, then Tab"
    assert step.items[1].next_text == "Declare secret."
    run = step.items[1].checks[1]
    assert run.args == ["Too low"]
    assert run.quals == {"INPUT": "0\n1", "SEED": "7", "FAIL": 'say "Too low"'}
    assert step.see == "VAR and secret : INTEGER; above BEGIN."
    assert step.hints == ["first", "second"]
    assert step.solution == ["PROGRAM Demo;", "VAR", "  secret : INTEGER;", "BEGIN", "END."]
    assert not step.final and lesson.steps[1].final
    assert lesson.index_of("DONE") == 1


def test_check_kinds_know_what_they_are():
    lesson = parse(GOOD)
    word, declares = lesson.steps[0].items[0].checks[0], lesson.steps[0].items[1].checks[0]
    assert word.durable and declares.durable and not word.latched
    assert str(declares) == "DECLARES secret INTEGER"


@pytest.mark.parametrize("change,at,message", [
    (("CHECK CONTAINS_WORD VAR", "CHECK SPELLING VAR"), "SPELLING", "unknown check type SPELLING"),
    (("CHECK CONTAINS_WORD VAR", "CHECK CONTAINS_WORD"), "CONTAINS_WORD", "takes 1 argument"),
    (("/SEED=7", "/SEED=x"), "/SEED=x", "/SEED needs a number"),
    (("/SEED=7", "/COLOUR=red"), "/COLOUR", "has no /COLOUR qualifier"),
    (('  SEE "above BEGIN."\n', '  FROB "x"\n'), "FROB", "unknown line in STEP variables: FROB"),
    (("END STEP\n\nSTEP done", "\nSTEP done"), "STEP done",
     "STEP done starts before the END STEP of variables"),
    (('    NEXT "VAR, then Tab"', '    NEXT "VAR, then Tab'), "NEXT", "not closed"),
    (("  FILE DEMO.PAS\n", ""), "LESSON DEMO", "needs a FILE line"),
    (("END TEXT", "END TXT"), "  TEXT", "TEXT block has no END TEXT"),
])
def test_errors_name_the_line(change, at, message):
    old, new = change
    text = GOOD.replace(old, new, 1)
    line = next(i for i, l in enumerate(text.split("\n"), 1) if at in l)
    with pytest.raises(LessonError) as err:
        parse(text, "x.lesson")
    assert err.value.line == line, err.value
    assert message in err.value.text
    assert str(err.value).startswith(f"x.lesson:{line}: ")


def test_steps_need_title_do_and_see():
    with pytest.raises(LessonError, match="no SEE line"):
        parse(GOOD.replace('  SEE "VAR and secret : INTEGER;"\n  SEE "above BEGIN."\n', ""))
    with pytest.raises(LessonError, match="no TITLE"):
        parse(GOOD.replace('  TITLE "Done"\n', ""))
    with pytest.raises(LessonError, match="two steps called"):
        parse(GOOD.replace("STEP done", "STEP variables"))
    with pytest.raises(LessonError, match="starts with LESSON"):
        parse("STEP x\n")
    with pytest.raises(LessonError, match="empty"):
        parse("! nothing\n")

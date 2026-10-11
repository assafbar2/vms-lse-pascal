import pytest

from lse.langdef import LangDefError, parse

SAMPLE = '''
! a comment
DEFINE LANGUAGE MINI
  /FILE_TYPES=(.MIN, .MINI)
  /INITIAL_STRING="%{unit}%"
  /TAB_INCREMENT=4
END DEFINE

DEFINE TOKEN WHILE /LANGUAGE=MINI
  /DESCRIPTION="Loop while true."
  /DESCRIPTION="Second line."
  /EXAMPLE="WHILE x DO y"
  "WHILE %{cond}% DO"
  "  %{stmt}%"
END DEFINE

DEFINE PLACEHOLDER unit /TYPE=MENU /DESCRIPTION="A unit." /EXAMPLE="WHILE"
  "WHILE"   /TOKEN
  "stmt"    /PLACEHOLDER
  "NOTHING" /DESCRIPTION="literal ""quoted"" text"
END DEFINE

DEFINE PLACEHOLDER stmt /LANGUAGE=MINI /SEPARATOR=";" /DUPLICATION=VERTICAL
  /DESCRIPTION="A statement." /EXAMPLE="x"
  "%{cond}%"
END DEFINE

DEFINE PLACEHOLDER cond /LANGUAGE=MINI
  /DESCRIPTION="A condition."
  /EXAMPLE="x > 1"
END DEFINE
'''


def test_parse_sample():
    langs = parse(SAMPLE, "mini.lse")
    lang = langs["MINI"]
    assert lang.file_types == [".MIN", ".MINI"]
    assert lang.initial_string == ["%{unit}%"]
    assert lang.tab_increment == 4
    tok = lang.token("while")
    assert tok.body == ["WHILE %{cond}% DO", "  %{stmt}%"]
    assert tok.description == ["Loop while true.", "Second line."]
    assert tok.summary == "Loop while true."
    unit = lang.placeholder("UNIT")
    assert unit.type == "MENU"
    assert [(o.text, o.kind) for o in unit.options] == [
        ("WHILE", "TOKEN"), ("stmt", "PLACEHOLDER"), ("NOTHING", "TEXT")]
    assert unit.options[2].description == 'literal "quoted" text'
    stmt = lang.placeholder("stmt")
    assert stmt.type == "NONTERMINAL" and stmt.separator == ";" and stmt.duplication == "VERTICAL"
    assert lang.placeholder("cond").type == "TERMINAL"
    assert lang.validate() == []


def test_validate_reports_problems():
    text = SAMPLE.replace('"  %{stmt}%"', '"  %{missing}%"').replace(
        '/DESCRIPTION="A condition."', "")
    problems = parse(text)["MINI"].validate()
    assert any("undefined placeholder %{missing}%" in p for p in problems)
    assert any("PLACEHOLDER cond: missing /DESCRIPTION" in p for p in problems)


@pytest.mark.parametrize("text,needle", [
    ('DEFINE TOKEN X\n"a"\nEND DEFINE', "no DEFINE LANGUAGE"),
    ('DEFINE LANGUAGE L\nEND DEFINE\nDEFINE TOKEN X\n"a"', "has no END DEFINE"),
    ('DEFINE LANGUAGE L\nEND DEFINE\nDEFINE TOKEN X\nbare words\nEND DEFINE', "must be quoted"),
    ('DEFINE LANGUAGE L /BOGUS=1\nEND DEFINE', "unknown qualifier /BOGUS"),
    ('DEFINE LANGUAGE L\nEND DEFINE\nDEFINE PLACEHOLDER p /TYPE=WEIRD\nEND DEFINE', "/TYPE must be"),
    ('DEFINE LANGUAGE L\nEND DEFINE\nDEFINE TOKEN X\n"unterminated\nEND DEFINE', "unterminated"),
])
def test_errors_have_line_numbers(text, needle):
    with pytest.raises(LangDefError) as exc:
        parse(text, "bad.lse")
    assert needle in str(exc.value)
    assert "bad.lse, line" in str(exc.value)

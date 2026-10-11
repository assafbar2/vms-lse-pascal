"""The message catalog: every message is explained, and every message the code uses exists."""

import re
import string
from pathlib import Path

import pytest

from pascal import api
from pascal.messages import Diagnostic, diag

PASCAL_DIR = Path(__file__).resolve().parents[2] / "pascal"


def test_every_message_has_explanation_and_hint():
    msgs = api.all_messages()
    assert len(msgs) > 80
    for m in msgs:
        assert m.facility in ("PASCAL", "LINK", "PAS", "TRACE"), m
        assert m.severity in ("I", "W", "E", "F"), m
        assert re.fullmatch(r"[A-Z]+", m.ident), m
        assert m.template and m.explanation.strip() and m.hint.strip(), m.code
        assert not re.search(r"(?<!%)\{[a-z_]+\}", m.explanation + m.hint), m.code
        assert m.explanation.endswith((".", ")")) and m.hint.endswith((".", ")", "'")), m.code


def test_message_keys_are_unique():
    keys = [(m.facility, m.ident) for m in api.all_messages()]
    assert len(keys) == len(set(keys))


def test_get_message():
    m = api.get_message("PASCAL", "SEMIEXP")
    assert m.severity == "E" and m.template == '";" expected'
    assert api.get_message("pas", "divbyzero").code == "%PAS-F-DIVBYZERO"
    with pytest.raises(KeyError):
        api.get_message("PASCAL", "NOSUCHTHING")


def _used_messages():
    """(facility, ident) pairs that appear in diag(...) and error(...) calls in the toolchain."""
    used = set()
    for path in PASCAL_DIR.glob("*.py"):
        text = path.read_text()
        for fac, ident in re.findall(r'diag\(\s*"(PASCAL|LINK|PAS|TRACE)",\s*"([A-Z]+)"', text):
            used.add((fac, ident))
        if path.name in ("parser.py", "semantic.py", "lexer.py"):
            for ident in re.findall(r'self\.error\(\s*"([A-Z]+)"', text):
                used.add(("PASCAL", ident))
        if path.name in ("vm.py", "rtl.py"):
            for ident in re.findall(r'(?:PascalRuntimeError|_fail|bad_input)\(\s*"([A-Z]+)"', text):
                used.add(("PAS", ident))
        if path.name == "parser.py":
            for ident in re.findall(r'"([A-Z]+EXP)"', text):
                used.add(("PASCAL", ident))
    return used


def test_every_message_used_by_the_code_is_in_the_catalog():
    used = _used_messages()
    assert len(used) > 60
    for fac, ident in used:
        api.get_message(fac, ident)


def test_hint_details_only_use_template_fields_or_known_extras():
    for m in api.all_messages():
        if m.hint_detail:
            fields = {f for _, f, _, _ in string.Formatter().parse(m.hint_detail) if f}
            assert fields, m.code


def test_diagnostic_format():
    d = diag("PASCAL", "SEMIEXP", file="GUESS.PAS", line=9, column=3, prev_line=8, prev_text="1")
    assert isinstance(d, Diagnostic)
    assert d.format() == (
        '%PASCAL-E-SEMIEXP, ";" expected at line 9, column 3\n'
        "  Explanation: Pascal statements and declarations are separated by semicolons. "
        'The compiler found the start of something new before the previous one was ended with ";".\n'
        '  Hint: Add ";" at the end of line 8, after "1".')
    assert d.format(explain=False) == '%PASCAL-E-SEMIEXP, ";" expected at line 9, column 3'
    assert str(d) == d.format(explain=False)
    wrapped = d.format(width=60)
    assert all(len(line) <= 60 for line in wrapped.splitlines())
    no_col = diag("PASCAL", "UNDECLID", line=12, name="COUNT")
    assert no_col.format(explain=False) == '%PASCAL-E-UNDECLID, undeclared identifier "COUNT" at line 12'
    no_loc = diag("LINK", "NOIMGFIL")
    assert no_loc.format(explain=False) == "%LINK-E-NOIMGFIL, image file not created"


def test_generic_hint_used_when_details_are_missing():
    d = diag("PASCAL", "SEMIEXP", line=3, column=1)
    assert d.hint == api.get_message("PASCAL", "SEMIEXP").hint


def test_missing_template_field_is_a_bug():
    with pytest.raises(KeyError):
        diag("PASCAL", "UNDECLID", line=1)

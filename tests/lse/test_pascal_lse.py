import pytest

from lse import placeholders as ph
from lse.langdef import LanguageRegistry
from lse.testing import EditorHarness

REQUIRED_TOKENS = ["PROGRAM", "MODULE", "CONST", "TYPE", "VAR", "PROCEDURE", "FUNCTION", "BEGIN",
                   "IF", "CASE", "WHILE", "REPEAT", "FOR", "WRITELN", "READLN", "RECORD", "ARRAY"]


@pytest.fixture(scope="module")
def pascal():
    reg = LanguageRegistry()
    lang = reg.get("PASCAL")
    assert reg.errors == []
    assert lang is not None
    return lang


def test_definition_is_sound(pascal):
    assert pascal.validate() == []


def test_required_tokens_exist(pascal):
    for name in REQUIRED_TOKENS:
        assert pascal.token(name) is not None, name


def test_every_entry_has_description_and_example(pascal):
    for tok in pascal.tokens.values():
        assert tok.description and tok.example, tok.name
    for p in pascal.placeholders.values():
        assert p.description and p.example, p.name


def test_one_line_hints_are_short(pascal):
    entries = list(pascal.tokens.values()) + list(pascal.placeholders.values())
    for e in entries:
        assert len(e.summary) <= 60, f"{e.name}: {len(e.summary)} chars: {e.summary}"


def test_file_types_and_initial_string(pascal):
    assert ".PAS" in pascal.file_types
    assert pascal.initial_string == ["%{compilation_unit}%"]


def test_every_placeholder_is_reachable_from_the_initial_string(pascal):
    seen, todo = set(), ["compilation_unit"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        p = pascal.placeholder(name)
        lines = list(p.body)
        for opt in p.options:
            if opt.kind == "TOKEN":
                lines += pascal.token(opt.text).body
            elif opt.kind == "PLACEHOLDER":
                todo.append(opt.text.lower())
        for m in ph.scan(lines):
            todo.append(m.name.lower())
    assert set(pascal.placeholders) - seen == set()


@pytest.mark.parametrize("token", REQUIRED_TOKENS + ["WRITE", "READ"])
def test_each_token_expands_where_typed(tmp_path, token):
    h = EditorHarness(tmp_path, files={"T.PAS": "  \n"})
    h.open("T.PAS")
    h.feed(f"<End>{token}<Tab>")
    body = h.editor.languages.get("PASCAL").token(token).body
    assert h.lines[0] == "  " + body[0]
    for got, want in zip(h.lines[1:], body[1:]):
        assert got == (("  " + want) if want.strip() else "")
    if ph.scan(body):
        assert ph.placeholder_at(h.lines, *h.cursor) is not None

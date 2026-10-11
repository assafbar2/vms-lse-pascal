"""The editor parses the buffer after every edit, so no half-typed program may crash the compiler."""

from pathlib import Path

import pytest

from pascal import vm
from pascal.compiler import compile_source
from pascal.lexer import tokenize
from pascal.pcode import OPCODES

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted((ROOT / "examples").glob("*.PAS")) + [Path(__file__).parent / "data" / "FEATURES.PAS"]


def variants(text: str):
    tokens, _ = tokenize(text)
    lines = text.split("\n")

    def offset(tok):
        return sum(len(ln) + 1 for ln in lines[:tok.line - 1]) + tok.column - 1

    for tok in tokens[:-1]:
        start = offset(tok)
        end = start + len(tok.text)
        yield text[:start] + text[end:]
        yield text[:start] + "%{x}%" + text[end:]
        yield text[:start] + "%[y]%..." + text[end:]
    for n in range(0, len(text), max(1, len(text) // 40)):
        yield text[:n]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_edit_crashes_the_compiler(path):
    text = path.read_text()
    count = 0
    for src in variants(text):
        out = compile_source(src, "FUZZ.PAS", created="-")
        for d in out.diagnostics:
            assert d.explanation and d.hint
            assert d.line is None or d.line >= 1
        count += 1
    assert count > 50


def test_vm_opcode_numbers_match_the_instruction_table():
    for i, name in enumerate(OPCODES):
        assert getattr(vm, f"OP_{name}") == i, name

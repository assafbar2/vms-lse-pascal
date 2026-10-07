from pathlib import Path

import pytest

from pascal import api
from pascal.compiler import compile_source
from pascal.objfile import ObjFormatError, read_image, read_library, read_object, write_image, write_object
from pascal.pcode import SymRef, format_instr, parse_operands
from pascal.rtl import LIBRARY_PATH, ROUTINES, build_library_text

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def obj_of(src, name="T.PAS"):
    out = compile_source(src, name, created="7-OCT-2026 00:00:00")
    assert out.obj is not None, [d.format() for d in out.diagnostics]
    return out.obj


def test_object_text_round_trips():
    obj = obj_of((EXAMPLES / "PRIMES.PAS").read_text())
    text = write_object(obj)
    again = read_object(text)
    assert write_object(again) == text
    assert again.name == "PRIMES" and again.kind == "PROGRAM" and again.transfer is not None


def test_object_contents_are_symbolic_and_readable():
    obj = obj_of((EXAMPLES / "GUESS.PAS").read_text(), "GUESS.PAS")
    text = write_object(obj)
    assert ".MODULE    GUESS" in text and ".KIND      PROGRAM" in text
    assert "CALL   PAS$RANDOM 1" in text
    ext = {e.name: e for e in obj.externals}
    assert set(ext) >= {"PAS$RANDOMIZE", "PAS$RANDOM", "PAS$WRITE_STR", "PAS$READ_INT", "PAS$READLN"}
    assert ext["PAS$RANDOM"].signature == "FUNCTION(INTEGER):INTEGER"
    for e in obj.externals:
        for site in e.sites:
            assert SymRef(e.name) in obj.code[site].args
    assert [v.name for v in obj.variables] == ["SECRET", "GUESS", "TRIES"]
    assert obj.lines[0] == (0, 4)


def test_module_globals_and_externals():
    obj = obj_of((EXAMPLES / "MATHLIB.PAS").read_text(), "MATHLIB.PAS")
    assert obj.kind == "MODULE" and obj.transfer is None
    g = {s.name: s for s in obj.globals}
    assert g["SQUARE"].kind == "ROUTINE" and g["SQUARE"].signature == "FUNCTION(INTEGER):INTEGER"
    assert g["CALLCOUNT"].kind == "DATA" and g["CALLCOUNT"].value == 0
    assert g["GCD"].signature == "FUNCTION(INTEGER,INTEGER):INTEGER"
    demo = obj_of((EXAMPLES / "MATHDEMO.PAS").read_text(), "MATHDEMO.PAS")
    ext = {e.name: e for e in demo.externals}
    assert ext["CALLCOUNT"].kind == "DATA" and ext["SQUARE"].kind == "ROUTINE"
    assert ext["PRINTBAR"].signature == "PROCEDURE(INTEGER)"


@pytest.mark.parametrize("op, text", [
    ("LIT", "42"), ("LIT", "-2.5"), ("LITS", "'it''s; ok'"), ("CALL", "PAS$WRITELN 0"),
    ("CALL", "001A 2"), ("LDG", "COUNTER"), ("INDEX", "1 10 3"), ("NATIVE", "PAS$SQRT 1"),
])
def test_operands_round_trip(op, text):
    from pascal.pcode import Instr
    ins = Instr(op, parse_operands(op, text))
    assert format_instr(ins).split(None, 1)[1] == text


def test_bad_objects_are_rejected():
    with pytest.raises(ObjFormatError):
        read_object("hello\n")
    good = write_object(obj_of("PROGRAM P; BEGIN END."))
    with pytest.raises(ObjFormatError):
        read_object(good.replace(".END", ""))
    with pytest.raises(ObjFormatError, match="unknown instruction"):
        read_object(good.replace("STOP", "FROB"))


def test_shipped_library_matches_the_generator():
    assert LIBRARY_PATH.read_text() == build_library_text(), "run: python -m pascal.rtl"
    lib = read_library(LIBRARY_PATH.read_text())
    assert set(lib.index) == set(ROUTINES)
    assert lib.index["PAS$RANDOM"] == "PAS$RANDOM"
    for name, (module, sig, _cells, _ret) in ROUTINES.items():
        sym = {s.name: s for s in lib.modules[module].globals}[name]
        assert sym.signature == sig


def test_image_round_trips(pas):
    exe = pas.build("HELLO", (EXAMPLES / "HELLO.PAS").read_text())
    text = Path(exe).read_text()
    img = read_image(text)
    assert write_image(img) == text
    assert img.name == "HELLO" and img.modules[0].name == "HELLO"
    assert img.line_at(img.transfer + 1) == 8


def test_versioned_and_lower_case_file_names(pas):
    (pas.dir / "hello.pas").write_text("PROGRAM H(OUTPUT); BEGIN WRITELN('lower') END.")
    r = api.compile_file(pas.dir / "hello")
    assert r.ok and r.obj_path.endswith("hello.obj")
    lr = api.link([str(pas.dir / "hello")])
    assert lr.ok and lr.exe_path.endswith("hello.exe")
    assert api.run_image(pas.dir / "hello").output == "lower\n"
    (pas.dir / "V.PAS;1").write_text("PROGRAM V(OUTPUT); BEGIN WRITELN('one') END.")
    (pas.dir / "V.PAS;2").write_text("PROGRAM V(OUTPUT); BEGIN WRITELN('two') END.")
    r = api.compile_file(pas.dir / "V")
    assert r.ok and r.obj_path.endswith("V.OBJ")
    api.link([str(pas.dir / "V")])
    assert api.run_image(pas.dir / "V").output == "two\n"

from pathlib import Path

from pascal import api

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def compile_all(pas, *names):
    pas.copy_example(*names)
    for n in names:
        r = api.compile_file(pas.dir / n)
        assert r.ok, [d.format() for d in r.diagnostics]


def test_two_module_link_and_run(pas):
    compile_all(pas, "MATHLIB", "MATHDEMO")
    r = api.link([str(pas.dir / "MATHDEMO"), str(pas.dir / "MATHLIB")])
    assert r.ok and r.diagnostics == []
    assert r.exe_path.endswith("MATHDEMO.EXE") and r.map_path.endswith("MATHDEMO.MAP")
    out = api.run_image(r.exe_path).output
    assert "4 squared is 16  ****************" in out
    assert "GCD(84, 36) = 12" in out
    assert "MATHLIB routines were called 16 times." in out


def test_comma_separated_link_list(pas):
    compile_all(pas, "MATHLIB", "MATHDEMO")
    r = api.link(f"{pas.dir / 'MATHDEMO'}, {pas.dir / 'MATHLIB'}")
    assert r.ok


def test_undefined_symbols_name_the_source_line(pas):
    compile_all(pas, "MATHDEMO")
    (pas.dir / "MATHDEMO.EXE").write_text("stale")
    r = api.link([str(pas.dir / "MATHDEMO")])
    assert not r.ok and r.exe_path is None
    undef = [d for d in r.diagnostics if d.ident == "UNDFSYMS"]
    assert {d.text.split()[2] for d in undef} == {"CALLCOUNT", "SQUARE", "GCD", "PRINTBAR"}
    assert all(d.severity == "W" for d in undef)
    sq = next(d for d in undef if "SQUARE" in d.text)
    assert sq.file.endswith("MATHDEMO.PAS") and sq.line == 17
    assert sq.format(explain=False) == (
        "%LINK-W-UNDFSYMS, undefined symbol SQUARE referenced in module MATHDEMO at line 17")
    assert r.diagnostics[-1].code == "%LINK-E-NOIMGFIL"
    assert not (pas.dir / "MATHDEMO.EXE").exists()


def test_map_shows_where_symbols_come_from(pas):
    pas.copy_example("GUESS")
    api.compile_file(pas.dir / "GUESS")
    r = api.link([str(pas.dir / "GUESS")])
    text = Path(r.map_path).read_text()
    assert "Object Module Synopsis" in text and "Symbol Cross Reference" in text
    xref = text.split("Symbol Cross Reference")[1].split("Symbols By Value")[0]
    line = next(ln for ln in xref.splitlines() if ln.startswith("PAS$RANDOM "))
    assert "PAS$RANDOM (PASRTL.OLB)" in line and line.rstrip().endswith("GUESS")
    assert "From PASRTL.OLB:" in text and "Transfer address:" in text
    assert "SECRET" in text


def test_only_needed_library_modules_are_linked(pas):
    pas.copy_example("HELLO")
    api.compile_file(pas.dir / "HELLO")
    r = api.link([str(pas.dir / "HELLO")])
    text = Path(r.map_path).read_text()
    assert "PAS$IO" in text and "PAS$RANDOM " not in text and "PAS$MATH" not in text


def test_no_map_and_custom_output(pas):
    pas.copy_example("HELLO")
    api.compile_file(pas.dir / "HELLO")
    r = api.link([str(pas.dir / "HELLO")], output=str(pas.dir / "GREET"), map_file=False)
    assert r.ok and r.exe_path.endswith("GREET.EXE") and r.map_path is None
    assert api.run_image(r.exe_path).output == "Hello, world!\n"


def test_link_errors(pas):
    r = api.link([str(pas.dir / "MISSING")])
    assert [d.code for d in r.diagnostics] == ["%LINK-F-OPENIN"]
    assert api.link([]).diagnostics[0].ident == "NOFILES"
    (pas.dir / "JUNK.OBJ").write_text("garbage")
    assert api.link([str(pas.dir / "JUNK")]).diagnostics[0].ident == "BADOBJ"

    compile_all(pas, "MATHLIB")
    r = api.link([str(pas.dir / "MATHLIB")])
    assert "NOMAIN" in [d.ident for d in r.diagnostics] and not r.ok

    pas.compile("A", "PROGRAM A; BEGIN END.")
    pas.compile("B", "PROGRAM B; BEGIN END.")
    r = api.link([str(pas.dir / "A"), str(pas.dir / "B")])
    assert "MULTFR" in [d.ident for d in r.diagnostics]


def test_multiple_definitions_warn_but_link(pas):
    lib = "MODULE {n};\n[GLOBAL] PROCEDURE Hello; BEGIN WRITELN('{n}') END;\nEND.\n"
    pas.compile("M1", lib.format(n="M1"))
    pas.compile("M2", lib.format(n="M2"))
    pas.compile("MAIN", "PROGRAM Main(OUTPUT);\nPROCEDURE Hello; EXTERNAL;\nBEGIN Hello END.\n")
    r = api.link([str(pas.dir / n) for n in ("MAIN", "M1", "M2")])
    assert r.ok and [d.ident for d in r.diagnostics] == ["MULDEF"]
    assert api.run_image(r.exe_path).output == "M1\n"


def test_kind_and_signature_mismatches(pas):
    pas.compile("LIB", "MODULE Lib;\nVAR [GLOBAL] Total : INTEGER;\n"
                       "[GLOBAL] FUNCTION Twice(x : INTEGER) : INTEGER; BEGIN Twice := 2 * x END;\nEND.\n")
    pas.compile("K", "PROGRAM K;\nPROCEDURE Total; EXTERNAL;\nBEGIN Total END.\n")
    r = api.link([str(pas.dir / "K"), str(pas.dir / "LIB")])
    assert "SYMKIND" in [d.ident for d in r.diagnostics] and not r.ok
    pas.compile("S", "PROGRAM S;\nVAR i : INTEGER;\nFUNCTION Twice(x : REAL) : INTEGER; EXTERNAL;\n"
                     "BEGIN i := Twice(2.0) END.\n")
    r = api.link([str(pas.dir / "S"), str(pas.dir / "LIB")])
    sig = [d for d in r.diagnostics if d.ident == "SIGNATURE"]
    assert sig and "FUNCTION(INTEGER):INTEGER" in sig[0].hint and not r.ok

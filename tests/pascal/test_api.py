"""The pascal.api contract used by the editor."""

import dataclasses
from pathlib import Path

from pascal import api

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def field_names(cls):
    return [f.name for f in dataclasses.fields(cls)]


def test_result_types_have_the_contract_fields():
    assert field_names(api.Diagnostic)[:9] == [
        "file", "line", "column", "severity", "facility", "ident", "text", "explanation", "hint"]
    assert field_names(api.CompileResult)[:5] == ["ok", "diagnostics", "obj_path", "dia_path", "lis_path"]
    assert field_names(api.ParseResult) == ["ast", "diagnostics"]
    assert field_names(api.LinkResult) == ["ok", "diagnostics", "exe_path", "map_path"]
    assert field_names(api.RunResult)[:4] == ["exit_status", "output", "error", "traceback"]
    assert field_names(api.MessageInfo)[:6] == [
        "facility", "ident", "severity", "template", "explanation", "hint"]


def test_compile_writes_obj_and_dia_next_to_the_source(pas):
    pas.copy_example("HELLO")
    r = api.compile_file(pas.dir / "HELLO.PAS")
    assert r.ok and r.diagnostics == [] and r.lis_path is None
    assert Path(r.obj_path) == pas.dir / "HELLO.OBJ" and Path(r.dia_path) == pas.dir / "HELLO.DIA"
    assert Path(r.obj_path).exists() and Path(r.dia_path).exists()
    r = api.compile_file(pas.dir / "HELLO", list_file=True)
    assert Path(r.lis_path) == pas.dir / "HELLO.LIS"
    lis = Path(r.lis_path).read_text()
    assert "    8   1    WRITELN('Hello, world!')" in lis and "COMPILATION STATISTICS" in lis


def test_failed_compile_writes_dia_and_removes_stale_obj(pas):
    pas.write("BAD", "PROGRAM Bad(OUTPUT);\nBEGIN\n  WRITELN('a')\n  WRITELN(count)\nEND.\n")
    (pas.dir / "BAD.OBJ").write_text("stale")
    r = api.compile_file(pas.dir / "BAD", list_file=True)
    assert not r.ok and r.obj_path is None and not (pas.dir / "BAD.OBJ").exists()
    assert [d.ident for d in r.diagnostics] == ["SEMIEXP", "UNDECLID"]
    back = api.read_dia(r.dia_path)
    assert [(d.ident, d.line, d.column, d.severity, d.facility) for d in back] == [
        ("SEMIEXP", 4, 3, "E", "PASCAL"), ("UNDECLID", 4, 11, "E", "PASCAL")]
    assert back[0].text == r.diagnostics[0].text and back[1].hint == r.diagnostics[1].hint
    assert back[1].end_column == r.diagnostics[1].end_column
    dia = Path(r.dia_path).read_text()
    assert "region/file/primary" in dia and "/line=4/column_range=(11,15)" in dia
    lis = Path(r.lis_path).read_text()
    assert "(1) %PASCAL-E-SEMIEXP" in lis and "No object module was produced" in lis


def test_compile_missing_file():
    r = api.compile_file("/nonexistent/NOPE.PAS")
    assert not r.ok and r.diagnostics[0].code == "%PASCAL-F-OPENIN"


def test_parse_source_reports_placeholders_with_positions():
    text = "PROGRAM Guess(INPUT, OUTPUT);\nBEGIN\n  %{statement}%\nEND.\n"
    r = api.parse_source(text)
    assert r.ast is not None
    d = r.diagnostics[0]
    assert (d.ident, d.line, d.column, d.file) == ("PLACEHOLDER", 3, 3, "<buffer>")
    assert d.format(explain=False) == (
        "%PASCAL-E-PLACEHOLDER, unexpanded placeholder %{statement}% at line 3, column 3")


def test_tutor_style_checks_on_a_partly_finished_program():
    text = ("PROGRAM Guess(INPUT, OUTPUT);\nVAR\n  secret, guess, tries : INTEGER;\nBEGIN\n"
            "  RANDOMIZE;\n  Secret := random(100) + 1;\n  %{statement}%...\n"
            "  REPEAT\n    READLN(guess);\n    IF guess < secret THEN WRITELN('Too low!')\n"
            "  UNTIL guess = secret\nEND.\n")
    ast = api.parse_source(text).ast
    assert ast.declares("secret", "INTEGER") and ast.declares("TRIES")
    assert not ast.declares("secret", "REAL") and not ast.declares("answer")
    assert len(api.find_statements(ast, "secret := RANDOM(100) + 1")) == 1
    assert len(api.find_statements(ast, "secret := RANDOM(%{n}%) + 1")) == 1
    assert len(api.find_statements(ast, "secret := RANDOM(99) + 1")) == 0
    assert len(api.find_statements(ast, "RANDOMIZE")) == 1
    assert len(api.find_statements(ast, "IF guess < secret THEN %{statement}%")) == 1
    assert len(api.find_statements(ast, "IF %{condition}% THEN WRITELN('Too low!')")) == 1
    assert len(api.find_statements(ast, "IF %{condition}% THEN WRITELN('too low!')")) == 0
    assert len(api.find_statements(ast, "REPEAT %{statement}%... UNTIL guess = secret")) == 1
    assert len(api.find_statements(ast, "REPEAT READLN(guess) UNTIL %{c}%")) == 0
    assert api.parse_statement("x := ") is None
    assert api.parse_statement("a := 1; b := 2") is None


def test_full_pipeline_with_seed_and_input(pas):
    pas.copy_example("GUESS")
    assert api.compile_file(pas.dir / "GUESS").ok
    lr = api.link([str(pas.dir / "GUESS.OBJ")])
    assert lr.ok
    r = api.run_image(lr.exe_path, input_text="50\n", seed=1)
    assert r.output.startswith("I am thinking of a number from 1 to 100.\nYour guess? ")
    assert r.error.ident == "PASTEOF"

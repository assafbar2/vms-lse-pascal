from pathlib import Path

from pascal import api
from pascal import astnodes as A

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def parse(text):
    return api.parse_source(text, "TEST.PAS")


def test_guess_ast_is_inspectable():
    r = parse((EXAMPLES / "GUESS.PAS").read_text())
    assert r.diagnostics == []
    prog = r.ast
    assert prog.kind == "program" and prog.name == "Guess" and prog.params == ["INPUT", "OUTPUT"]
    assert prog.variables() == [("secret", "INTEGER"), ("guess", "INTEGER"), ("tries", "INTEGER")]
    var = prog.block.vars[0]
    assert var.kind == "var" and var.names == ["secret", "guess", "tries"] and var.type_name == "INTEGER"
    kinds = [s.kind for s in prog.statements()]
    assert kinds[:4] == ["compound", "call", "assign", "assign"]
    assert "repeat" in kinds and "if" in kinds
    calls = [s.name.upper() for s in prog.find_all("call")]
    assert "RANDOMIZE" in calls and "READLN" in calls
    assigns = {s.target_name.upper(): s.value.to_source() for s in prog.find_all("assign")}
    assert assigns["SECRET"] == "RANDOM(100) + 1"
    rep = prog.find_all("repeat")[0]
    assert rep.cond.to_source() == "guess = secret"
    assert [s.kind for s in rep.body] == ["call", "call", "assign", "if"]


def test_positions_are_recorded():
    r = parse("PROGRAM P;\nVAR x : INTEGER;\nBEGIN\n  x := 1\nEND.\n")
    assign = r.ast.find_all("assign")[0]
    assert (assign.line, assign.column, assign.end_line, assign.end_column) == (4, 3, 4, 9)


def test_placeholders_leave_a_usable_tree():
    src = ("PROGRAM %{program_name}%(INPUT, OUTPUT);\n"
           "%[declarations]%\n"
           "VAR secret : INTEGER;\n"
           "BEGIN\n"
           "  %{statement}%...\n"
           "  IF %{condition}% THEN WRITELN('x') %[ELSE %{statement}%]%\n"
           "END.\n")
    r = parse(src)
    assert r.ast is not None
    assert r.ast.variables() == [("secret", "INTEGER")]
    assert {d.ident for d in r.diagnostics} == {"PLACEHOLDER"}
    texts = [d.text for d in r.diagnostics]
    assert "unexpanded placeholder %{statement}%..." in texts
    stmt_kinds = [s.kind for s in r.ast.block.body.stmts]
    assert stmt_kinds[0] == "placeholder" and "if" in stmt_kinds
    cond = r.ast.find_all("if")[0].cond
    assert cond.kind == "placeholder_expr" and cond.name == "condition"


def test_missing_semicolon_reports_line_and_hint():
    src = "PROGRAM P;\nVAR x : INTEGER;\nBEGIN\n  x := 1\n  x := 2\nEND.\n"
    d = parse(src).diagnostics
    assert [x.ident for x in d] == ["SEMIEXP"]
    assert (d[0].line, d[0].column) == (5, 3)
    assert d[0].hint == 'Add ";" at the end of line 4, after "1".'
    assert d[0].format().startswith('%PASCAL-E-SEMIEXP, ";" expected at line 5, column 3\n  Explanation: ')


def test_common_novice_mistakes_have_specific_messages():
    cases = {
        "IF x > 1 THEN x := 1; ELSE x := 2": "ELSESEMI",
        "x = 5": "EQASSIGN",
        "IF x > 1 x := 1": "THENEXP",
        "WHILE x > 1 x := 1": "DOEXP",
        "FOR x := 1 10 DO x := 1": "TOEXP",
        "IF 1 < x < 10 THEN x := 1": "CHAINREL",
        "x := ": "EXPREXP",
        "WRITELN('a'": "RPAREXP",
        "REPEAT x := 1": "UNTILEXP",
    }
    for body, ident in cases.items():
        src = f"PROGRAM P;\nVAR x : INTEGER;\nBEGIN\n  {body}\nEND.\n"
        got = [d.ident for d in parse(src).diagnostics]
        assert ident in got, (body, got)


def test_else_after_semicolon_is_still_attached():
    r = parse("PROGRAM P; VAR x : INTEGER; BEGIN IF x > 1 THEN x := 1; ELSE x := 2 END.")
    assert r.ast.find_all("if")[0].else_part is not None


def test_missing_period_and_end():
    assert "PERIODEXP" in [d.ident for d in parse("PROGRAM P; BEGIN END").diagnostics]
    d = parse("PROGRAM P;\nBEGIN\n  WRITELN('x');\n").diagnostics
    assert d[0].ident == "ENDEXP"


def test_not_a_program_is_fatal():
    r = parse("x := 1;")
    assert r.ast is None and r.diagnostics[0].ident == "PROGEXP" and r.diagnostics[0].severity == "F"
    assert parse("").ast is None


def test_unsupported_features_are_named():
    r = parse("PROGRAM P; VAR p : ^INTEGER; BEGIN END.")
    assert r.diagnostics[0].ident == "NOTSUPP" and "pointer" in r.diagnostics[0].text
    r = parse("PROGRAM P; VAR r : INTEGER; BEGIN WITH r DO r := 1 END.")
    assert "WITH" in r.diagnostics[0].text


def test_error_recovery_reports_several_errors():
    src = ("PROGRAM P;\nVAR x : INTEGER;\nBEGIN\n  x := ;\n  IF x THEN\n  x := 1\n  WRITELN(x)\nEND.\n")
    idents = [d.ident for d in parse(src).diagnostics]
    assert "EXPREXP" in idents and "SEMIEXP" in idents


def test_module_and_attributes():
    src = ("MODULE M;\nVAR [GLOBAL] total : INTEGER;\n  hidden : [GLOBAL] INTEGER;\n"
           "[GLOBAL] PROCEDURE Add(n : INTEGER);\nBEGIN total := total + n END;\n"
           "FUNCTION Ext(x : REAL) : REAL; EXTERNAL;\nEND.\n")
    r = parse(src)
    assert r.diagnostics == []
    assert r.ast.is_module and r.ast.block.body is None
    v1, v2 = r.ast.block.vars
    assert v1.attributes == ["GLOBAL"] and v2.attributes == ["GLOBAL"]
    add, ext = r.ast.block.routines
    assert add.kind == "procedure" and add.attributes == ["GLOBAL"]
    assert ext.kind == "function" and ext.directive == "EXTERNAL" and ext.block is None


def test_types_unparse():
    src = ("PROGRAM P;\nTYPE R = RECORD a, b : INTEGER; c : CHAR END;\n"
           "VAR g : ARRAY [1..3, 'a'..'z'] OF REAL; s : 1..10; e : (Red, Green);\nBEGIN END.\n")
    r = parse(src)
    assert r.diagnostics == []
    assert r.ast.variables() == [("g", "ARRAY [1..3, 'a'..'z'] OF REAL"), ("s", "1..10"),
                                 ("e", "(Red, Green)")]
    assert r.ast.block.types[0].spec.text == "RECORD a, b : INTEGER; c : CHAR END"


def test_walk_visits_everything_in_order():
    r = parse("PROGRAM P; VAR x : INTEGER; BEGIN x := 1 + 2 * 3 END.")
    kinds = [n.kind for n in A.walk(r.ast)]
    assert kinds[:3] == ["program", "block", "var"]
    assert kinds.count("int") == 3
    assert r.ast.find_all("assign")[0].value.to_source() == "1 + 2 * 3"

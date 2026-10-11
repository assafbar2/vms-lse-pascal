import pytest

from pascal import api

DECLS = """
CONST Max = 10; Name = 'Bob';
TYPE Small = 1..10; Vec = ARRAY [1..5] OF INTEGER; RecT = RECORD a : INTEGER; c : CHAR END;
VAR i, j : INTEGER; r : REAL; b : BOOLEAN; ch : CHAR; v : Vec; s : Small; rec : RecT;
    w : ARRAY [1..3] OF CHAR;
PROCEDURE P(x : INTEGER; VAR y : INTEGER); BEGIN y := x END;
FUNCTION F(x : INTEGER) : INTEGER; BEGIN F := x END;
"""


def check(body: str, decls: str = DECLS) -> list[str]:
    src = f"PROGRAM T(INPUT, OUTPUT);\n{decls}\nBEGIN\n{body}\nEND.\n"
    return [d.ident for d in api.parse_source(src, "T.PAS").diagnostics]


def test_valid_program_has_no_messages():
    body = """
  i := 1; r := i; r := i / 2; b := (i > 0) AND (j < 3); ch := 'x'; s := 5;
  v[1] := Max; rec.a := v[1]; rec.c := ch; w := 'ab'; P(i, j); i := F(j) + 1;
  WRITELN(i:3, r:8:2, b, ch, 'text', w, Name); READLN(i, r, ch, w);
  IF ODD(i) THEN i := ABS(i) ELSE i := SQR(i); i := ROUND(r) + TRUNC(r) + ORD(ch);
  ch := CHR(65); ch := SUCC(ch); r := SQRT(r) + SIN(r) + COS(r) + EXP(r) + LN(r) + ARCTAN(r);
  i := RANDOM(10); r := RANDOM; RANDOMIZE; b := EOF OR EOLN;
  CASE i OF 1: i := 2; 2, 3: ; 4..6: i := 0 OTHERWISE i := 1 END;
  FOR i := 1 TO Max DO j := j + i; FOR ch := 'a' TO 'z' DO ; WHILE b DO b := NOT b;
  REPEAT i := i - 1 UNTIL i = 0"""
    assert check(body) == []


@pytest.mark.parametrize("body, ident", [
    ("count := 1", "UNDECLID"),
    ("i := r", "REALINT"),
    ("i := 'abc'", "INCASSIGN"),
    ("b := 1", "INCASSIGN"),
    ("ch := 65", "INCASSIGN"),
    ("IF i THEN i := 1", "NOTBOOL"),
    ("WHILE i + 1 DO i := 1", "NOTBOOL"),
    ("IF i > 0 AND i < 10 THEN i := 1", "BOOLOPINT"),
    ("i := r DIV 2", "REALDIV"),
    ("i := 'a' + 1", "INCOPERAND"),
    ("b := ch = 1", "INCOMPTYPES"),
    ("P(1)", "ARGCOUNT"),
    ("P(r, i)", "ARGTYPE"),
    ("P(1, 2)", "VARARG"),
    ("P(1, s)", "VARTYPE"),
    ("i := v", "INCASSIGN"),
    ("i := i[1]", "NOTARRAY"),
    ("i := v[1, 2]", "INDEXCOUNT"),
    ("i := v['a']", "INDEXTYPE"),
    ("i := v[9]", "OUTOFRANGE"),
    ("i := rec.zz", "NOFIELD"),
    ("i := i.a", "NOTRECORD"),
    ("s := 11", "OUTOFRANGE"),
    ("w := 'toolong'", "STRLENGTH"),
    ("Max := 3", "NOTVAR"),
    ("F(3)", "FUNCSTMT"),
    ("i := P", "NOTFUNC"),
    ("i", "NOTPROC"),
    ("READLN(b)", "READTYPE"),
    ("READLN(3)", "VARARG"),
    ("WRITELN(v)", "WRITETYPE"),
    ("WRITELN(i:r)", "WIDTHTYPE"),
    ("WRITELN(i:3:1)", "PRECREAL"),
    ("i := F(3:2)", "WIDTHUSE"),
    ("FOR r := 1 TO 3 DO i := 1", "FORVAR"),
    ("CASE i OF 'a': i := 1 END", "CASETYPE"),
    ("CASE i OF 1: i := 1; 1: i := 2 END", "DUPCASE"),
    ("CASE r OF 1: i := 1 END", "NOTORDINAL"),
    ("i := ABS(b)", "ARGTYPE"),
    ("i := ORD(1, 2)", "ARGCOUNT"),
    ("RANDOMIZE(3)", "ARGCOUNT"),
    ("i := Integer", "BADUSE"),
])
def test_semantic_errors(body, ident):
    got = check(body)
    assert ident in got, got


@pytest.mark.parametrize("decls, ident", [
    ("VAR x : INTEGER; x : REAL;", "MULDECL"),
    ("VAR x : Foo;", "UNDECLID"),
    ("VAR x : STRING;", "NOTSUPP"),
    ("CONST c = 1; VAR x : c;", "NOTTYPE"),
    ("TYPE T = 10..1;", "BADRANGE"),
    ("VAR n : INTEGER; TYPE T = 1..n;", "CONSTEXPR"),
    ("TYPE T = ARRAY [REAL] OF INTEGER;", "NOTORDINAL"),
    ("FUNCTION F(x : INTEGER) : INTEGER; BEGIN END;", "NORESULT"),
    ("TYPE V = ARRAY [1..2] OF INTEGER; FUNCTION F : V; BEGIN END;", "FUNCTYPE"),
    ("PROCEDURE P; FORWARD;", "FWDNOTDEF"),
    ("PROCEDURE P(x : INTEGER); FORWARD; PROCEDURE P(x : REAL); BEGIN END;", "HEADMISMAT"),
    ("PROCEDURE P; VAR [GLOBAL] x : INTEGER; BEGIN END;", "ATTRLEVEL"),
    ("[EXTERNAL] PROCEDURE P; BEGIN END;", "EXTBODY"),
    ("VAR [VOLATILE] x : INTEGER;", "BADATTR"),
])
def test_declaration_errors(decls, ident):
    got = check("", decls)
    assert ident in got, got


def test_undeclared_identifier_reported_once_with_name_in_hint():
    src = "PROGRAM T;\nBEGIN\n  count := 1;\n  count := count + 1\nEND.\n"
    d = api.parse_source(src, "T.PAS").diagnostics
    assert [x.ident for x in d] == ["UNDECLID"]
    assert d[0].format(explain=False) == '%PASCAL-E-UNDECLID, undeclared identifier "count" at line 3, column 3'
    assert "VAR count : INTEGER" in d[0].hint


def test_program_name_does_not_clash_with_a_variable():
    src = "PROGRAM Guess;\nVAR guess : INTEGER;\nBEGIN guess := 1 END.\n"
    assert api.parse_source(src).diagnostics == []


def test_program_parameter_warning():
    src = "PROGRAM T(datafile);\nBEGIN END.\n"
    d = api.parse_source(src).diagnostics
    assert d[0].ident == "PROGPARAM" and d[0].severity == "W"


def test_semantic_types_are_annotated():
    src = "PROGRAM T;\nVAR x : INTEGER; y : REAL;\nBEGIN y := x / 2 END.\n"
    ast = api.parse_source(src).ast
    value = ast.find_all("assign")[0].value
    assert str(value.type) == "REAL"
    assert str(value.left.type) == "INTEGER"
    assert value.left.symbol.name == "x"


def test_parse_source_without_semantic_check():
    r = api.parse_source("PROGRAM T; BEGIN count := 1 END.", semantic=False)
    assert r.diagnostics == [] and r.ast is not None

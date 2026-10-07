"""Fatal run-time errors: a %PAS-F message plus a symbolic traceback."""

import pytest

AVERAGE = """PROGRAM Average(INPUT, OUTPUT);
VAR total, count : INTEGER;
FUNCTION Mean(sum, n : INTEGER) : INTEGER;
BEGIN
  Mean := sum DIV n
END;
PROCEDURE Report;
BEGIN
  WRITELN('The average is ', Mean(total, count):1)
END;
BEGIN
  total := 0;
  count := 0;
  Report
END.
"""


def test_division_by_zero_traceback(pas):
    r = pas.run(AVERAGE, name="AVERAGE")
    assert r.exit_status == 1
    assert r.error.code == "%PAS-F-DIVBYZERO"
    assert r.error.line == 5 and r.error.file.endswith("AVERAGE.PAS")
    assert r.error.explanation and r.error.hint
    assert r.traceback[0] == "%TRACE-F-TRACEBACK, symbolic stack dump follows"
    frames = [ln.split() for ln in r.traceback[2:]]
    assert [(f[0], f[1], f[2]) for f in frames] == [
        ("AVERAGE", "MEAN", "5"), ("AVERAGE", "REPORT", "9"), ("AVERAGE", "AVERAGE", "14")]
    out = r.output
    assert "%PAS-F-DIVBYZERO, division by zero at line 5" in out
    assert "  Explanation: " in out and "  Hint: " in out
    assert out.index("%PAS-F-DIVBYZERO") < out.index("%TRACE-F-TRACEBACK")
    assert out.startswith("The average is \n%PAS-F-DIVBYZERO")


def test_noexplain_omits_explanation(pas):
    exe = pas.build("AVERAGE", AVERAGE)
    from pascal import api
    r = api.run_image(exe, input_text="", explain=False)
    assert "Explanation" not in r.output and "%TRACE-F-TRACEBACK" in r.output


@pytest.mark.parametrize("decls, body, ident, text", [
    ("VAR a : ARRAY [1..3] OF INTEGER; i : INTEGER;", "i := 4; a[i] := 1",
     "ARRINDVAL", "array index value 4 is out of range 1..3"),
    ("VAR s : 1..10; i : INTEGER;", "i := 11; s := i", "VALOUTRAN", "value 11 is out of range 1..10"),
    ("VAR i : INTEGER;", "i := 5; CASE i OF 1: i := 0 END", "CASSELVAL",
     "CASE selector value 5 does not match any CASE label"),
    ("VAR i : INTEGER;", "i := MAXINT; i := i + 1", "INTOVF", "integer overflow"),
    ("VAR i : INTEGER;", "i := 300; WRITELN(CHR(i))", "VALOUTRAN", "value 300 is out of range 0..255"),
    ("VAR secret, tries : INTEGER;", "tries := tries + 1", "UNINITVAR",
     "variable TRIES used before it was given a value"),
    ("VAR x : REAL;", "x := -4; WRITELN(SQRT(x))", "SQUROONEG", "square root of a negative number (-4)"),
    ("VAR x : REAL;", "x := 0; WRITELN(LN(x))", "LOGNONPOS", "logarithm of zero or a negative number (0)"),
    ("VAR x : REAL;", "x := 0; x := 1 / x", "DIVBYZERO", "division by zero"),
    ("VAR i : INTEGER;", "i := 0; WRITELN(RANDOM(i))", "RANDARG", "RANDOM(0): the argument must be at least 1"),
    ("VAR i : INTEGER;", "i := -1; WRITELN(5:i)", "NEGWIDDIG", "negative field width or number of digits (-1)"),
    ("VAR i : INTEGER;", "READLN(i)", "PASTEOF", "attempt to read past the end of the input"),
    ("VAR x : REAL; i : INTEGER;", "x := 1.0E10; i := ROUND(x)", "INTOVF", "integer overflow"),
    ("VAR c : CHAR;", "c := CHR(255); c := SUCC(c)", "VALOUTRAN", "value 256 is out of range 0..255"),
])
def test_runtime_errors(pas, decls, body, ident, text):
    src = f"PROGRAM T(INPUT, OUTPUT);\n{decls}\nBEGIN\n  {body}\nEND.\n"
    r = pas.run(src)
    assert r.error is not None, r.output
    assert r.error.ident == ident and r.error.facility == "PAS" and r.error.severity == "F"
    assert r.error.text == text
    assert r.error.line == 4
    assert r.traceback[-1].split()[:3] == ["T", "T", "4"]


def test_uninitialized_local_and_array_element(pas):
    src = """PROGRAM U(OUTPUT);
PROCEDURE P;
VAR count : INTEGER; a : ARRAY [1..3] OF INTEGER;
BEGIN
  a[1] := 0;
  WRITELN(a[1] + a[2])
END;
BEGIN P END."""
    r = pas.run(src)
    assert r.error.ident == "UNINITVAR"
    assert r.error.text == "variable A[...] used before it was given a value"
    assert r.error.line == 6


def test_function_without_result(pas):
    src = """PROGRAM F(OUTPUT);
VAR i : INTEGER;
FUNCTION Pick(n : INTEGER) : INTEGER;
BEGIN
  IF n > 0 THEN Pick := n
END;
BEGIN
  i := Pick(0)
END."""
    r = pas.run(src)
    assert r.error.ident == "NOFUNCRES"
    assert 'function "PICK"' in r.error.text
    assert [ln.split()[1] for ln in r.traceback[2:]] == ["PICK", "F"]


def test_runaway_recursion_is_a_stack_overflow(pas):
    src = """PROGRAM S(OUTPUT);
PROCEDURE Forever(n : INTEGER);
BEGIN
  Forever(n + 1)
END;
BEGIN Forever(1) END."""
    r = pas.run(src)
    assert r.error.ident == "STKOVF"
    assert len(r.traceback) == 2 + 20 + 1 + 5
    assert "more calls not shown" in r.traceback[22]
    assert r.traceback[-1].split()[:3] == ["S", "S", "6"]
    assert r.traceback[2].split()[:3] == ["S", "FOREVER", "4"]


def test_endless_loop_hits_the_step_limit(pas):
    src = "PROGRAM L(OUTPUT); VAR i : INTEGER; BEGIN i := 0; WHILE TRUE DO i := 1 END."
    r = pas.run(src, max_steps=10_000)
    assert r.error.ident == "STEPLIMIT"
    assert r.error.text == "program stopped after 10000 instructions"


def test_error_inside_runtime_library_points_at_user_line(pas):
    src = "PROGRAM E(INPUT, OUTPUT);\nVAR i : INTEGER;\nBEGIN\n  WRITE('n? ');\n  READLN(i)\nEND.\n"
    r = pas.run(src, input_text="")
    assert r.error.ident == "PASTEOF" and r.error.line == 5
    first = r.traceback[2].split()
    assert first[:2] == ["PAS$IO", "PAS$READ_INT"]
    assert r.traceback[3].split()[:3] == ["E", "E", "5"]

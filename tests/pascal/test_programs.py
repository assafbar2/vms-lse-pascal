"""Programs compiled, linked and run end to end."""

from pathlib import Path

FEATURES = (Path(__file__).parent / "data" / "FEATURES.PAS").read_text()


def test_feature_program(pas):
    out = pas.output(FEATURES)
    assert out.splitlines() == [
        "Sum = 55 v[1] still 1",
        "7 3",
        "9 4",
        "1,2 10,2",
        "RED GREEN BLUE ",
        "1 BLUE RED",
        "abcde",
        " 5 4 3 2 1",
        "    6.2832  6.28318E+00  4.0  3.50",
        "3 4 -3 -3",
        "3 -3 1 -1",
        "  TRUE    TRUE   TRUE   TRUE  TRUE",
        "[Hi there]",
        "[Bob     ]B",
        "Hi t|  x|   42|-42",
        "23 31",
        "10",
        "Outer(3) count = 6",
        "total 62",
        "a-e",
        "Ab 5 16 2.5 2147483647",
        "done 0",
    ]


def test_default_field_widths_follow_vax_pascal(pas):
    out = pas.output("PROGRAM W(OUTPUT); BEGIN WRITELN(42, TRUE, 'c', 1.5); WRITELN(-7:1, 'x':0) END.")
    assert out == "        42  TRUEc 1.50000E+00\n-7\n"


def test_recursion_and_function_results(pas):
    src = """PROGRAM R(OUTPUT);
FUNCTION Fib(n : INTEGER) : INTEGER;
BEGIN
  IF n < 2 THEN Fib := n ELSE Fib := Fib(n - 1) + Fib(n - 2)
END;
FUNCTION Answer : INTEGER;
BEGIN Answer := 42 END;
BEGIN
  WRITELN(Fib(15):1, ' ', Answer:1)
END."""
    assert pas.output(src) == "610 42\n"


def test_nested_procedures_reach_outer_variables_and_params(pas):
    src = """PROGRAM N(OUTPUT);
VAR g : INTEGER;
PROCEDURE A(VAR total : INTEGER; step : INTEGER);
  VAR local : INTEGER;
  PROCEDURE B;
    PROCEDURE C;
    BEGIN total := total + step; local := local + 1; g := g + 100 END;
  BEGIN C; C END;
BEGIN local := 0; B; B; WRITELN('local ', local:1) END;
BEGIN
  g := 0; A(g, 5); WRITELN('g ', g:1)
END."""
    assert pas.output(src) == "local 4\ng 420\n"


def test_records_with_arrays_and_structured_value_params(pas):
    src = """PROGRAM S(OUTPUT);
TYPE
  Scores = ARRAY [1..3] OF INTEGER;
  Player = RECORD name : PACKED ARRAY [1..5] OF CHAR; score : Scores END;
  Team = ARRAY [1..2] OF Player;
VAR t : Team; i, k : INTEGER;
FUNCTION Total(p : Player) : INTEGER;
VAR k, s : INTEGER;
BEGIN s := 0; FOR k := 1 TO 3 DO s := s + p.score[k]; p.score[1] := 0; Total := s END;
PROCEDURE Bump(VAR p : Player);
BEGIN p.score[2] := p.score[2] + 1000 END;
BEGIN
  t[1].name := 'Ann'; t[2].name := 'Bobby';
  FOR i := 1 TO 2 DO FOR k := 1 TO 3 DO t[i].score[k] := i * k;
  Bump(t[2]);
  FOR i := 1 TO 2 DO WRITELN(t[i].name, Total(t[i]):6, t[i].score[1]:3)
END."""
    assert pas.output(src) == "Ann       6  1\nBobby  1012  2\n"


def test_while_repeat_for_and_case(pas):
    src = """PROGRAM C(OUTPUT);
VAR i, n : INTEGER; c : CHAR;
BEGIN
  n := 0; i := 10;
  WHILE i > 0 DO BEGIN n := n + i; i := i - 3 END;
  REPEAT n := n * 2 UNTIL n > 100;
  FOR i := 3 DOWNTO 1 DO n := n + i;
  FOR i := 5 TO 1 DO n := 0;
  WRITELN(n:1);
  FOR c := 'a' TO 'f' DO
    CASE c OF
      'a', 'e': WRITE('vowel ');
      'b'..'d': WRITE(c, ' ')
      OTHERWISE WRITE('? ')
    END;
  WRITELN
END."""
    assert pas.output(src) == "182\nvowel b c d vowel ? \n"


def test_short_circuit_boolean_operators(pas):
    src = """PROGRAM B(OUTPUT);
VAR a : ARRAY [1..3] OF INTEGER; i : INTEGER;
BEGIN
  a[1] := 1; a[2] := 2; a[3] := 3; i := 4;
  IF (i <= 3) AND (a[i] > 0) THEN WRITELN('no') ELSE WRITELN('safe');
  IF (i > 3) OR (a[i] > 0) THEN WRITELN('safe too')
END."""
    assert pas.output(src) == "safe\nsafe too\n"


def test_integer_arithmetic_rules(pas):
    src = """PROGRAM A(OUTPUT);
BEGIN
  WRITELN(17 DIV 5:1, ' ', (-17) DIV 5:1, ' ', 17 MOD 5:1, ' ', (-17) MOD 5:1, ' ', 17 DIV (-5):1);
  WRITELN(MAXINT - 1 + 1:1, ' ', SUCC(5):1, ' ', PRED('b'), ' ', ORD(TRUE):1, ' ', ODD(-3))
END."""
    assert pas.output(src) == "3 -3 2 -2 -3\n2147483647 6 a 1   TRUE\n"


def test_real_arithmetic_and_formatting(pas):
    src = """PROGRAM F(OUTPUT);
VAR x : REAL; i : INTEGER;
BEGIN
  i := 7; x := i / 2; WRITELN(x:6:2, i * 1.5:6:1, -x:8:3);
  WRITELN(x:12, ' ', 123456.789:0:2, ' ', 0.001:9);
  WRITELN(ROUND(2.5):1, ROUND(-0.5):3, TRUNC(9.99):3, SQRT(2):8:4)
END."""
    assert pas.output(src) == ("  3.50  10.5  -3.500\n 3.50000E+00 123456.79  1.00E-03\n"
                                "3 -1  9  1.4142\n")


def test_enumerations(pas):
    src = """PROGRAM E(OUTPUT);
TYPE Day = (Mon, Tue, Wed, Thu, Fri);
VAR d : Day; count : ARRAY [Day] OF INTEGER;
BEGIN
  FOR d := Mon TO Fri DO count[d] := ORD(d) * 10;
  d := Wed;
  WRITELN(d, ' ', SUCC(d), ' ', count[Thu]:1, ' ', d > Tue, ' ', d:5, '|')
END."""
    assert pas.output(src) == "WED THU 30   TRUE   WED|\n"


def test_string_constants_and_char_arrays(pas):
    src = """PROGRAM S(INPUT, OUTPUT);
CONST Title = 'Report';
TYPE Str = PACKED ARRAY [1..10] OF CHAR;
VAR s, t : Str;
PROCEDURE Show(x : Str); BEGIN WRITELN('<', x, '>') END;
BEGIN
  s := Title; t := s; t[1] := 'r'; Show(s); Show(t); Show('literal');
  READLN(s); WRITELN('[', s, ']', s:3, '|')
END."""
    out = pas.output(src, "Typed here and more\n")
    assert out == "<Report    >\n<report    >\n<literal   >\n[Typed here]Typ|\n"


def test_comparing_character_arrays(pas):
    src = """PROGRAM Names(INPUT, OUTPUT);
TYPE Name = PACKED ARRAY [1..5] OF CHAR;
VAR a, b : Name;
BEGIN
  READLN(a);
  b := 'Bob';
  WRITELN(a = 'Bob', a = b, a < 'Carl', 'Bob' = b, a <> 'Bob  ', a > 'B')
END."""
    assert pas.output(src, "Bob\n") == "  TRUE  TRUE  TRUE  TRUE FALSE  TRUE\n"


def test_string_comparison_errors(idents):
    decls = "PROGRAM T; VAR a : PACKED ARRAY [1..3] OF CHAR; b : PACKED ARRAY [1..4] OF CHAR; x : BOOLEAN;"
    assert "INCOMPTYPES" in idents(decls + " BEGIN x := a = b END.")
    assert "INCOMPTYPES" in idents(decls + " BEGIN x := a = 'toolong' END.")
    assert idents(decls + " BEGIN x := a = 'ab' END.") == []


def test_read_mixed_values(pas):
    src = """PROGRAM Rd(INPUT, OUTPUT);
VAR a, b : INTEGER; x : REAL; c, d : CHAR;
BEGIN
  READ(a, b); READLN(x);
  READ(c); READ(d); READLN;
  WRITELN(a + b:1, ' ', x:4:1, ' ', c, d, '.');
  WHILE NOT EOF DO BEGIN READLN(a); WRITE(a:3) END;
  WRITELN
END."""
    out = pas.output(src, "3 4\n  2.5 ignored\nxy z\n1\n2\n3\n")
    assert out == "7  2.5 xy.\n  1  2  3\n"


def test_eoln_and_read_char_at_end_of_line(pas):
    src = """PROGRAM L(INPUT, OUTPUT);
VAR c : CHAR; n : INTEGER;
BEGIN
  n := 0;
  WHILE NOT EOLN DO BEGIN READ(c); n := n + 1 END;
  READ(c);
  WRITELN(n:1, ' [', c, ']')
END."""
    assert pas.output(src, "abcd\nnext\n") == "4 [ ]\n"


def test_halt_stops_normally(pas):
    r = pas.run("PROGRAM H(OUTPUT); BEGIN WRITELN('a'); HALT; WRITELN('b') END.")
    assert r.output == "a\n" and r.exit_status == 0 and r.error is None


def test_global_variables_in_procedures_and_subrange_checks_pass(pas):
    src = """PROGRAM G(OUTPUT);
VAR s : 1..10; i : INTEGER;
PROCEDURE Store(v : INTEGER); BEGIN s := v END;
BEGIN
  FOR i := 1 TO 10 DO Store(i);
  WRITELN(s:1)
END."""
    assert pas.output(src) == "10\n"

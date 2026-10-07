PROGRAM Features(INPUT, OUTPUT);
CONST
  N = 5;
  Greeting = 'Hi there';
  Pi = 3.14159;
TYPE
  Color = (Red, Green, Blue);
  Point = RECORD x, y : INTEGER END;
  Vec = ARRAY [1..N] OF INTEGER;
  Name = PACKED ARRAY [1..8] OF CHAR;
  Grid = ARRAY [1..3, 1..3] OF INTEGER;
VAR
  i, j, total : INTEGER;
  v : Vec;
  p, q : Point;
  c : Color;
  ch : CHAR;
  r : REAL;
  b : BOOLEAN;
  nm : Name;
  g : Grid;
  small : 1..10;

FUNCTION IsEven(k : INTEGER) : BOOLEAN; FORWARD;

FUNCTION IsOdd(k : INTEGER) : BOOLEAN;
BEGIN
  IF k = 0 THEN IsOdd := FALSE ELSE IsOdd := IsEven(k - 1)
END;

FUNCTION IsEven;
BEGIN
  IF k = 0 THEN IsEven := TRUE ELSE IsEven := IsOdd(k - 1)
END;

PROCEDURE Swap(VAR a, b : INTEGER);
VAR t : INTEGER;
BEGIN
  t := a; a := b; b := t
END;

PROCEDURE Outer(depth : INTEGER);
VAR count : INTEGER;
  PROCEDURE Inner;
    PROCEDURE Deepest;
    BEGIN
      count := count + depth
    END;
  BEGIN
    Deepest; Deepest
  END;
BEGIN
  count := 0;
  Inner;
  WRITELN('Outer(', depth:1, ') count = ', count:1)
END;

FUNCTION Sum(a : Vec) : INTEGER;
VAR k, s : INTEGER;
BEGIN
  s := 0;
  FOR k := 1 TO N DO s := s + a[k];
  a[1] := 999;
  Sum := s
END;

BEGIN
  FOR i := 1 TO N DO v[i] := i * i;
  WRITELN('Sum = ', Sum(v):1, ' v[1] still ', v[1]:1);
  i := 3; j := 7; Swap(i, j); WRITELN(i:1, ' ', j:1);
  Swap(v[2], v[3]); WRITELN(v[2]:1, ' ', v[3]:1);
  p.x := 1; p.y := 2; q := p; q.x := 10; WRITELN(p.x:1, ',', p.y:1, ' ', q.x:1, ',', q.y:1);
  FOR c := Red TO Blue DO WRITE(c, ' '); WRITELN;
  c := Green; WRITELN(ORD(c):1, ' ', SUCC(c), ' ', PRED(c));
  FOR ch := 'a' TO 'e' DO WRITE(ch); WRITELN;
  FOR i := 5 DOWNTO 1 DO WRITE(i:2); WRITELN;
  r := Pi * 2; WRITELN(r:10:4, ' ', r, ' ', SQRT(16.0):4:1, ' ', 7 / 2:5:2);
  WRITELN(TRUNC(3.7):1, ' ', ROUND(3.5):1, ' ', ROUND(-2.5):1, ' ', TRUNC(-3.7):1);
  WRITELN(7 DIV 2:1, ' ', -7 DIV 2:1, ' ', 7 MOD 3:1, ' ', -7 MOD 3:1);
  b := (i > 0) AND NOT (j < 0); WRITELN(b, ' ', b:7, ' ', ODD(3), ' ', IsEven(10), IsOdd(7));
  nm := Greeting; WRITELN('[', nm, ']'); nm := 'Bob'; WRITELN('[', nm, ']', nm[1]);
  WRITELN(Greeting:4, '|', 'x':3, '|', 42:5, '|', -42:1);
  FOR i := 1 TO 3 DO FOR j := 1 TO 3 DO g[i, j] := i * 10 + j;
  WRITELN(g[2, 3]:1, ' ', g[3][1]:1);
  small := 10; WRITELN(small:1);
  Outer(3);
  total := 0;
  FOR i := 1 TO 10 DO
    CASE i MOD 4 OF
      0: total := total + 1;
      1, 2: total := total + 10;
      3: ;
    END;
  WRITELN('total ', total:1);
  CASE ch OF 'a'..'e': WRITELN('a-e'); OTHERWISE WRITELN('other') END;
  WRITELN(CHR(65), CHR(ORD('a') + 1), ' ', ABS(-5):1, ' ', SQR(4):1, ' ', ABS(-2.5):3:1, ' ', MAXINT:1);
  i := 0;
  WHILE i < 3 DO i := i + 1;
  REPEAT i := i - 1 UNTIL i = 0;
  WRITELN('done ', i:1)
END.

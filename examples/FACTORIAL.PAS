PROGRAM Factorial(OUTPUT);
{ Recursion: Fact calls itself with a smaller number until it reaches 1.
  12! is the largest factorial that fits in an INTEGER; try changing
  the loop to go up to 13 to see %PAS-F-INTOVF and a traceback. }
VAR
  n : INTEGER;

FUNCTION Fact(k : INTEGER) : INTEGER;
BEGIN
  IF k <= 1 THEN
    Fact := 1
  ELSE
    Fact := k * Fact(k - 1)
END;

BEGIN
  FOR n := 1 TO 12 DO
    WRITELN(n:2, '! = ', Fact(n):10)
END.

PROGRAM MathDemo(OUTPUT);
{ Uses routines from the separately compiled module MATHLIB.PAS.
  EXTERNAL says "this is defined in another module; LINK will find it". }

VAR
  [EXTERNAL] CallCount : INTEGER;
  i : INTEGER;

FUNCTION Square(x : INTEGER) : INTEGER; EXTERNAL;
FUNCTION GCD(a, b : INTEGER) : INTEGER; EXTERNAL;
PROCEDURE PrintBar(n : INTEGER); EXTERNAL;

BEGIN
  CallCount := 0;
  FOR i := 1 TO 5 DO
  BEGIN
    WRITE(i:1, ' squared is ', Square(i):2, '  ');
    PrintBar(Square(i))
  END;
  WRITELN('GCD(84, 36) = ', GCD(84, 36):1);
  WRITELN('MATHLIB routines were called ', CallCount:1, ' times.')
END.

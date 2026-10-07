MODULE MathLib;
{ A MODULE holds routines and variables for other programs to use.
  [GLOBAL] makes a name visible to LINK.  Build the example with:

    PASCAL MATHLIB
    PASCAL MATHDEMO
    LINK MATHDEMO, MATHLIB
    RUN MATHDEMO

  Leave MATHLIB out of the LINK command to see %LINK-W-UNDFSYMS. }

VAR
  [GLOBAL] CallCount : INTEGER;

[GLOBAL] FUNCTION Square(x : INTEGER) : INTEGER;
BEGIN
  CallCount := CallCount + 1;
  Square := x * x
END;

[GLOBAL] FUNCTION GCD(a, b : INTEGER) : INTEGER;
{ Greatest common divisor, by Euclid's method. }
VAR
  t : INTEGER;
BEGIN
  CallCount := CallCount + 1;
  WHILE b <> 0 DO
  BEGIN
    t := a MOD b;
    a := b;
    b := t
  END;
  GCD := a
END;

[GLOBAL] PROCEDURE PrintBar(n : INTEGER);
VAR
  i : INTEGER;
BEGIN
  CallCount := CallCount + 1;
  FOR i := 1 TO n DO
    WRITE('*');
  WRITELN
END;

END.

PROGRAM Average(INPUT, OUTPUT);
{ Reads numbers until you type 0, then prints their average.
  Type 0 straight away to see a run-time error (%PAS-F-DIVBYZERO)
  and the traceback that shows which routines were running. }
VAR
  total, count : INTEGER;

FUNCTION Mean(sum, n : INTEGER) : INTEGER;
BEGIN
  Mean := sum DIV n
END;

PROCEDURE Report;
BEGIN
  WRITELN('The average is ', Mean(total, count):1)
END;

PROCEDURE ReadNumbers;
VAR
  x : INTEGER;
BEGIN
  REPEAT
    WRITE('Number (0 to stop)? ');
    READLN(x);
    IF x <> 0 THEN
    BEGIN
      total := total + x;
      count := count + 1
    END
  UNTIL x = 0
END;

BEGIN
  total := 0;
  count := 0;
  ReadNumbers;
  Report
END.

PROGRAM Primes(OUTPUT);
{ The sieve of Eratosthenes: start with every number marked as a
  candidate, then cross out the multiples of each prime that is left. }
CONST
  Limit = 100;
TYPE
  Sieve = ARRAY [2..Limit] OF BOOLEAN;
VAR
  candidate : Sieve;
  count : INTEGER;

PROCEDURE CrossOut(VAR s : Sieve);
VAR
  i, multiple : INTEGER;
BEGIN
  FOR i := 2 TO Limit DO
    s[i] := TRUE;
  i := 2;
  WHILE i * i <= Limit DO
  BEGIN
    IF s[i] THEN
    BEGIN
      multiple := i * i;
      WHILE multiple <= Limit DO
      BEGIN
        s[multiple] := FALSE;
        multiple := multiple + i
      END
    END;
    i := i + 1
  END
END;

PROCEDURE PrintPrimes(s : Sieve; VAR found : INTEGER);
VAR
  i : INTEGER;

  PROCEDURE Show(p : INTEGER);
  { A nested procedure: it can use "found" from PrintPrimes. }
  BEGIN
    found := found + 1;
    WRITE(p:5);
    IF found MOD 10 = 0 THEN
      WRITELN
  END;

BEGIN
  found := 0;
  FOR i := 2 TO Limit DO
    IF s[i] THEN
      Show(i);
  IF found MOD 10 <> 0 THEN
    WRITELN
END;

BEGIN
  WRITELN('Prime numbers up to ', Limit:1, ':');
  CrossOut(candidate);
  PrintPrimes(candidate, count);
  WRITELN('There are ', count:1, ' of them.')
END.

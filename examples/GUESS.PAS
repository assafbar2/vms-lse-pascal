PROGRAM Guess(INPUT, OUTPUT);
VAR
  secret, guess, tries : INTEGER;
BEGIN
  RANDOMIZE;
  secret := RANDOM(100) + 1;
  tries := 0;
  WRITELN('I am thinking of a number from 1 to 100.');
  REPEAT
    WRITE('Your guess? ');
    READLN(guess);
    tries := tries + 1;
    IF guess < secret THEN
      WRITELN('Too low!')
    ELSE IF guess > secret THEN
      WRITELN('Too high!')
    ELSE
      WRITELN('Correct! You got it in ', tries:1, ' tries.')
  UNTIL guess = secret
END.

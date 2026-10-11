"""The run-time library: input/output behaviour and random numbers."""

import io

from pascal import api
from pascal.rtl import Lcg, Runtime

ASK = """PROGRAM Ask(INPUT, OUTPUT);
VAR n : INTEGER; x : REAL;
BEGIN
  WRITE('Number? ');
  READLN(n);
  WRITE('Real? ');
  READLN(x);
  WRITELN('Got ', n:1, ' and ', x:4:2)
END.
"""

DICE = """PROGRAM Dice(OUTPUT);
VAR i : INTEGER;
BEGIN
  RANDOMIZE;
  FOR i := 1 TO 10 DO WRITE(RANDOM(6) + 1:2);
  WRITELN;
  WRITELN(RANDOM < 1.0)
END.
"""


def test_bad_integer_input_reprompts(pas):
    r = pas.run(ASK, input_text="abc\n12\n1.5\n")
    assert r.error is None and r.exit_status == 0
    assert r.output == (
        "Number? \n"
        '%PAS-W-INVSYNINT, "abc" is not a valid INTEGER\n'
        "  Explanation: The program asked for a whole number, but what was typed is not one. "
        "Whole numbers are digits only, optionally with a sign, like 42 or -7.\n"
        "  Hint: Type a whole number and press RETURN.\n"
        "Number? Real? Got 12 and 1.50\n")


def test_bad_real_input_reprompts_and_transcript_shows_input(pas):
    r = pas.run(ASK, input_text="7\nseven\n7.25\n", explain=False)
    assert r.error is None
    assert r.transcript == (
        "Number? 7\nReal? seven\n"
        '%PAS-W-INVSYNREA, "seven" is not a valid REAL number\n'
        "Real? 7.25\nGot 7 and 7.25\n")


def test_random_is_repeatable_with_a_seed(pas):
    exe = pas.build("DICE", DICE)
    a = api.run_image(exe, seed=7).output
    b = api.run_image(exe, seed=7).output
    c = api.run_image(exe, seed=8).output
    assert a == b and a != c
    rolls = [int(x) for x in a.splitlines()[0].split()]
    assert len(rolls) == 10 and all(1 <= x <= 6 for x in rolls)
    assert len(set(rolls)) > 1


def test_random_without_randomize_is_repeatable_and_randomize_without_seed_varies(pas):
    src = "PROGRAM R(OUTPUT); BEGIN WRITELN(RANDOM(1000000):1) END."
    exe = pas.build("R", src)
    assert api.run_image(exe).output == api.run_image(exe).output
    src2 = "PROGRAM R2(OUTPUT); BEGIN RANDOMIZE; WRITELN(RANDOM(1000000000):1) END."
    exe2 = pas.build("R2", src2)
    outs = {api.run_image(exe2).output for _ in range(3)}
    assert len(outs) > 1


def test_lcg_is_the_vax_generator():
    g = Lcg(0)
    g.state = 1
    g.next()
    assert g.state == 69070


def test_random_range():
    rt = Runtime(seed=1)
    values = {rt.random(3) for _ in range(200)}
    assert values == {0, 1, 2}


def test_interactive_streams_tee_output(pas):
    exe = pas.build("ASK", ASK)
    stdin = io.StringIO("x\n5\n2\n")
    stdout = io.StringIO()
    r = api.run_image(exe, stdin=stdin, stdout=stdout, explain=False)
    assert r.error is None
    terminal = stdout.getvalue()
    assert terminal == ("Number? "
                        '%PAS-W-INVSYNINT, "x" is not a valid INTEGER\n'
                        "Number? Real? Got 5 and 2.00\n")
    assert r.output.endswith("Got 5 and 2.00\n")
    assert r.transcript == ("Number? x\n" '%PAS-W-INVSYNINT, "x" is not a valid INTEGER\n'
                            "Number? 5\nReal? 2\nGot 5 and 2.00\n")


def test_stdout_with_scripted_input_echoes_input(pas):
    exe = pas.build("ASK", ASK)
    stdout = io.StringIO()
    api.run_image(exe, input_text="5\n2\n", stdout=stdout)
    assert stdout.getvalue() == "Number? 5\nReal? 2\nGot 5 and 2.00\n"


def test_fatal_error_is_written_to_the_terminal(pas):
    exe = pas.build("ASK", ASK)
    stdout = io.StringIO()
    r = api.run_image(exe, stdin=io.StringIO("5\n"), stdout=stdout)
    assert r.error.ident == "PASTEOF"
    assert "%PAS-F-PASTEOF" in stdout.getvalue() and "%TRACE-F-TRACEBACK" in stdout.getvalue()


def test_ctrl_c_stops_the_program(pas):
    exe = pas.build("ASK", ASK)

    class Interrupting(io.StringIO):
        def readline(self, *a):
            raise KeyboardInterrupt

    r = api.run_image(exe, stdin=Interrupting(), stdout=io.StringIO())
    assert r.error.ident == "CONTROLC" and r.exit_status == 1


def test_missing_and_bad_images(tmp_path):
    r = api.run_image(tmp_path / "NOPE")
    assert r.error.ident == "NOIMAGE" and r.exit_status == 1 and "%PAS-F-NOIMAGE" in r.output
    bad = tmp_path / "BAD.EXE"
    bad.write_text("this is not an image\n")
    r = api.run_image(bad)
    assert r.error.ident == "BADIMAGE"

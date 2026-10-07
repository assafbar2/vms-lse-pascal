"""Every example builds, and GUESS plays deterministically with a seed."""

import pytest

from pascal import api
from pascal.rtl import Runtime


def build(pas, *names):
    pas.copy_example(*names)
    for n in names:
        r = api.compile_file(pas.dir / n)
        assert r.ok, [d.format() for d in r.diagnostics]
    lr = api.link([str(pas.dir / n) for n in names])
    assert lr.ok, [d.format() for d in lr.diagnostics]
    return lr.exe_path


def secret_for(seed: int) -> int:
    rt = Runtime(seed=seed)
    rt.randomize()
    return rt.random(100) + 1


def play_script(secret: int) -> tuple[str, int]:
    """Binary-search guesses for ``secret``, as typed by a player."""
    lo, hi, guesses = 1, 100, []
    while True:
        g = (lo + hi) // 2
        guesses.append(g)
        if g == secret:
            return "".join(f"{x}\n" for x in guesses), len(guesses)
        if g < secret:
            lo = g + 1
        else:
            hi = g - 1


def test_hello(pas):
    assert api.run_image(build(pas, "HELLO")).output == "Hello, world!\n"


def test_factorial(pas):
    out = api.run_image(build(pas, "FACTORIAL")).output.splitlines()
    assert out[0] == " 1! =          1" and out[-1] == "12! =  479001600" and len(out) == 12


def test_primes(pas):
    out = api.run_image(build(pas, "PRIMES")).output
    assert out.splitlines()[1].split()[:5] == ["2", "3", "5", "7", "11"]
    assert out.endswith("There are 25 of them.\n")


def test_mathdemo(pas):
    out = api.run_image(build(pas, "MATHDEMO", "MATHLIB")).output
    assert out.endswith("MATHLIB routines were called 16 times.\n")


def test_average_runtime_error(pas):
    r = api.run_image(build(pas, "AVERAGE"), input_text="0\n")
    assert r.error.code == "%PAS-F-DIVBYZERO"
    assert [ln.split()[1] for ln in r.traceback[2:]] == ["MEAN", "REPORT", "AVERAGE"]
    ok = api.run_image(build(pas, "AVERAGE"), input_text="3\n5\n0\n")
    assert ok.output.endswith("The average is 4\n") and ok.error is None


@pytest.mark.parametrize("seed", [1, 42, 2026])
def test_guess_plays_deterministically(pas, seed):
    exe = build(pas, "GUESS")
    secret = secret_for(seed)
    script, tries = play_script(secret)
    r = api.run_image(exe, input_text=script, seed=seed)
    assert r.error is None and r.exit_status == 0
    assert r.output.startswith("I am thinking of a number from 1 to 100.\n")
    assert r.output.endswith(f"Correct! You got it in {tries} tries.\n")
    assert r.output.count("Your guess? ") == tries
    again = api.run_image(exe, input_text=script, seed=seed)
    assert again.output == r.output


def test_guess_survives_a_letter_typed_into_the_game(pas):
    exe = build(pas, "GUESS")
    secret = secret_for(5)
    r = api.run_image(exe, input_text=f"fifty\n{secret}\n", seed=5)
    assert r.error is None
    assert '%PAS-W-INVSYNINT, "fifty" is not a valid INTEGER' in r.output
    assert r.output.endswith("Correct! You got it in 1 tries.\n")

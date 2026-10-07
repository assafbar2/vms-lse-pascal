"""The DCL-like command-line tools."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pascal import cli

ROOT = Path(__file__).resolve().parents[2]


def run_cli(args, cwd, input_text=""):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "pascal", *args], cwd=cwd, input=input_text,
                          capture_output=True, text=True, env=env, timeout=60)


def test_pascal_link_run_from_a_shell(pas):
    pas.copy_example("HELLO")
    r = run_cli(["PASCAL", "HELLO"], pas.dir)
    assert r.returncode == 0 and r.stdout == ""
    r = run_cli(["LINK", "HELLO"], pas.dir)
    assert r.returncode == 0 and (pas.dir / "HELLO.EXE").exists() and (pas.dir / "HELLO.MAP").exists()
    r = run_cli(["RUN", "HELLO"], pas.dir)
    assert r.returncode == 0 and r.stdout == "Hello, world!\n"


def test_guess_with_seed_and_piped_input(pas):
    pas.copy_example("GUESS")
    assert run_cli(["PASCAL", "GUESS"], pas.dir).returncode == 0
    assert run_cli(["LINK", "GUESS"], pas.dir).returncode == 0
    from pascal.rtl import Runtime
    rt = Runtime(seed=42)
    rt.randomize()
    secret = rt.random(100) + 1
    r = run_cli(["RUN", "/SEED=42", "GUESS"], pas.dir, input_text=f"x\n{secret}\n")
    assert r.returncode == 0
    assert "Your guess? x\n%PAS-W-INVSYNINT" in r.stdout
    assert r.stdout.endswith("Correct! You got it in 1 tries.\n")
    r2 = run_cli(["RUN", "GUESS", "--seed", "42"], pas.dir, input_text=f"{secret}\n")
    assert r2.stdout.endswith("Correct! You got it in 1 tries.\n")
    r3 = run_cli(["RUN/SEED=42", "GUESS"], pas.dir, input_text=f"{secret}\n")
    assert r3.stdout == r2.stdout


def test_compile_errors_show_source_line_and_caret(pas):
    pas.write("BAD", "PROGRAM Bad(OUTPUT);\nBEGIN\n  WRITELN(count)\nEND.\n")
    r = run_cli(["PASCAL", "BAD"], pas.dir)
    assert r.returncode == 1
    lines = r.stdout.splitlines()
    assert lines[0] == "     3    WRITELN(count)"
    assert lines[1] == " " * 18 + "^"
    assert lines[2] == '%PASCAL-E-UNDECLID, undeclared identifier "count" at line 3, column 11'
    assert lines[3].startswith("  Explanation: ")
    r = run_cli(["PASCAL", "/NOEXPLAIN", "BAD"], pas.dir)
    assert "Explanation" not in r.stdout


def test_runtime_error_from_the_shell(pas):
    pas.copy_example("AVERAGE")
    run_cli(["PASCAL", "AVERAGE"], pas.dir)
    run_cli(["LINK", "AVERAGE"], pas.dir)
    r = run_cli(["RUN", "AVERAGE"], pas.dir, input_text="0\n")
    assert r.returncode == 1
    assert "%PAS-F-DIVBYZERO, division by zero at line 10" in r.stdout
    assert "%TRACE-F-TRACEBACK, symbolic stack dump follows" in r.stdout
    assert "AVERAGE         MEAN                               10" in r.stdout


def test_link_two_modules_dcl_style(pas):
    pas.copy_example("MATHLIB", "MATHDEMO")
    assert run_cli(["PASCAL", "MATHLIB", "MATHDEMO"], pas.dir).returncode == 0
    assert run_cli(["LINK", "MATHDEMO,", "MATHLIB"], pas.dir).returncode == 0
    r = run_cli(["LINK", "MATHDEMO"], pas.dir)
    assert r.returncode == 1 and "%LINK-W-UNDFSYMS" in r.stdout and "%LINK-E-NOIMGFIL" in r.stdout


def test_listing_qualifier_forms(pas):
    pas.copy_example("HELLO")
    for args in (["/LIST", "HELLO"], ["HELLO/LIST"], ["--list", "HELLO"]):
        lis = pas.dir / "HELLO.LIS"
        if lis.exists():
            lis.unlink()
        assert run_cli(["PASCAL", *args], pas.dir).returncode == 0
        assert lis.exists(), args


def test_parse_args():
    files, opts = cli.parse_args(["/SEED=5", "GUESS"], cli.RUN_QUALS)
    assert files == ["GUESS"] and opts == {"SEED": "5"}
    files, opts = cli.parse_args(["A,", "B,C", "/NOMAP", "--exe", "OUT"], cli.LINK_QUALS)
    assert files == ["A", "B", "C"] and opts == {"NOMAP": True, "EXECUTABLE": "OUT"}
    files, opts = cli.parse_args(["dir/file.pas"], cli.PASCAL_QUALS)
    assert files == ["dir/file.pas"] and opts == {}
    with pytest.raises(cli.UsageError):
        cli.parse_args(["--frobnicate"], cli.PASCAL_QUALS)


def test_usage_errors(capsys):
    assert cli.pascal_main([]) == 2
    assert "usage: pascal" in capsys.readouterr().err
    assert cli.main(["FROB"]) == 2


@pytest.mark.skipif(shutil.which("pascal") is None, reason="package not installed")
def test_installed_entry_points(pas):
    pas.copy_example("HELLO")
    assert subprocess.run(["pascal", "HELLO"], cwd=pas.dir).returncode == 0
    for linker in ("paslink", "link"):
        if shutil.which(linker) and "/.local/" in shutil.which(linker) or linker == "paslink":
            assert subprocess.run([linker, "HELLO"], cwd=pas.dir).returncode == 0
            break
    r = subprocess.run(["pasrun", "HELLO"], cwd=pas.dir, capture_output=True, text=True)
    assert r.stdout == "Hello, world!\n"

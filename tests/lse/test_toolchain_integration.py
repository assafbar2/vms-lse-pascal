"""COMPILE, LINK, RUN inside LSE with the real Pascal toolchain (pascal.api)."""

import os

import pytest

from lse.testing import EditorHarness

api = pytest.importorskip("pascal.api")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def example(name):
    with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def h(tmp_path):
    files = {n: example(n) for n in ("GUESS.PAS", "AVERAGE.PAS", "HELLO.PAS")}
    return EditorHarness(tmp_path, api=api, app=True, files=files)


def test_run_shows_banners_and_fills_output(h):
    h.open("GUESS.PAS")
    h.editor.run_seed = 7
    h.host.program_input = "50\nabc\n32\n"
    h.press("F5")
    run = h.host.transcripts[-1]
    assert run.startswith("Running GUESS.EXE. Type your answers and press RETURN. "
                          "Ctrl-C stops the program.\n")
    assert run.rstrip().endswith("Program finished. Press RETURN to go back to LSE.")
    out = h.editor.buffers["$OUTPUT"].lines
    assert out[0] == "I am thinking of a number from 1 to 100."
    assert "Your guess? 50" in out and "Your guess? abc" in out
    assert '%PAS-W-INVSYNINT, "abc" is not a valid INTEGER' in out
    assert out[-1] == "Correct! You got it in 2 tries."
    assert "GUESS.EXE finished (exit status 0)" in h.message
    assert h.next_line.startswith("Edit and try again")


def test_run_time_error_banner_output_and_f8(h):
    h.open("AVERAGE.PAS")
    h.host.program_input = "0\n"
    h.press("F5")
    assert "Program stopped because of the error above." in h.host.transcripts[-1]
    out = "\n".join(h.editor.buffers["$OUTPUT"].lines)
    assert "%PAS-F-DIVBYZERO" in out and "%TRACE-F-TRACEBACK" in out
    assert "(F8 goes to line 10. Output and traceback: buffer $OUTPUT.)" in h.message
    assert h.next_line.startswith("F8 goes to line 10 where the program stopped")
    assert "RUN!" in h.status
    h.press("F8")
    assert h.cursor[0] == 9


def test_set_messages_noexplain_for_compile_and_run(h):
    h.write_file("BAD.PAS", "PROGRAM Bad(OUTPUT);\nBEGIN\n  WRITELN('x')\n  WRITELN('y')\nEND.\n")
    h.open("BAD.PAS")
    h.press("F7")
    assert "Explanation:" in h.message
    h.command("SET MESSAGES /NOEXPLAIN")
    h.press("F7")
    assert "%PASCAL-E-SEMIEXP" in h.message and "Explanation:" not in h.message
    h.open("AVERAGE.PAS")
    h.host.program_input = "0\n"
    h.press("F5")
    out = "\n".join(h.editor.buffers["$OUTPUT"].lines)
    assert "%PAS-F-DIVBYZERO" in out and "Explanation:" not in out
    h.command("SET MESSAGES /EXPLAIN")
    h.press("F5")
    assert "Explanation:" in "\n".join(h.editor.buffers["$OUTPUT"].lines)


def test_link_map_opens_read_only_and_ctrl_o_enter_goes_back(h):
    h.open("GUESS.PAS")
    h.press("F7")
    h.command("LINK")
    assert "the map is in GUESS.MAP" in h.message
    h.command("GOTO FILE GUESS.MAP")
    assert h.buffer.read_only and "read-only" in h.message
    assert any("PAS$RANDOM" in line and "PASRTL" in line for line in h.lines)
    h.type("x")
    assert "read-only" in h.message
    h.press("C-o")
    assert "Open file [GUESS.PAS]:" in h.command_line
    h.press("Enter")
    assert h.buffer.name.startswith("GUESS.PAS")


def test_ctrl_c_during_run_stops_the_program(h):
    h.open("GUESS.PAS")
    h.host.program_input = "50\n\x03\n"
    h.press("F5")
    assert "Program stopped. Press RETURN" in h.host.transcripts[-1]
    assert "%LSE-W-STOPPED, GUESS.EXE was stopped with Ctrl-C" in " ".join(h.message.split())
    assert h.next_line.startswith("F5 runs it again (Ctrl-C stopped it")


def test_run_seed_repeats_the_secret(h):
    h.open("GUESS.PAS")
    h.press("F7")
    h.command("LINK")
    h.command('RUN /SEED=7 /INPUT="32"')
    assert h.editor.buffers["$OUTPUT"].lines[-1] == "Correct! You got it in 1 tries."

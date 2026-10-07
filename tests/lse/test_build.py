"""COMPILE / LINK / RUN / REVIEW through the toolchain adapter (fake pascal.api)."""

import types

import pytest
from lse_helpers import HELLO

from lse.testing import EditorHarness, FakePascalApi
from lse.toolchain import Toolchain, ToolchainUnavailable

BROKEN = """PROGRAM Broken(INPUT, OUTPUT);
BEGIN
  WRITELN(%{write_item}%...);
  SYNTAXERROR here
END.
"""

ASK = """PROGRAM Ask(INPUT, OUTPUT);
VAR n : INTEGER;
BEGIN
  WRITE('Number? ');
  READLN(n);
  WRITELN('Thanks')
END.
"""


def open_file(tmp_path, name, text, **kw):
    h = EditorHarness(tmp_path, files={name: text}, **kw)
    h.open(name)
    return h


def test_compile_clean(hello):
    hello.press("F7")
    assert "%LSE-S-COMPILED, HELLO.PAS compiled with no errors" in hello.message
    assert hello.exists("HELLO.OBJ") and hello.exists("HELLO.DIA")
    st = hello.editor.build_for(hello.buffer)
    assert st.compile_ok and st.compiled_state == hello.buffer.state_id


def test_compile_saves_first(hello):
    hello.type("{x}")
    hello.press("F7")
    assert hello.exists("HELLO.PAS;2")
    assert not hello.buffer.modified


def test_compile_errors_and_f8_review(tmp_path):
    h = open_file(tmp_path, "BROKEN.PAS", BROKEN)
    h.press("F7")
    msg = h.message
    assert "%LSE-E-COMPERR, BROKEN.PAS has 2 errors. Press F8" in msg
    assert "%PASCAL-E-PLACEHOLDER, unexpanded placeholder %{write_item}%..." in msg
    assert "Explanation:" in msg
    h.press("F8")
    assert h.cursor == (2, 10)
    assert h.message.startswith("(1 of 2) %PASCAL-E-PLACEHOLDER")
    h.press("F8")
    assert h.cursor == (3, 2)
    assert h.message.startswith("(2 of 2) %PASCAL-E-SYNTAX")
    h.press("F8")
    assert "last one" in h.message
    h.press("S-F8")
    assert h.cursor == (2, 10)
    h.feed("<Esc>8")  # Esc 8 = F8 for terminals that keep F8
    assert h.cursor == (3, 2)


def test_review_window(tmp_path):
    h = open_file(tmp_path, "BROKEN.PAS", BROKEN)
    h.press("F7")
    h.command("REVIEW")
    scr = h.screen
    assert "window1" in scr.regions
    review = "\n".join(scr.region("window1"))
    assert " 1. %PASCAL-E-PLACEHOLDER" in review and " 2. %PASCAL-E-SYNTAX" in review
    assert h.buffer.name == "$REVIEW"
    h.feed("<Down><Down><Down><Enter>")
    assert h.buffer.name == "BROKEN.PAS" and h.cursor == (3, 2)
    h.press("Esc")
    assert len(h.editor.windows) == 1 and h.buffer.name == "BROKEN.PAS"


def test_set_messages_noexplain(tmp_path):
    h = open_file(tmp_path, "BROKEN.PAS", BROKEN)
    h.command("SET MESSAGES /NOEXPLAIN")
    h.press("F7")
    assert "Explanation:" not in h.message


def test_link_before_compile_says_what_to_do(hello):
    hello.command("LINK")
    assert "NOTCOMPILED" in hello.message and "F7" in hello.message


def test_link_after_errors_refuses(tmp_path):
    h = open_file(tmp_path, "BROKEN.PAS", BROKEN)
    h.press("F7")
    h.command("LINK")
    assert "COMPERR" in h.message


def test_compile_link_run_separately(hello):
    hello.press("F7")
    hello.command("LINK")
    assert "%LSE-S-LINKED, HELLO.EXE written; the map is in HELLO.MAP" in hello.message
    hello.command("RUN")
    assert "%LSE-S-RAN, HELLO.EXE finished" in hello.message
    out = hello.editor.buffers["$OUTPUT"]
    assert out.lines == ["Hello, world"]
    transcript = hello.host.transcripts[-1]
    assert transcript.startswith("Running HELLO.EXE.")
    assert "Hello, world" in transcript and "Press RETURN to go back to LSE" in transcript


def test_run_before_link(hello):
    hello.command("RUN")
    assert "NOTLINKED" in hello.message and "F5" in hello.message


def test_f5_builds_and_runs_with_input(tmp_path):
    h = open_file(tmp_path, "ASK.PAS", ASK, program_input="42\n")
    h.press("F5")
    assert "RAN" in h.message and "exit status 0" in h.message
    assert h.editor.buffers["$OUTPUT"].lines == ["Number? 42", "Thanks"]
    api = h.api
    names = [c[0] for c in api.calls]
    assert names == ["compile_file", "link", "run_image"]


def test_f5_stops_at_compile_errors(tmp_path):
    h = open_file(tmp_path, "BROKEN.PAS", BROKEN)
    h.press("F5")
    assert "COMPERR" in h.message
    assert [c[0] for c in h.api.calls] == ["compile_file"]


def test_run_with_input_and_seed_qualifiers(tmp_path):
    h = open_file(tmp_path, "ASK.PAS", ASK)
    h.press("F7")
    h.command("LINK")
    h.command('RUN/SEED=7/INPUT="5"')
    assert h.api.calls[-1] == ("run_image", (h.path("ASK.EXE"), "5", 7))
    assert h.host.transcripts == []


def test_runtime_error_shows_traceback(tmp_path):
    h = open_file(tmp_path, "DIV.PAS", HELLO.replace("WRITELN('Hello, world')",
                                                     "WRITELN('a'); DIVBYZERO"))
    h.press("F5")
    assert "%PAS-F-DIVBYZERO" in h.message
    out = h.editor.buffers["$OUTPUT"].lines
    assert "%TRACE-F-TRACEBACK, symbolic stack dump follows" in out


def test_runtime_error_already_in_output_is_not_repeated(tmp_path):
    h = open_file(tmp_path, "DIV.PAS", HELLO.replace("WRITELN('Hello, world')",
                                                     "WRITELN('a'); DIVBYZERO"))
    real_run = h.api.run_image

    def run_like_real_runtime(exe, **kw):
        res = real_run(exe, **kw)
        res.output += res.error.format() + "\n" + "\n".join(res.traceback) + "\n"
        return res
    h.api.run_image = run_like_real_runtime
    h.press("F5")
    out = h.editor.buffers["$OUTPUT"].lines
    assert sum(line.startswith("%PAS-F-DIVBYZERO") for line in out) == 1
    assert sum(line.startswith("%TRACE-F-TRACEBACK") for line in out) == 1


def test_toolchain_missing_is_a_friendly_error(tmp_path):
    h = EditorHarness(tmp_path, files={"HELLO.PAS": HELLO})
    h.editor.toolchain = Toolchain(module="no_such_pascal_module_xyz")
    h.open("HELLO.PAS")
    h.press("F7")
    assert "%LSE-E-NOTOOLCHAIN" in h.message


def test_link_undefined_symbol_goes_to_review(tmp_path):
    h = open_file(tmp_path, "U.PAS", HELLO.replace("WRITELN('Hello, world')",
                                                   "x := 1;\n  UNDEFINEDSYM(x)"))
    h.press("F5")
    assert "%LSE-E-LINKERR, LINK failed. Press F8" in h.message
    assert "%LINK-W-UNDFSYMS, undefined symbol UNDEFINEDSYM" in h.message
    h.feed("<C-Home><F8>")
    assert h.cursor == (3, 2)


def test_noexplain_reaches_the_runtime(hello):
    hello.command("SET MESSAGES /NOEXPLAIN")
    hello.press("F5")
    assert hello.api.last_explain is False


def test_adapter_leaves_out_explain_for_older_apis():
    seen = {}
    api = types.SimpleNamespace(run_image=lambda exe, *, input_text=None, stdin=None,
                                stdout=None, seed=None: seen.update(exe=exe, seed=seed))
    Toolchain(api).run("A.EXE", seed=1, explain=False)
    assert seen == {"exe": "A.EXE", "seed": 1}


def test_toolchain_crash_becomes_a_message(hello):
    def boom(path, *, list_file=False):
        raise RuntimeError("compiler bug")
    hello.api.compile_file = boom
    hello.press("F5")
    assert "%LSE-F-TOOLFAIL, COMPILE stopped with an internal error" in hello.message
    assert "compiler bug" in "\n".join(hello.editor.messages_buffer.lines)
    hello.type("still editing")
    assert hello.lines[0].startswith("still editing")


def test_link_and_run_reject_names_that_are_not_files(hello):
    hello.command("LINK .")
    assert "NOFILE" in hello.message
    hello.command("RUN NOPE")
    assert "NOIMAGE" in hello.message


def test_adapter_uses_the_contract_signatures():
    calls = []
    api = types.SimpleNamespace(
        parse_source=lambda text, filename="<buffer>": calls.append(("parse", text, filename)),
        compile_file=lambda path, *, list_file=False: calls.append(("compile", path, list_file)),
        link=lambda objs, *, output=None, map_file=True: calls.append(("link", objs, output, map_file)),
        run_image=lambda exe, *, input_text=None, stdin=None, stdout=None, seed=None:
            calls.append(("run", exe, input_text, stdin, stdout, seed)),
        get_message=lambda fac, ident: calls.append(("msg", fac, ident)),
        all_messages=lambda: [1, 2],
    )
    tc = Toolchain(api)
    tc.parse("x", "A.PAS")
    tc.compile("A.PAS", list_file=True)
    tc.link(["A.OBJ"], map_file=False)
    tc.run("A.EXE", input_text="1", seed=3)
    tc.message("PASCAL", "UNDECLID")
    assert tc.all_messages() == [1, 2]
    assert calls == [("parse", "x", "A.PAS"), ("compile", "A.PAS", True),
                     ("link", ["A.OBJ"], None, False), ("run", "A.EXE", "1", None, None, 3),
                     ("msg", "PASCAL", "UNDECLID")]


def test_adapter_reports_missing_module():
    tc = Toolchain(module="no_such_pascal_module_xyz")
    assert not tc.available
    with pytest.raises(ToolchainUnavailable):
        tc.compile("A.PAS")


def test_fake_api_parse_reports_placeholders():
    res = FakePascalApi().parse_source("x := %{expression}%;")
    assert res.ast is None
    assert res.diagnostics[0].format(explain=False) == \
        "%PASCAL-E-PLACEHOLDER, unexpanded placeholder %{expression}% at line 1"

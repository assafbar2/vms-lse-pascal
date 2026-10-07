"""The guidance layer: the NEXT line, the pipeline indicator, the key bar, WHAT NOW."""

import itertools

import pytest

from lse import guidance
from lse.guidance import ACTION_WORDS, OVERLAYS, VIEWS, State, next_action, pipeline_of
from lse.overlays import TextViewOverlay
from lse.testing import EditorHarness

BUILD_STATES = [
    # compiled, linked, ran (the combinations the editor can actually reach)
    ("none", "none", "none"),
    ("stale", "stale", "stale"),
    ("stale", "none", "none"),
    ("failed", "none", "none"),
    ("failed", "none", "stale"),
    ("ok", "none", "none"),
    ("warnings", "none", "none"),
    ("ok", "stale", "stale"),
    ("ok", "failed", "none"),
    ("ok", "ok", "none"),
    ("ok", "ok", "stale"),
    ("ok", "ok", "ok"),
    ("ok", "ok", "error"),
    ("ok", "ok", "stopped"),
]
TUTOR_TEXTS = ["", "Type Guess over %{program_name}% and press Tab",
               "Stuck? Press F4 for a hint. Press F5 to compile, link and run it"]


def all_states():
    for view, overlay in itertools.product(VIEWS, OVERLAYS):
        info = {"prompt": "Open file [GUESS.PAS]: ", "question": "Y or N",
                "menu": "statement"}.get(overlay, "")
        for (compiled, linked, ran), placeholders, modified, tutor, at in itertools.product(
                BUILD_STATES, (0, 3), (False, True), TUTOR_TEXTS,
                ("", "%{statement}%...")):
            if at and not placeholders:
                continue
            for kind in (("MENU", "NONTERMINAL", "TERMINAL") if at else ("",)):
                yield State(view=view, overlay=overlay, overlay_info=info,
                            placeholders=placeholders, at_placeholder=at,
                            at_placeholder_kind=kind, modified=modified, compiled=compiled,
                            errors=2 if compiled == "failed" else 0, linked=linked, ran=ran,
                            run_error_line=7 if ran == "error" else 0, tutor=tutor,
                            back="Ctrl-W goes back to GUESS.PAS" if view != "source" else "",
                            suggest_tutorial=not tutor)


def test_next_action_is_never_empty_and_always_actionable():
    seen = 0
    texts = set()
    for s in all_states():
        text = next_action(s)
        assert text.strip(), s
        assert ACTION_WORDS.search(text), (text, s)
        if not s.tutor or s.overlay:
            assert len(text) <= 74, text  # fits the NEXT line of an 80-column screen
        texts.add(text)
        seen += 1
    assert seen > 10000
    assert len(texts) > 25  # the advice really depends on the state


def test_rules_follow_the_plan_order():
    s = State()
    assert next_action(s) == "F7 compiles GUESS.PAS (F5 also links and runs it)"
    assert next_action(State(placeholders=3)) == "Tab to the next placeholder (3 left)"
    assert next_action(State(placeholders=2, at_placeholder="%{statement}%...",
                             at_placeholder_kind="MENU")).startswith("Tab shows the choices")
    assert next_action(State(modified=True)).startswith("Ctrl-S saves")
    assert next_action(State(compiled="stale")).startswith("F7 compiles")
    assert next_action(State(compiled="failed", errors=3)) == \
        "F8 goes to error 1 of 3; fix it, then F7 compiles again"
    assert next_action(State(compiled="failed", errors=3, error_index=0)).startswith(
        "F8 goes to error 2 of 3")
    assert next_action(State(compiled="ok")).startswith("F5 links and runs it")
    assert next_action(State(compiled="ok", linked="ok")) == "F5 runs GUESS.EXE"
    assert next_action(State(compiled="ok", linked="ok", ran="ok")).startswith(
        "Edit and try again")
    assert "line 7" in next_action(State(compiled="ok", linked="ok", ran="error",
                                         run_error_line=7))


def test_overlays_and_views_come_first():
    assert next_action(State(overlay="menu", placeholders=3)).startswith("Up/Down to choose")
    assert "Esc" in next_action(State(overlay="question", overlay_info="Y or N"))
    assert next_action(State(view="review")).startswith("Enter goes to the message")
    assert "Ctrl-W goes back" in next_action(State(view="output", back="Ctrl-W goes back to X"))
    assert next_action(State(view="none")).startswith("Ctrl-O opens a file")
    tutor = State(tutor="Type Guess over %{program_name}% and press Tab", placeholders=3)
    assert next_action(tutor) == "Type Guess over %{program_name}% and press Tab"


def test_pipeline_stages():
    def labels(s):
        return [(st.label, st.status) for st in pipeline_of(s)]

    assert labels(State()) == [("EDIT", "done"), ("COMPILE", "current"), ("LINK", "pending"),
                               ("RUN", "pending")]
    assert labels(State(placeholders=2))[0] == ("EDIT", "current")
    assert labels(State(compiled="failed"))[:2] == [("EDIT", "current"), ("COMPILE!", "failed")]
    assert labels(State(compiled="ok", linked="ok", ran="ok")) == [
        ("EDIT", "done"), ("COMPILE", "done"), ("LINK", "done"), ("RUN", "done")]
    assert labels(State(compiled="stale", linked="stale", ran="stale")) == [
        ("EDIT", "done"), ("COMPILE*", "current"), ("LINK*", "stale"), ("RUN*", "stale")]
    assert labels(State(compiled="ok", linked="ok", ran="error"))[3] == ("RUN!", "failed")


@pytest.fixture
def app(tmp_path):
    return EditorHarness(tmp_path, app=True, files={"HELLO.PAS": "PROGRAM Hello(INPUT, OUTPUT);\n"
                                                    "BEGIN\n  WRITELN('Hi')\nEND.\n"})


def test_layout_with_next_line_and_key_bar(app):
    app.open("HELLO.PAS")
    scr = app.screen
    assert scr.regions["status0"] == [20]
    assert scr.regions["next"] == [21]
    assert scr.regions["message"] == [22]
    assert scr.regions["keybar"] == [23]
    assert scr.regions["command"] == []
    assert app.next_line.startswith("F7 compiles HELLO.PAS")
    assert app.key_bar.startswith("F1 Help  ^S Save")
    assert app.key_bar.rstrip().endswith("^Q Quit")
    assert scr.role_at(23, 0) == "keybar_key"


def test_prompt_takes_the_key_bar_row(app):
    app.open("HELLO.PAS")
    app.press("C-p")
    scr = app.screen
    assert scr.regions["command"] == [23] and scr.regions["keybar"] == []
    assert app.command_line.startswith("LSE>")
    assert app.next_line.startswith("Type a command and press Enter")
    app.press("Esc")
    assert app.screen.regions["keybar"] == [23]


def test_next_line_follows_the_build_cycle(app):
    app.open("HELLO.PAS")
    assert app.next_line.startswith("F7 compiles")
    app.press("F7")
    assert app.next_line.startswith("F5 links and runs it")
    app.press("F5")
    assert app.next_line.startswith("Edit and try again")
    app.feed("<End>x")
    assert app.next_line.startswith("Ctrl-S saves")
    app.press("C-s")
    assert app.next_line.startswith("F7 compiles")


def test_next_line_after_errors_and_in_review(app):
    app.write_file("BAD.PAS", "PROGRAM Bad(INPUT, OUTPUT);\nBEGIN\n  SYNTAXERROR\nEND.\n")
    app.open("BAD.PAS")
    app.press("F7")
    assert app.next_line == "F8 goes to the error; fix it, then F7 compiles again"
    app.command("REVIEW")
    assert app.next_line.startswith("Enter goes to the message")
    assert "Esc Back to code" in app.key_bar
    app.press("Esc")
    assert app.next_line.startswith("F8 goes to the error")


def test_pipeline_indicator_in_the_status_line(app):
    app.open("HELLO.PAS")
    assert "[ EDIT > COMPILE > LINK > RUN ]" in app.status
    row = app.screen.regions["status0"][0]
    col = app.status.index("COMPILE")
    assert app.screen.role_at(row, col) == "pipeline_current"
    app.press("F5")
    row = app.screen.regions["status0"][0]
    assert app.screen.role_at(row, col) == "pipeline_done"
    app.feed("<End>x")
    assert "[ EDIT > COMPILE* > LINK* > RUN* ]" in app.status


def test_key_bar_follows_the_context(app):
    app.open("NEW.PAS")
    app.press("Tab")
    assert app.key_bar.startswith("Up/Down Choose  Enter Pick")
    app.press("Esc")
    app.type("x").press("C-q")
    assert "unsaved changes" in app.command_line
    assert app.screen.regions["keybar"] == []  # the question is on that row
    app.press("Esc")
    assert app.key_bar.endswith("^Q Quit")


def test_output_buffer_says_how_to_get_back(app):
    app.open("HELLO.PAS")
    app.press("F5")
    app.command("GOTO BUFFER $OUTPUT")
    assert app.next_line == "Your program's output. Ctrl-O then Enter goes back to HELLO.PAS"
    assert app.key_bar.startswith("^O Enter Back to code")
    app.feed("<C-o><Enter>")
    assert app.buffer.name == "HELLO.PAS"


def test_main_buffer_and_text_files(app):
    assert app.next_line.startswith("Ctrl-O opens a file")
    app.write_file("NOTES.TXT", "hello\n")
    app.open("NOTES.TXT")
    assert app.next_line.startswith("Type to edit it")
    app.type("x")
    assert app.next_line.startswith("Ctrl-S saves")


def test_suggests_the_tutorial_until_the_first_build(tmp_path):
    wide = EditorHarness(tmp_path, app=True, size=(24, 120), files={"A.PAS": "x\n"})
    wide.open("A.PAS")
    assert guidance.TUTORIAL_TIP in wide.next_line
    wide.press("F7")
    assert guidance.TUTORIAL_TIP not in wide.next_line


def test_lse_file_offers_the_tutorial(tmp_path):
    h = EditorHarness(tmp_path, args=["HELLO.PAS"])
    assert "lines read from file" not in h.message  # a new file
    assert guidance.TUTORIAL_OFFER.split(".")[0] in " ".join(h.message.split())


def test_what_now_explains_the_state(app):
    app.open("HELLO.PAS")
    app.press("F7")
    app.press("End", "F1")
    assert isinstance(app.overlay, TextViewOverlay)
    text = " ".join(app.screen.text().replace("│", " ").split())
    assert "What now?" in text
    assert "You are editing HELLO.PAS." in text
    assert "It compiled, but it hasn't been linked since your last change." in text
    assert "F5 links and runs it" in text
    assert any("LSE keypad" in line for line in app.overlay.lines)


def test_f1_on_a_placeholder_still_explains_the_placeholder(app):
    app.open("NEW.PAS")
    app.press("F1")
    assert "Placeholder %{compilation_unit}%" in app.screen.text()

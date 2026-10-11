"""File names and file systems that differ between Linux, macOS and Windows."""

import errno
import os

import pytest

from lse import files
from lse.testing import EditorHarness


@pytest.mark.parametrize("leaf,problem", [
    ("GUESS.PAS", None),
    ("GUESS.PAS;3", None),
    ("my game.pas", None),
    ("a<b.PAS", "Windows does not allow <"),
    ("what?.PAS", "Windows does not allow ?"),
    ('say"hi".PAS', 'Windows does not allow "'),
    ("CON.PAS", "CON is a device name on Windows"),
    ("nul", "NUL is a device name on Windows"),
    ("trailing.", "end with a dot or a space"),
    ("", "the file name is empty"),
])
def test_windows_file_name_rules(leaf, problem):
    found = files.name_problem(leaf, windows=True)
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found


def test_other_systems_allow_more():
    assert files.name_problem("a<b?.PAS", windows=False) is None
    assert files.name_problem("CON.PAS", windows=False) is None


@pytest.fixture
def windows_names(monkeypatch):
    real = files.name_problem
    monkeypatch.setattr(files, "name_problem", lambda leaf, windows=None: real(leaf, True))


def test_opening_a_file_windows_cannot_create_says_why(tmp_path, windows_names):
    h = EditorHarness(tmp_path)
    h.command('GOTO FILE "a<b.PAS"')
    assert "%LSE-E-OPENIN" in h.message and "Windows does not allow <" in h.message
    assert h.buffer.name == "MAIN"


def test_saving_under_a_bad_name_keeps_the_buffer(tmp_path, windows_names):
    h = EditorHarness(tmp_path)
    h.open("GOOD.PAS")
    h.type("x")
    h.command('WRITE FILE "CON.PAS"')
    assert "%LSE-E-BADNAME, cannot write CON.PAS: CON is a device name" in \
        " ".join(h.message.split())
    assert h.buffer.name == "GOOD.PAS" and h.buffer.modified
    h.press("C-s")
    assert "written to file GOOD.PAS;1" in h.message


def test_a_failed_write_is_a_message_not_a_crash(tmp_path, monkeypatch):
    h = EditorHarness(tmp_path)
    h.open("GOOD.PAS")
    h.type("x")

    def full(base, lines):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(files, "write_new_version", full)
    h.command("WRITE FILE OTHER.PAS")
    assert "%LSE-E-WRITEERR, cannot write OTHER.PAS: No space left on device" in h.message
    assert h.buffer.name == "GOOD.PAS" and h.buffer.modified
    h.press("F7")
    assert "WRITEERR" in h.message
    assert not any(name == "compile_file" for name, _ in h.api.calls)
    h.press("C-q")
    h.press("y")
    assert not h.editor.quit_requested  # it could not save, so it does not quit


def test_existing_files_keep_their_spelling(tmp_path):
    (tmp_path / "GUESS.PAS").write_text("x\n")
    (tmp_path / "Notes.txt").write_text("x\n")
    assert files.resolve_name(str(tmp_path), "guess", ".PAS") == str(tmp_path / "GUESS.PAS")
    assert files.resolve_name(str(tmp_path), "guess.pas;2") == str(tmp_path / "GUESS.PAS") + ";2"
    assert files.resolve_name(str(tmp_path), "NOTES.TXT") == str(tmp_path / "Notes.txt")
    assert files.resolve_name(str(tmp_path), "new", ".PAS") == str(tmp_path / "new.PAS")
    h = EditorHarness(tmp_path)
    h.open("guess")
    assert h.buffer.name == "GUESS.PAS"
    h.type("y").press("C-s")
    assert sorted(f for f in os.listdir(tmp_path) if f.upper().startswith("GUESS")) == \
        ["GUESS.PAS", "GUESS.PAS;1", "GUESS.PAS;2"]

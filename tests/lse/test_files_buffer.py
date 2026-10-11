import os

from lse import files
from lse.buffer import Buffer


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


def test_split_version():
    assert files.split_version("HELLO.PAS;3") == ("HELLO.PAS", 3)
    assert files.split_version("HELLO.PAS") == ("HELLO.PAS", None)
    assert files.split_version("HELLO.PAS;") == ("HELLO.PAS", 0)
    assert files.split_version("HELLO.PAS;-1") == ("HELLO.PAS", -1)


def test_new_file_versions_count_up(tmp_path):
    base = str(tmp_path / "HELLO.PAS")
    assert files.write_new_version(base, ["one"]) == 1
    assert files.write_new_version(base, ["two"]) == 2
    assert read(base + ";1") == "one\n"
    assert read(base + ";2") == "two\n"
    assert read(base) == "two\n"
    assert files.list_versions(base) == [1, 2]


def test_existing_plain_file_is_kept_as_version_1(tmp_path):
    base = str(tmp_path / "OLD.PAS")
    write(base, "original\n")
    assert files.write_new_version(base, ["edited"]) == 2
    assert read(base + ";1") == "original\n"
    assert read(base + ";2") == "edited\n"


def test_load_variants(tmp_path):
    base = str(tmp_path / "A.PAS")
    assert files.load(base) == (base, None, None)
    files.write_new_version(base, ["v1"])
    files.write_new_version(base, ["v2", "line"])
    assert files.load(base) == (base, ["v2", "line"], 2)
    assert files.load(base + ";1") == (base, ["v1"], 1)
    assert files.load(base + ";0")[2] == 2
    assert files.load(base + ";-1")[2] == 1
    os.unlink(base)
    assert files.load(base) == (base, ["v2", "line"], 2)


def test_read_handles_crlf_and_tabs(tmp_path):
    p = tmp_path / "T.PAS"
    p.write_bytes(b"a\r\n\tb\r\n")
    assert files.read_lines(str(p)) == ["a", "        b"]


def test_resolve_name_is_forgiving(tmp_path):
    write(tmp_path / "GUESS.PAS", "x\n")
    d = str(tmp_path)
    assert files.resolve_name(d, "guess.pas") == str(tmp_path / "GUESS.PAS")
    assert files.resolve_name(d, "guess", ".PAS") == str(tmp_path / "GUESS.PAS")
    assert files.resolve_name(d, "NEW", ".PAS") == str(tmp_path / "NEW.PAS")
    assert files.resolve_name(d, "GUESS.PAS;1") == str(tmp_path / "GUESS.PAS") + ";1"


def test_purge_keeps_newest(tmp_path):
    base = str(tmp_path / "P.PAS")
    for i in range(4):
        files.write_new_version(base, [str(i)])
    removed = files.purge(base, keep=2)
    assert len(removed) == 2
    assert files.list_versions(base) == [3, 4]


def test_undo_redo_and_modified():
    b = Buffer("X", ["abc"])
    assert not b.modified
    b.insert(0, 3, "d")
    assert b.lines == ["abcd"] and b.modified
    assert b.undo()
    assert b.lines == ["abc"] and not b.modified
    assert b.redo()
    assert b.lines == ["abcd"]
    assert not b.redo()


def test_grouped_changes_undo_together():
    b = Buffer("X", ["x"])
    with b.change():
        b.insert(0, 1, "\nsecond")
        b.replace_line(0, "first")
    assert b.lines == ["first", "second"]
    b.undo()
    assert b.lines == ["x"]


def test_typing_groups_merge_into_one_undo_step():
    b = Buffer("X", [""])
    for i, ch in enumerate("word"):
        with b.change(group=("type", 0, i), next_group=("type", 0, i + 1)):
            b.insert(0, i, ch)
    assert b.lines == ["word"]
    assert len(b.undo_stack) == 1
    b.undo()
    assert b.lines == [""]


def test_save_clears_modified_and_tracks_version(tmp_path):
    b = Buffer("S.PAS", ["one"], path=str(tmp_path / "S.PAS"))
    b.insert(0, 3, "!")
    assert b.save() == 1
    assert not b.modified and b.display_name == "S.PAS;1"
    b.undo()
    assert b.modified
    b.redo()
    assert not b.modified


def test_read_only_buffer_refuses_edits():
    import pytest
    from lse.buffer import ReadOnlyError
    b = Buffer("$R", ["x"], read_only=True)
    with pytest.raises(ReadOnlyError):
        b.insert(0, 0, "y")

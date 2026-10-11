import curses

import pytest

from lse.keys import KeyDecoder, decode_sequence, describe_key, normalize_key, parse_keys
from lse.screen import translate_key


@pytest.mark.parametrize("name,expected", [
    ("C-s", "C-s"), ("Ctrl-S", "C-s"), ("ctrl+s", "C-s"), ("^Q", "C-q"),
    ("Shift-Tab", "S-Tab"), ("S-Tab", "S-Tab"), ("backtab", "S-Tab"),
    ("Ctrl-Delete", "C-Delete"), ("Shift-F8", "S-F8"), ("f5", "F5"),
    ("PgUp", "PageUp"), ("Return", "Enter"), ("esc", "Esc"), ("x", "x"), ("lt", "<"),
])
def test_normalize_key(name, expected):
    assert normalize_key(name) == expected


def test_normalize_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_key("Hyper-Q")


def test_parse_keys_mixes_text_and_names():
    assert parse_keys("IF<Tab>x<lt>1<C-s>") == ["I", "F", "Tab", "x", "<", "1", "C-s"]
    assert parse_keys("a\nb") == ["a", "Enter", "b"]
    assert parse_keys("a < b") == ["a", " ", "<", " ", "b"]


def test_describe_key():
    assert describe_key("C-s") == "Ctrl-S"
    assert describe_key("S-F8") == "Shift-F8"
    assert describe_key("C-Delete") == "Ctrl-Delete"
    assert describe_key(" ") == "Space"


def feed_all(decoder, keys):
    out = []
    for k in keys:
        out += decoder.feed(k)
    return out


@pytest.mark.parametrize("digit,fkey", [("1", "F1"), ("5", "F5"), ("8", "F8"), ("0", "F10")])
def test_esc_digit_is_function_key(digit, fkey):
    d = KeyDecoder()
    assert d.feed("Esc") == []
    assert d.waiting
    assert d.feed(digit) == [fkey]
    assert not d.waiting


def test_lone_esc_released_by_flush():
    d = KeyDecoder()
    assert d.feed("Esc") == []
    assert d.flush() == ["Esc"]
    assert d.flush() == []


def test_esc_then_letter_gives_both():
    assert feed_all(KeyDecoder(), ["Esc", "x"]) == ["Esc", "x"]


def test_double_esc_is_immediate():
    assert feed_all(KeyDecoder(), ["Esc", "Esc"]) == ["Esc", "Esc"]


@pytest.mark.parametrize("seq,key", [
    ("[3;5~", "C-Delete"), ("[1;5C", "C-Right"), ("[Z", "S-Tab"), ("OP", "F1"),
    ("[15~", "F5"), ("[19;2~", "S-F8"), ("[A", "Up"), ("[[A", "F1"), ("[6~", "PageDown"),
])
def test_escape_sequences(seq, key):
    assert decode_sequence(seq) == key
    assert feed_all(KeyDecoder(), ["Esc", *seq]) == [key]


def test_unknown_sequence_is_reported_not_typed():
    out = feed_all(KeyDecoder(), ["Esc", "[", "9", "9", "~"])
    assert out == ["Unknown:ESC[99~"]


def test_slow_bracket_after_esc_is_typed():
    d = KeyDecoder()
    d.feed("Esc")
    assert d.feed("[", elapsed=0.5) == ["Esc", "["]


def test_translate_curses_keys():
    assert translate_key(curses.KEY_F0 + 5) == "F5"
    assert translate_key(curses.KEY_F0 + 20) == "S-F8"
    assert translate_key(curses.KEY_BTAB) == "S-Tab"
    assert translate_key(curses.KEY_DC) == "Delete"
    assert translate_key("\x13") == "C-s"   # Ctrl-S arrives in raw mode
    assert translate_key("\x11") == "C-q"
    assert translate_key("\t") == "Tab"
    assert translate_key("\r") == "Enter"
    assert translate_key("\x7f") == "Backspace"
    assert translate_key("\x1b") == "Esc"
    assert translate_key("a") == "a"
    assert translate_key(4242, keyname=lambda c: b"kDC5") == "C-Delete"
    assert translate_key(4243, keyname=lambda c: b"kWHAT") is None

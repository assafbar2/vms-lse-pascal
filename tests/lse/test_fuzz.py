"""Random key mashing must never crash the editor or leave it unusable."""

import random

import pytest
from lse_helpers import HELLO

from lse.keymap import MODERN_PROFILE
from lse.testing import EditorHarness

KEYS = sorted(set(MODERN_PROFILE) - {"C-q"}) + list("abcXYZ 0123;:=()'%{}[].,<>") + \
    ["F2", "F4", "F12", "S-F8", "C-x", "C-v"]


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("size", [(24, 80), (10, 30)])
def test_random_keys_never_crash(tmp_path, seed, size):
    rng = random.Random(seed)
    h = EditorHarness(tmp_path, size=size, files={"HELLO.PAS": HELLO, "W.TXT": "text\n"},
                      program_input="5\n")
    h.open("NEW.PAS")
    for i in range(1500):
        key = rng.choice(KEYS)
        h.editor.feed_key(key)
        if i % 50 == 0:
            h.editor.flush_keys()
            scr = h.screen
            assert scr.height == size[0]
        if rng.random() < 0.01:
            h.editor.execute(rng.choice(["GOTO FILE HELLO.PAS", "TWO WINDOWS", "ONE WINDOW",
                                         "REVIEW", "GOTO BUFFER $OUTPUT", "BUILD"]))
    h.editor.flush_keys()
    while h.editor.overlays:
        h.press("Esc")
    h.command("GOTO FILE FINAL.TXT")
    h.type("ok").press("C-s")
    assert h.file("FINAL.TXT;1") == "ok\n"

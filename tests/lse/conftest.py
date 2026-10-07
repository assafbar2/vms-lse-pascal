import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lse.testing import EditorHarness  # noqa: E402

HELLO = """PROGRAM Hello(INPUT, OUTPUT);
BEGIN
  WRITELN('Hello, world')
END.
"""


@pytest.fixture
def h(tmp_path):
    """A harness on an empty directory (24x80 screen, fake toolchain)."""
    return EditorHarness(tmp_path)


@pytest.fixture
def hello(tmp_path):
    """A harness with HELLO.PAS (no versions yet) already open."""
    harness = EditorHarness(tmp_path, files={"HELLO.PAS": HELLO})
    harness.open("HELLO.PAS")
    return harness


def new_program(h, name="Hello"):
    """Open NEW.PAS and expand PROGRAM with a name; cursor on %[declarations]%..."""
    h.open("NEW.PAS")
    h.feed(f"<Tab><Enter>{name}<Tab>")
    return h

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for path in (ROOT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

from lse.testing import EditorHarness  # noqa: E402
from lse_helpers import HELLO  # noqa: E402


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

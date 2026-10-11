"""Per-user settings that outlive one session: ``~/.lse/state``.

For now it only remembers whether the tutorial has been finished, which
decides what ``lse`` with no file name does (tutorial or welcome screen).
``LSE_STATE_DIR`` moves the directory (tests use a temporary one).

The file is plain ``name = value`` lines, so it is easy to read or delete.
"""

from __future__ import annotations

import os

HEADER = "! LSE settings. Delete this file to start over (the tutorial will run again).\n"


def default_dir() -> str:
    return os.environ.get("LSE_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".lse")


class UserState:
    def __init__(self, directory: str | None = None) -> None:
        self.dir = directory or default_dir()
        self.path = os.path.join(self.dir, "state")
        self._values: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._values is None:
            values: dict[str, str] = {}
            try:
                with open(self.path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("!") or "=" not in line:
                            continue
                        name, _, value = line.partition("=")
                        values[name.strip().lower()] = value.strip()
            except OSError:
                pass
            self._values = values
        return self._values

    def get(self, name: str, default: str = "") -> str:
        return self._load().get(name.lower(), default)

    def set(self, name: str, value: str) -> None:
        values = self._load()
        values[name.lower()] = value
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(HEADER)
                for k in sorted(values):
                    f.write(f"{k} = {values[k]}\n")
            os.replace(tmp, self.path)
        except OSError:
            pass  # a read-only home directory must not stop the editor

    @property
    def tutorial_finished(self) -> bool:
        return self.get("tutorial_finished").lower() in ("yes", "true", "1")

    def mark_tutorial_finished(self) -> None:
        if not self.tutorial_finished:
            self.set("tutorial_finished", "yes")

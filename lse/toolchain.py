"""Thin adapter between the editor and the Pascal toolchain (``pascal.api``).

The editor never imports the compiler, linker or VM directly; it goes
through ``Toolchain``, which forwards to the module that implements the
contract in ``pascal/api.py``:

* ``parse_source(text, filename) -> ParseResult``
* ``compile_file(path, *, list_file) -> CompileResult``
* ``link(obj_paths, *, output, map_file) -> LinkResult``
* ``run_image(exe_path, *, input_text, stdin, stdout, seed) -> RunResult``
* ``get_message(facility, ident)`` / ``all_messages()``

Tests pass a fake module with the same functions (see
``lse.testing.FakePascalApi``).
"""

from __future__ import annotations

import importlib
from typing import Any


class ToolchainUnavailable(Exception):
    """``pascal.api`` could not be imported."""


class Toolchain:
    def __init__(self, api: Any = None, module: str = "pascal.api") -> None:
        self._api = api
        self._module = module

    @property
    def api(self) -> Any:
        if self._api is None:
            try:
                self._api = importlib.import_module(self._module)
            except ImportError as e:
                raise ToolchainUnavailable(
                    f"the Pascal toolchain ({self._module}) is not installed: {e}") from e
        return self._api

    @property
    def available(self) -> bool:
        try:
            self.api
        except ToolchainUnavailable:
            return False
        return True

    def parse(self, text: str, filename: str = "<buffer>") -> Any:
        return self.api.parse_source(text, filename)

    def compile(self, path: str, *, list_file: bool = False) -> Any:
        return self.api.compile_file(path, list_file=list_file)

    def link(self, obj_paths: list[str], *, output: str | None = None, map_file: bool = True) -> Any:
        return self.api.link([str(p) for p in obj_paths], output=output, map_file=map_file)

    def run(self, exe_path: str, *, input_text: str | None = None, stdin: Any = None,
            stdout: Any = None, seed: int | None = None) -> Any:
        return self.api.run_image(exe_path, input_text=input_text, stdin=stdin,
                                  stdout=stdout, seed=seed)

    def message(self, facility: str, ident: str) -> Any:
        return self.api.get_message(facility, ident)

    def all_messages(self) -> list[Any]:
        return list(self.api.all_messages())


def format_diagnostic(diag: Any, explain: bool = True) -> str:
    """VMS-style text for a diagnostic, with explanation and hint if wanted."""
    fmt = getattr(diag, "format", None)
    if callable(fmt):
        return fmt(explain=explain)
    sev = getattr(diag, "severity", "E")
    fac = getattr(diag, "facility", "PASCAL")
    ident = getattr(diag, "ident", "ERROR")
    return f"%{fac}-{sev}-{ident}, {getattr(diag, 'text', diag)}"

"""The toolchain API used by the LSE editor (and by the command-line tools).

Everything the editor needs -- parsing a buffer, COMPILE, LINK, RUN and
the message catalog -- goes through the functions in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import astnodes
from .compiler import check_source, compile_path, read_dia as _read_dia_text
from .files import find_file
from .linker import link_files
from .messages import Diagnostic, MessageInfo, diag
from .messages import all_messages as _all_messages
from .messages import get_message as _get_message
from .objfile import ObjFormatError, read_image
from .rtl import Runtime
from .vm import VM

__all__ = [
    "Diagnostic", "MessageInfo", "CompileResult", "ParseResult", "LinkResult", "RunResult",
    "parse_source", "compile_file", "link", "run_image", "get_message", "all_messages",
    "read_dia", "parse_statement", "find_statements", "astnodes", "DEFAULT_MAX_STEPS",
]

# Instruction limit for non-interactive runs, so a program stuck in a loop
# cannot hang a test or the tutor. Interactive runs have no limit (Ctrl-C stops them).
DEFAULT_MAX_STEPS = 20_000_000
_DEFAULT = object()


@dataclass
class CompileResult:
    ok: bool
    diagnostics: list[Diagnostic]
    obj_path: str | None
    dia_path: str | None
    lis_path: str | None = None


@dataclass
class ParseResult:
    ast: astnodes.Program | None
    diagnostics: list[Diagnostic]


@dataclass
class LinkResult:
    ok: bool
    diagnostics: list[Diagnostic]
    exe_path: str | None
    map_path: str | None


@dataclass
class RunResult:
    exit_status: int
    output: str
    error: Diagnostic | None = None
    traceback: list[str] = field(default_factory=list)
    transcript: str = ""


def parse_source(text: str, filename: str = "<buffer>", *, semantic: bool = True) -> ParseResult:
    """Parse (and type-check) a buffer without writing any files.

    The AST is returned even when there are errors such as leftover
    placeholders; it is None only when the text is not a PROGRAM or MODULE at all.
    """
    out = check_source(text, filename, semantic=semantic)
    return ParseResult(out.ast, out.diagnostics)


def parse_statement(text: str) -> astnodes.Statement | None:
    """Parse one statement (placeholders allowed, as wildcards); None if it is not a single valid statement."""
    src = f"PROGRAM Pattern;\nBEGIN\n{text}\nEND.\n"
    out = check_source(src, "<pattern>", semantic=False)
    if out.ast is None or any(d.is_error and d.ident != "PLACEHOLDER" for d in out.diagnostics):
        return None
    stmts = [s for s in out.ast.block.body.stmts if s.kind != "empty"]
    return stmts[0] if len(stmts) == 1 else None


def find_statements(ast: astnodes.Program | None, pattern: str) -> list[astnodes.Statement]:
    """Statements anywhere in ``ast`` that match ``pattern`` (see :func:`astnodes.matches`)."""
    pat = parse_statement(pattern)
    if ast is None or pat is None:
        return []
    return [s for s in ast.statements() if astnodes.matches(pat, s)]


def compile_file(path, *, list_file: bool = False) -> CompileResult:
    """COMPILE: writes NAME.OBJ (if there are no errors) and NAME.DIA next to the source."""
    r = compile_path(str(path), list_file=list_file)
    return CompileResult(r.ok, r.diagnostics, r.obj_path, r.dia_path, r.lis_path)


def link(obj_paths, *, output: str | None = None, map_file: bool = True) -> LinkResult:
    """LINK: object files (and PASRTL.OLB) to NAME.EXE and NAME.MAP."""
    if isinstance(obj_paths, (str, Path)):
        obj_paths = [str(obj_paths)]
    r = link_files([str(p) for p in obj_paths], output=output, map_file=map_file)
    return LinkResult(r.ok, r.diagnostics, r.exe_path, r.map_path)


def run_image(exe_path, *, input_text: str | None = None, stdin=None, stdout=None,
              seed: int | None = None, explain: bool = True, max_steps=_DEFAULT) -> RunResult:
    """RUN an image on the p-code machine.

    * ``input_text``: read input from this string and capture the output.
    * ``stdin``/``stdout``: run interactively on these streams; output is also captured.
    * ``seed``: makes RANDOMIZE / RANDOM repeatable (RUN/SEED=n).
    * ``explain``: include explanations and hints in run-time messages.
    * ``max_steps``: instruction limit (default: DEFAULT_MAX_STEPS without ``stdin``, none with it).
    """
    if max_steps is _DEFAULT:
        max_steps = None if stdin is not None else DEFAULT_MAX_STEPS
    rt = Runtime(input_text=input_text, stdin=stdin, stdout=stdout, seed=seed, explain=explain)
    path = find_file(str(exe_path), ".EXE")
    if path is None:
        stem = Path(str(exe_path)).name.rsplit(".", 1)[0]
        return _run_failure(rt, diag("PAS", "NOIMAGE", file=str(exe_path), stem=stem))
    try:
        image = read_image(path.read_text(errors="replace"))
        vm = VM(image, rt, max_steps)
    except (ObjFormatError, OSError, ValueError) as exc:
        return _run_failure(rt, diag("PAS", "BADIMAGE", file=str(path), reason=str(exc)))
    result = vm.run()
    rt.flush()
    return RunResult(result.exit_status, "".join(rt.output), result.error, result.traceback,
                     "".join(rt.transcript))


def _run_failure(rt: Runtime, d: Diagnostic) -> RunResult:
    rt.write_message(d.format(explain=rt.explain))
    return RunResult(1, "".join(rt.output), d, [], "".join(rt.transcript))


def get_message(facility: str, ident: str) -> MessageInfo:
    return _get_message(facility, ident)


def all_messages() -> list[MessageInfo]:
    return _all_messages()


def read_dia(path) -> list[Diagnostic]:
    """Read the diagnostics written by an earlier COMPILE (NAME.DIA)."""
    p = find_file(str(path), ".DIA")
    if p is None:
        return []
    return _read_dia_text(p.read_text(errors="replace"))

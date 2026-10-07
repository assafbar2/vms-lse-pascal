"""The compiler driver: source text to object module, diagnostics file and listing.

``PASCAL HELLO`` reads HELLO.PAS and writes

* HELLO.OBJ  the object module (only when there are no errors)
* HELLO.DIA  the diagnostics, in the format LSE's REVIEW command reads
* HELLO.LIS  a listing with line numbers and messages (with /LIST)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import VERSION
from . import astnodes as A
from .codegen import generate
from .files import find_file, output_name
from .lexer import Token
from .linker import vms_date
from .messages import Diagnostic, diag, has_errors
from .objfile import ObjectModule, write_object
from .parser import parse
from .semantic import UnitInfo, analyze


@dataclass
class CompileOutcome:
    ast: A.Program | None
    diagnostics: list[Diagnostic]
    obj: ObjectModule | None = None
    info: UnitInfo | None = None
    tokens: list[Token] = field(default_factory=list)


def _sort(diags: list[Diagnostic]) -> list[Diagnostic]:
    return sorted(diags, key=lambda d: (d.line or 0, d.column or 0))


def check_source(text: str, filename: str = "<buffer>", semantic: bool = True) -> CompileOutcome:
    """Parse (and by default type-check) without generating code."""
    ast, diags, tokens = parse(text, filename)
    info = None
    if ast is not None and semantic:
        info, sdiags = analyze(ast, filename)
        diags = _sort(diags + sdiags)
    return CompileOutcome(ast, diags, None, info, tokens)


def compile_source(text: str, filename: str = "<buffer>", created: str | None = None) -> CompileOutcome:
    out = check_source(text, filename)
    if out.ast is not None and out.info is not None and not has_errors(out.diagnostics):
        out.obj = generate(out.ast, out.info, filename, created or vms_date())
    return out


@dataclass
class FileCompileOutcome:
    ok: bool
    diagnostics: list[Diagnostic]
    obj_path: str | None = None
    dia_path: str | None = None
    lis_path: str | None = None
    outcome: CompileOutcome | None = None
    source_path: str | None = None


def compile_path(path: str, *, list_file: bool = False) -> FileCompileOutcome:
    src = find_file(str(path), ".PAS")
    if src is None:
        d = diag("PASCAL", "OPENIN", file=str(path))
        return FileCompileOutcome(False, [d])
    try:
        text = src.read_text(errors="replace")
    except OSError:
        return FileCompileOutcome(False, [diag("PASCAL", "OPENIN", file=str(src))])
    created = vms_date()
    out = compile_source(text, str(src), created)
    obj_path = output_name(src, ".OBJ")
    dia_path = output_name(src, ".DIA")
    lis_path = output_name(src, ".LIS") if list_file else None
    diags = list(out.diagnostics)
    try:
        dia_path.write_text(write_dia(diags, str(src), created))
        if out.obj is not None:
            obj_path.write_text(write_object(out.obj))
        elif obj_path.exists():
            obj_path.unlink()
        if lis_path is not None:
            lis_path.write_text(write_listing(text, str(src), out, created))
    except OSError as exc:
        bad = getattr(exc, "filename", None) or str(obj_path)
        diags.append(diag("PASCAL", "OPENOUT", file=str(bad)))
    ok = out.obj is not None and not has_errors(diags)
    return FileCompileOutcome(ok, diags, str(obj_path) if ok else None, str(dia_path),
                              str(lis_path) if lis_path else None, out, str(src))


# ----------------------------------------------------------------------
# Diagnostics file (.DIA)
# ----------------------------------------------------------------------

def _dq(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def write_dia(diags: list[Diagnostic], source: str, created: str = "") -> str:
    errors = sum(1 for d in diags if d.severity in ("E", "F"))
    warnings = sum(1 for d in diags if d.severity == "W")
    L = [f"!  VMS-LSE Pascal {VERSION} diagnostics for {source}",
         f"!  Compiled {created};  {errors} error(s), {warnings} warning(s)",
         "start diagnostics"]
    for d in diags:
        L.append("  start modification")
        region = f"    region/file/primary {_dq(d.file or source)}"
        if d.line is not None:
            region += f" /line={d.line}"
            if d.column is not None:
                end = max(d.column, (d.end_column or d.column + 1) - 1)
                region += f"/column_range=({d.column},{end})"
        L.append(region)
        L.append(f"    message {_dq(f'{d.code}, {d.text}')}")
        L.append(f"    explanation {_dq(d.explanation)}")
        L.append(f"    hint {_dq(d.hint)}")
        L.append("  end modification")
    L.append("end diagnostics")
    return "\n".join(L) + "\n"


_DQ = r'"((?:[^"]|"")*)"'
_REGION_RE = re.compile(r'region/file/primary\s+' + _DQ + r'(?:\s*/line=(\d+))?(?:/column_range=\((\d+),(\d+)\))?')
_FIELD_RE = re.compile(r'(message|explanation|hint)\s+' + _DQ)
_MSG_RE = re.compile(r"%(\w+)-([SIWEF])-(\w+), (.*)", re.S)


def read_dia(text: str) -> list[Diagnostic]:
    """Read a .DIA file back into Diagnostic objects."""
    out = []
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line == "start modification":
            cur = {}
        elif line == "end modification" and cur is not None:
            m = _MSG_RE.match(cur.get("message", ""))
            if m:
                out.append(Diagnostic(
                    file=cur.get("file"), line=cur.get("line"), column=cur.get("column"),
                    severity=m.group(2), facility=m.group(1), ident=m.group(3), text=m.group(4),
                    explanation=cur.get("explanation", ""), hint=cur.get("hint", ""),
                    end_column=cur.get("end_column")))
            cur = None
        elif cur is not None:
            r = _REGION_RE.match(line)
            if r:
                cur["file"] = r.group(1).replace('""', '"')
                if r.group(2):
                    cur["line"] = int(r.group(2))
                if r.group(3):
                    cur["column"] = int(r.group(3))
                    cur["end_column"] = int(r.group(4)) + 1
                continue
            f = _FIELD_RE.match(line)
            if f:
                cur[f.group(1)] = f.group(2).replace('""', '"')
    return out


# ----------------------------------------------------------------------
# Listing file (.LIS)
# ----------------------------------------------------------------------

_OPEN = {"BEGIN", "REPEAT", "CASE", "RECORD"}
_CLOSE = {"END", "UNTIL"}


def nesting_levels(tokens: list[Token], line_count: int) -> list[int]:
    """BEGIN/END nesting level at the start of each source line (index 0 = line 1)."""
    levels = [0] * (line_count + 1)
    depth = 0
    ti = 0
    for ln in range(1, line_count + 1):
        start_depth = depth
        min_depth = depth
        while ti < len(tokens) and tokens[ti].line == ln:
            k = tokens[ti].kind
            if k in _OPEN:
                depth += 1
            elif k in _CLOSE:
                depth = max(0, depth - 1)
                min_depth = min(min_depth, depth)
            ti += 1
        levels[ln - 1] = min(start_depth, min_depth)
    return levels


def write_listing(text: str, source: str, out: CompileOutcome, created: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    unit = out.ast.name.upper() if out.ast else Path(source).stem.upper()
    levels = nesting_levels(out.tokens, len(lines))
    by_line: dict[int, list[Diagnostic]] = {}
    for d in out.diagnostics:
        by_line.setdefault(d.line or 0, []).append(d)
    L = [f"{unit:<32}{created:<24}VMS-LSE Pascal {VERSION}",
         f"{'Source Listing':<32}{source}", "",
         " Line Lev  Source", " ---- ---  ------"]
    for d in by_line.get(0, []):
        L.append(d.format())
    for i, src_line in enumerate(lines, 1):
        L.append(f"{i:5d} {levels[i - 1]:3d}  {src_line}")
        ds = by_line.get(i, [])
        if ds:
            marks = [" "] * (max((d.column or 1) for d in ds) + 1)
            for n, d in enumerate(ds, 1):
                col = (d.column or 1) - 1
                if marks[col] == " ":
                    marks[col] = str(n % 10)
            L.append(" " * 11 + "".join(marks).rstrip())
            for n, d in enumerate(ds, 1):
                L.append(f"({n % 10}) " + d.format().replace("\n", "\n    "))
    errors = sum(1 for d in out.diagnostics if d.severity in ("E", "F"))
    warnings = sum(1 for d in out.diagnostics if d.severity == "W")
    L += ["", "COMPILATION STATISTICS", "",
          f"  Source lines:      {len(lines)}",
          f"  Errors:            {errors}",
          f"  Warnings:          {warnings}"]
    if out.obj is not None:
        L += [f"  Code size:         {len(out.obj.code)} p-code instructions",
              f"  Static data:       {out.obj.data_size} cells",
              f"  Routines:          {', '.join(r.name for r in out.obj.routines) or '(none)'}",
              f"  External symbols:  {', '.join(e.name for e in out.obj.externals) or '(none)'}"]
    else:
        L.append("  No object module was produced because of the errors above.")
    L += ["", "COMMAND QUALIFIERS", "", f"  PASCAL /LIST {source}", ""]
    return "\n".join(L)

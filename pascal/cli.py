"""DCL-style command-line entry points.

    $ pascal HELLO            compile HELLO.PAS -> HELLO.OBJ, HELLO.DIA
    $ pascal /LIST HELLO      ... and a listing, HELLO.LIS
    $ link HELLO, MATHLIB     link -> HELLO.EXE, HELLO.MAP
    $ run HELLO               run HELLO.EXE
    $ run /SEED=42 GUESS      repeatable random numbers

Qualifiers can be written VMS style (/LIST, /SEED=42, also glued to the
file name as HELLO/LIST) or Unix style (--list, --seed 42). The same
commands are available as ``python -m pascal PASCAL|LINK|RUN ...``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import VERSION
from .api import compile_file, link, run_image
from .messages import Diagnostic

PASCAL_QUALS = {"LIST": False, "NOLIST": False, "EXPLAIN": False, "NOEXPLAIN": False}
LINK_QUALS = {"EXECUTABLE": True, "MAP": False, "NOMAP": False, "EXPLAIN": False, "NOEXPLAIN": False}
RUN_QUALS = {"SEED": True, "INPUT": True, "EXPLAIN": False, "NOEXPLAIN": False, "MAX_STEPS": True}

USAGE = {
    "PASCAL": "usage: pascal [/LIST] [/NOEXPLAIN] file[.PAS] ...\n"
              "Compile Pascal source files into object modules (.OBJ) and diagnostics (.DIA).",
    "LINK": "usage: link [/EXECUTABLE=name] [/NOMAP] [/NOEXPLAIN] file[.OBJ] [, file ...]\n"
            "Link object modules and the run-time library PASRTL.OLB into an image (.EXE) and a map (.MAP).",
    "RUN": "usage: run [/SEED=n] [/INPUT=file] [/NOEXPLAIN] file[.EXE]\n"
           "Run an image on the p-code machine.",
}


class UsageError(Exception):
    pass


def _match(word: str, quals: dict) -> str | None:
    word = word.upper().replace("-", "_")
    if word in quals:
        return word
    hits = [q for q in quals if len(word) >= 3 and q.startswith(word)]
    return hits[0] if len(hits) == 1 else None


def parse_args(argv: list[str], quals: dict) -> tuple[list[str], dict[str, str | bool]]:
    files: list[str] = []
    opts: dict[str, str | bool] = {}
    i = 0

    def take(item: str, from_next: bool):
        nonlocal i
        name, eq, value = item.partition("=")
        q = _match(name, quals)
        if q is None:
            raise UsageError(f"unknown qualifier {item!r}")
        if quals[q]:
            if not eq:
                if not from_next or i + 1 >= len(argv):
                    raise UsageError(f"qualifier /{q} needs a value, e.g. /{q}=value")
                i += 1
                value = argv[i]
            opts[q] = value
        else:
            opts[q] = True

    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help", "/HELP", "/help"):
            raise UsageError("")
        if arg.startswith("--"):
            take(arg[2:], True)
        elif arg.startswith("/") and _match(arg[1:].partition("=")[0], quals) and not os.path.exists(arg):
            take(arg[1:], False)
        else:
            parts = arg.split("/")
            tail = []
            while len(parts) > 1 and _match(parts[-1].partition("=")[0], quals) and "." not in parts[-1].partition("=")[0]:
                tail.insert(0, parts.pop())
            if tail and not os.path.exists(arg):
                for t in tail:
                    take(t, False)
                arg = "/".join(parts)
            for name in arg.split(","):
                if name.strip():
                    files.append(name.strip())
        i += 1
    return files, opts


def _source_excerpt(d: Diagnostic) -> list[str]:
    if not d.file or not d.line:
        return []
    try:
        lines = Path(d.file).read_text(errors="replace").splitlines()
    except OSError:
        return []
    if not 1 <= d.line <= len(lines):
        return []
    raw = lines[d.line - 1]
    out = [f"{d.line:6d}  {raw.expandtabs(8)}"]
    if d.column:
        out.append(" " * (8 + len(raw[:d.column - 1].expandtabs(8))) + "^")
    return out


def print_diagnostics(diags: list[Diagnostic], explain: bool, excerpt: bool = True, stream=None):
    stream = stream or sys.stdout
    for d in diags:
        if excerpt:
            for ln in _source_excerpt(d):
                print(ln, file=stream)
        print(d.format(explain=explain, width=100), file=stream)


def _explain(opts) -> bool:
    return not opts.get("NOEXPLAIN", False)


def pascal_command(argv: list[str]) -> int:
    files, opts = parse_args(argv, PASCAL_QUALS)
    if not files:
        raise UsageError("no source file given")
    status = 0
    for f in files:
        r = compile_file(f, list_file=bool(opts.get("LIST")) and not opts.get("NOLIST"))
        print_diagnostics(r.diagnostics, _explain(opts))
        if not r.ok:
            status = 1
    return status


def link_command(argv: list[str]) -> int:
    files, opts = parse_args(argv, LINK_QUALS)
    if not files:
        raise UsageError("no object file given")
    r = link(files, output=opts.get("EXECUTABLE") or None, map_file=not opts.get("NOMAP"))
    print_diagnostics(r.diagnostics, _explain(opts))
    return 0 if r.ok else 1


def run_command(argv: list[str]) -> int:
    files, opts = parse_args(argv, RUN_QUALS)
    if len(files) != 1:
        raise UsageError("give exactly one image to run")
    seed = None
    if "SEED" in opts:
        try:
            seed = int(opts["SEED"])
        except ValueError:
            raise UsageError("/SEED needs a whole number, e.g. /SEED=42") from None
    kwargs = {}
    if "MAX_STEPS" in opts:
        kwargs["max_steps"] = int(opts["MAX_STEPS"])
    if "INPUT" in opts:
        text = Path(str(opts["INPUT"])).read_text()
        r = run_image(files[0], input_text=text, stdout=sys.stdout, seed=seed,
                      explain=_explain(opts), **kwargs)
    elif sys.stdin.isatty():
        r = run_image(files[0], stdin=sys.stdin, stdout=sys.stdout, seed=seed,
                      explain=_explain(opts), **kwargs)
    else:
        r = run_image(files[0], input_text=sys.stdin.read(), stdout=sys.stdout, seed=seed,
                      explain=_explain(opts), **kwargs)
    sys.stdout.flush()
    return r.exit_status


COMMANDS = {"PASCAL": pascal_command, "COMPILE": pascal_command, "LINK": link_command, "RUN": run_command}


def _entry(name: str, argv: list[str] | None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        return COMMANDS[name](argv)
    except UsageError as exc:
        key = "PASCAL" if name == "COMPILE" else name
        if str(exc):
            print(f"%DCL-W-USAGE, {exc}", file=sys.stderr)
        print(USAGE[key], file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n%DCL-W-INTERRUPT, interrupted by Ctrl-C", file=sys.stderr)
        return 130


def pascal_main(argv: list[str] | None = None) -> int:
    return _entry("PASCAL", argv)


def link_main(argv: list[str] | None = None) -> int:
    return _entry("LINK", argv)


def run_main(argv: list[str] | None = None) -> int:
    return _entry("RUN", argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command, *quals = argv[0].split("/") if argv else [""]
    if command.upper() not in COMMANDS:
        print(f"VMS-LSE Pascal {VERSION}\nusage: python -m pascal PASCAL|LINK|RUN [qualifiers] files",
              file=sys.stderr)
        return 2
    return _entry(command.upper(), ["/" + q for q in quals if q] + argv[1:])

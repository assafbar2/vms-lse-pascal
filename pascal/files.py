"""File-name helpers that behave a little like VMS: default extensions,
case-insensitive lookup, and ``;N`` version numbers (the highest wins)."""

from __future__ import annotations

import os
from pathlib import Path


def strip_version(name: str) -> str:
    base, sep, version = name.rpartition(";")
    return base if sep and version.isdigit() else name


def find_file(name: str, extension: str) -> Path | None:
    """Find ``name``, adding ``extension`` if it has none; ignores case and picks the highest ;version."""
    p = Path(name)
    has_ext = "." in strip_version(p.name)
    candidates = [p] if has_ext else [p.with_name(p.name + extension), p.with_name(p.name + extension.lower()), p]
    for c in candidates:
        if c.is_file():
            return c
    directory = p.parent
    want = {strip_version(c.name).upper() for c in candidates}
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return None
    best = None
    best_version = -1
    for entry in entries:
        base, sep, version = entry.rpartition(";")
        if not sep or not version.isdigit():
            base, version = entry, "0"
        if base.upper() in want and (directory / entry).is_file():
            v = int(version)
            if v > best_version:
                best, best_version = directory / entry, v
    return best


def output_name(path: Path, extension: str) -> Path:
    """HELLO.PAS -> HELLO.OBJ (hello.pas -> hello.obj), dropping any ;version."""
    path = Path(path)
    name = strip_version(path.name)
    stem, dot, ext_in = name.rpartition(".")
    if not dot:
        stem, ext_in = name, ""
    ext = extension.lower() if ext_in and ext_in.islower() else extension.upper()
    return path.with_name(stem + ext)

"""VMS-style versioned files.

Saving ``HELLO.PAS`` writes a new version ``HELLO.PAS;N`` (one higher than
the highest that exists) and also refreshes the plain ``HELLO.PAS``, which
always holds the newest text so that the compiler and other tools can
read it. If a plain file exists with no versions yet, it is kept as
``;1`` before the first new version is written, so nothing is lost.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile

_VERSION_RE = re.compile(r"^(?P<base>.*?);(?P<ver>-?\d*)$")


def split_version(path: str) -> tuple[str, int | None]:
    """``"HELLO.PAS;3"`` -> ``("HELLO.PAS", 3)``; no version -> ``None``.

    ``;0`` or a bare ``;`` means "the newest version" and yields ``0``;
    negative numbers count back from the newest (``;-1`` is the one before).
    """
    m = _VERSION_RE.match(path)
    if not m:
        return path, None
    ver = m.group("ver")
    return m.group("base"), int(ver) if ver not in ("", "-") else 0


def versioned_name(base: str, version: int) -> str:
    return f"{base};{version}"


def list_versions(base: str) -> list[int]:
    """All version numbers on disk for ``base`` (an absolute or relative path)."""
    directory, name = os.path.split(base)
    directory = directory or "."
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    prefix = name + ";"
    out = []
    for entry in entries:
        if entry.startswith(prefix):
            tail = entry[len(prefix):]
            if tail.isdigit():
                out.append(int(tail))
    return sorted(out)


def latest_version(base: str) -> int | None:
    versions = list_versions(base)
    return versions[-1] if versions else None


def resolve_name(directory: str, name: str, default_type: str | None = None) -> str:
    """Find an existing file for ``name`` the way a forgiving VMS user expects.

    Tries the exact name, then a case-insensitive match, then (when the
    name has no file type) the name with ``default_type`` added. An existing
    file comes back spelled as it is on disk, also on file systems that
    ignore case (Windows, macOS). Returns the path to use, which may not
    exist yet.
    """
    base, ver = split_version(name)
    path = base if os.path.isabs(base) else os.path.join(directory, base)
    suffix = "" if ver is None else f";{ver}"
    folder, leaf = os.path.split(path)
    candidates = [leaf]
    if default_type and "." not in leaf:
        candidates.append(leaf + default_type)
    try:
        entries = os.listdir(folder or ".")
    except OSError:
        entries = []
    exact: set[str] = set()
    by_case: dict[str, str] = {}
    for entry in entries:
        plain = split_version(entry)[0]
        exact.add(plain)
        by_case.setdefault(plain.lower(), plain)
    for cand in candidates:
        if cand in exact:
            return os.path.join(folder, cand) + suffix
        found = by_case.get(cand.lower())
        if found:
            return os.path.join(folder, found) + suffix
    if os.path.exists(path):
        return path + suffix
    if default_type and "." not in leaf:
        return path + default_type + suffix
    return path + suffix


_WINDOWS_BAD = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                     *(f"LPT{i}" for i in range(1, 10))}


def name_problem(leaf: str, windows: bool | None = None) -> str | None:
    """Why ``leaf`` cannot be a file name here, or None if it can.

    Windows forbids ``< > : " / \\ | ? *``, control characters, names that
    end in a dot or space, and device names such as CON or NUL (with any
    file type). Elsewhere only NUL and ``/`` are out.
    """
    if windows is None:
        windows = os.name == "nt"
    leaf = split_version(leaf)[0]
    if not leaf:
        return "the file name is empty"
    if not windows:
        return "a file name cannot contain NUL or /" if ("\0" in leaf or "/" in leaf) else None
    bad = sorted({c for c in leaf if c in _WINDOWS_BAD})
    if bad:
        shown = " ".join(repr(c)[1:-1] if c.isprintable() else f"\\x{ord(c):02x}" for c in bad)
        return f"Windows does not allow {shown} in a file name"
    if leaf.endswith((".", " ")):
        return "Windows does not allow a file name to end with a dot or a space"
    if leaf.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        return f"{leaf.split('.', 1)[0].upper()} is a device name on Windows, not a file"
    return None


def read_lines(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        data = f.read()
    data = data.replace("\r\n", "\n").replace("\r", "\n")
    if data.endswith("\n"):
        data = data[:-1]
    return [line.expandtabs(8) for line in data.split("\n")]


def load(path: str) -> tuple[str, list[str] | None, int | None]:
    """Load ``path`` (optionally with ``;N``).

    Returns ``(base, lines, version)``. ``lines`` is ``None`` for a new
    file. ``version`` is the version the text came from, if known.
    """
    base, ver = split_version(path)
    versions = list_versions(base)
    if ver is not None:
        if ver <= 0 and versions:
            idx = len(versions) - 1 + ver
            if idx < 0:
                raise FileNotFoundError(f"no such version: {path}")
            ver = versions[idx]
        target = versioned_name(base, ver)
        if not os.path.exists(target):
            raise FileNotFoundError(f"no such version: {target}")
        return base, read_lines(target), ver
    if os.path.exists(base):
        return base, read_lines(base), versions[-1] if versions else None
    if versions:
        return base, read_lines(versioned_name(base, versions[-1])), versions[-1]
    return base, None, None


def _atomic_write(path: str, data: str) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".lse-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_new_version(base: str, lines: list[str]) -> int:
    """Write ``lines`` as the next version of ``base``; return its number."""
    versions = list_versions(base)
    if not versions and os.path.exists(base):
        shutil.copy2(base, versioned_name(base, 1))
        versions = [1]
    version = (versions[-1] if versions else 0) + 1
    data = "".join(line + "\n" for line in lines)
    _atomic_write(versioned_name(base, version), data)
    _atomic_write(base, data)
    return version


def purge(base: str, keep: int = 1) -> list[str]:
    """Delete all but the newest ``keep`` versions; return the deleted names."""
    versions = list_versions(base)
    doomed = versions[:-keep] if keep > 0 else versions
    removed = []
    for v in doomed:
        name = versioned_name(base, v)
        try:
            os.unlink(name)
            removed.append(name)
        except OSError:
            pass
    return removed

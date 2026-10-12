"""Build the browser version of LSE into ``web/dist`` (the GitHub Pages site).

    cd web && npm ci && python3 build.py [--out DIR]

The site is static: ``index.html`` and the scripts from ``web/src``,
Pyodide, xterm.js and the VT323 font from ``node_modules``, and
``app.zip`` with the ``lse`` and ``pascal`` packages, ``lse_web.py`` and
the example programs. Every URL that can change carries a build id taken
from the content, so a new deploy never mixes old and new files.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
SRC = WEB / "src"
MODULES = WEB / "node_modules"

PAGES = ["index.html", "main.js", "keys.js", "worker.js", "sw.js", "style.css"]

VENDOR = {
    # Pyodide is MPL-2.0; its npm package has no LICENSE file to copy
    "pyodide": ("pyodide", ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm",
                            "python_stdlib.zip", "pyodide-lock.json", "package.json"]),
    "xterm": ("@xterm/xterm", ["lib/xterm.mjs", "css/xterm.css", "LICENSE"]),
    "xterm-fit": ("@xterm/addon-fit", ["lib/addon-fit.mjs", "LICENSE"]),
    "xterm-webgl": ("@xterm/addon-webgl", ["lib/addon-webgl.mjs", "LICENSE"]),
    "fonts": ("@fontsource/vt323", ["files/vt323-latin-400-normal.woff2", "LICENSE"]),
}
# where each vendored file lands under dist/vendor/
TARGET = {"xterm-fit": "xterm", "xterm-webgl": "xterm"}

ZIP_PACKAGES = ["lse", "pascal"]
ZIP_SKIP_DIRS = {"__pycache__"}


def tracked_files(paths: list[str]) -> list[Path]:
    """Files under ``paths`` that git knows about (falls back to all files)."""
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=ROOT, check=True,
                             capture_output=True).stdout.decode()
        files = [ROOT / p for p in out.split("\0") if p]
        if files:
            return sorted(f for f in files if f.is_file())
    except (OSError, subprocess.CalledProcessError):
        pass
    found: list[Path] = []
    for p in paths:
        base = ROOT / p
        found += [f for f in base.rglob("*") if f.is_file()
                  and not ZIP_SKIP_DIRS.intersection(f.relative_to(ROOT).parts)]
    return sorted(found)


def app_zip() -> bytes:
    """``lse/``, ``pascal/``, ``examples/`` and ``lse_web.py`` (fixed timestamps)."""
    entries: list[tuple[str, bytes]] = []
    for f in tracked_files(ZIP_PACKAGES + ["examples"]):
        entries.append((f.relative_to(ROOT).as_posix(), f.read_bytes()))
    entries.append(("lse_web.py", (SRC / "lse_web.py").read_bytes()))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


def vendor_files() -> list[tuple[str, Path]]:
    out = []
    for key, (package, names) in VENDOR.items():
        base = MODULES / package
        if not base.is_dir():
            sys.exit(f"build.py: {base} is missing; run `npm ci` in web/ first")
        folder = TARGET.get(key, key)
        for name in names:
            src = base / name
            if not src.is_file():
                sys.exit(f"build.py: {src} is missing")
            leaf = Path(name).name
            if leaf == "LICENSE":
                leaf = f"LICENSE.{key}" if folder != key else "LICENSE"
            out.append((f"vendor/{folder}/{leaf}", src))
    return out


def build(out: Path) -> str:
    vendor = vendor_files()
    zipped = app_zip()
    pages = {name: (SRC / name).read_text(encoding="utf-8") for name in PAGES}

    digest = hashlib.sha256(zipped)
    for name in PAGES:
        digest.update(pages[name].encode())
    for rel, src in vendor:
        digest.update(rel.encode())
        digest.update(hashlib.sha256(src.read_bytes()).digest())
    build_id = digest.hexdigest()[:12]

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, text in pages.items():
        (out / name).write_text(text.replace("__BUILD_ID__", build_id), encoding="utf-8")
    (out / "app.zip").write_bytes(zipped)
    for rel, src in vendor:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    (out / ".nojekyll").write_text("")
    return build_id


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=WEB / "dist", help="output folder (default web/dist)")
    args = p.parse_args(argv)
    build_id = build(args.out.resolve())
    size = sum(f.stat().st_size for f in args.out.rglob("*") if f.is_file())
    print(f"built {args.out} (build {build_id}, {size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The linker: combines object modules into an executable image.

LINK lays the code and static data of each module end to end, resolves
every [EXTERNAL] reference against the [GLOBAL] symbols of the other
modules and of the run-time library PASRTL.OLB (pulling in only the
library modules that are needed), relocates addresses, and writes the
image (.EXE) and a map (.MAP) listing every symbol, its module and
address.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

from . import VERSION
from .files import find_file, output_name
from .messages import Diagnostic, diag, has_errors
from .objfile import (Image, ImageModule, Library, ObjectModule, ObjFormatError, RoutineInfo,
                      VarInfo, read_library, read_object, write_image)
from .pcode import CODE, DATA, Instr, SymRef, operand_kinds
from .rtl import LIBRARY_PATH

_library_cache: dict[str, tuple[float, Library]] = {}


def vms_date(t: _dt.datetime | None = None) -> str:
    t = t or _dt.datetime.now()
    return t.strftime("%d-%b-%Y %H:%M:%S").upper().lstrip("0")


def load_library(path: Path = LIBRARY_PATH) -> Library:
    key = str(path)
    mtime = path.stat().st_mtime
    cached = _library_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    lib = read_library(path.read_text(), path.name)
    _library_cache[key] = (mtime, lib)
    return lib


@dataclass
class LinkOutcome:
    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)
    image: Image | None = None
    exe_path: str | None = None
    map_path: str | None = None
    map_text: str = ""


@dataclass
class _Placed:
    obj: ObjectModule
    from_library: bool
    code_base: int = 0
    data_base: int = 0


def link_files(obj_paths: list[str], *, output: str | None = None, map_file: bool = True,
               library: Path = LIBRARY_PATH) -> LinkOutcome:
    diags: list[Diagnostic] = []
    names = [n.strip() for item in obj_paths for n in str(item).split(",") if n.strip()]
    if not names:
        return LinkOutcome(False, [diag("LINK", "NOFILES")])
    objects: list[ObjectModule] = []
    paths: list[Path] = []
    for name in names:
        path = find_file(name, ".OBJ")
        if path is None:
            stem = Path(name).name.rsplit(".", 1)[0]
            diags.append(diag("LINK", "OPENIN", file=name, stem=stem))
            continue
        try:
            obj = read_object(path.read_text(errors="replace"), str(path))
        except (ObjFormatError, OSError, UnicodeDecodeError) as exc:
            diags.append(diag("LINK", "BADOBJ", file=str(path), reason=str(exc)))
            continue
        objects.append(obj)
        paths.append(path)
    if has_errors(diags):
        return LinkOutcome(False, diags)
    try:
        lib = load_library(library)
    except (ObjFormatError, OSError) as exc:
        diags.append(diag("LINK", "BADLIB", file=str(library), reason=str(exc)))
        return LinkOutcome(False, diags)

    exe_path = Path(output) if output else output_name(paths[0], ".EXE")
    if output and not exe_path.suffix:
        exe_path = exe_path.with_name(exe_path.name + ".EXE")
    image, link_diags, map_text = link_modules(objects, lib, image_name=exe_path.name)
    diags.extend(link_diags)
    map_path = output_name(exe_path, ".MAP") if map_file else None
    if image is None:
        for stale in (exe_path,):
            try:
                if stale.exists():
                    stale.unlink()
            except OSError:
                pass
        return LinkOutcome(False, diags)
    try:
        exe_path.write_text(write_image(image))
        if map_path is not None:
            map_path.write_text(map_text)
    except OSError:
        diags.append(diag("LINK", "OPENOUT", file=str(exe_path)))
        return LinkOutcome(False, diags)
    return LinkOutcome(not has_errors(diags), diags, image, str(exe_path),
                       str(map_path) if map_path else None, map_text)


def link_modules(objects: list[ObjectModule], lib: Library, image_name: str = "IMAGE.EXE"):
    """Link object modules (and the library modules they need). Returns (image or None, diagnostics, map text)."""
    diags: list[Diagnostic] = []
    placed: list[_Placed] = []
    definitions: dict[str, tuple[_Placed, object]] = {}

    def add(obj: ObjectModule, from_library: bool):
        p = _Placed(obj, from_library)
        placed.append(p)
        for s in obj.globals:
            if s.name in definitions:
                first = definitions[s.name][0].obj.name
                diags.append(diag("LINK", "MULDEF", file=obj.file or None, symbol=s.name,
                                  module=first, other=obj.name))
            else:
                definitions[s.name] = (p, s)

    for obj in objects:
        add(obj, False)
    changed = True
    while changed:
        changed = False
        for p in list(placed):
            for ref in p.obj.externals:
                if ref.name not in definitions and ref.name in lib.index:
                    libmod = lib.modules[lib.index[ref.name]]
                    if all(q.obj is not libmod for q in placed):
                        add(libmod, True)
                        changed = True

    undefined = 0
    for p in placed:
        for ref in p.obj.externals:
            d = definitions.get(ref.name)
            if d is None:
                undefined += 1
                line = p.obj.line_for(ref.sites[0]) if ref.sites else None
                diags.append(diag("LINK", "UNDFSYMS", file=p.obj.source or p.obj.file or None, line=line,
                                  symbol=ref.name, module=p.obj.name))
                continue
            dp, sym = d
            if sym.kind != ref.kind:
                diags.append(diag("LINK", "SYMKIND", file=p.obj.source or None, symbol=ref.name,
                                  defkind=_kind_word(sym.kind), defmodule=dp.obj.name, module=p.obj.name,
                                  usekind=_kind_word(ref.kind)))
            elif ref.signature and sym.signature and ref.signature != sym.signature:
                diags.append(diag("LINK", "SIGNATURE", file=p.obj.source or None, symbol=ref.name,
                                  module=p.obj.name, defmodule=dp.obj.name, defsig=sym.signature,
                                  usesig=ref.signature))

    mains = [p for p in placed if p.obj.kind == "PROGRAM" and not p.from_library]
    if not mains:
        diags.append(diag("LINK", "NOMAIN"))
    elif len(mains) > 1:
        diags.append(diag("LINK", "MULTFR", modules=", ".join(p.obj.name for p in mains)))
    if has_errors(diags) or undefined:
        diags.append(diag("LINK", "NOIMGFIL"))
        return None, diags, ""

    code_base = data_base = 0
    for p in placed:
        p.code_base, p.data_base = code_base, data_base
        code_base += len(p.obj.code)
        data_base += p.obj.data_size

    def address_of(name: str) -> int:
        dp, sym = definitions[name]
        return sym.value + (dp.code_base if sym.kind == "ROUTINE" else dp.data_base)

    main = mains[0]
    image = Image(name=Path(image_name).name.rsplit(".", 1)[0].upper(),
                  transfer=main.code_base + main.obj.transfer, data_size=data_base,
                  ident=VERSION, linked=vms_date())
    for p in placed:
        o = p.obj
        image.modules.append(ImageModule(o.name, p.code_base, len(o.code), p.data_base, o.data_size,
                                         Path(o.file).name if o.file else "", o.source))
        for ins in o.code:
            args = []
            for kind, arg in zip(operand_kinds(ins.op), ins.args):
                if kind in (CODE, DATA):
                    if isinstance(arg, SymRef):
                        arg = address_of(arg.name)
                    else:
                        arg = arg + (p.code_base if kind == CODE else p.data_base)
                args.append(arg)
            image.code.append(Instr(ins.op, args, ins.line, ins.comment))
        for r in o.routines:
            image.routines.append((o.name, RoutineInfo(r.name, r.start + p.code_base, r.end + p.code_base, r.level)))
        for v in o.variables:
            image.variables.append((o.name, VarInfo(None if v.routine is None else v.routine + p.code_base,
                                                    v.name, v.offset, v.cells)))
        for a, ln in o.lines:
            image.lines.append((o.name, a + p.code_base, ln))
    map_text = write_map(image, placed, definitions, image_name, diags)
    return image, diags, map_text


def _kind_word(kind: str) -> str:
    return "procedure or function" if kind == "ROUTINE" else "variable"


def _box(title: str) -> list[str]:
    bar = "+" + "-" * (len(title) + 2) + "+"
    return ["", bar, f"! {title} !", bar, ""]


def write_map(image: Image, placed: list[_Placed], definitions, image_name: str, diags) -> str:
    L = [f"{image_name:<40}{image.linked:>24}   VMS-LSE Linker {VERSION}", ""]
    L += _box("Object Module Synopsis")
    L.append(f"{'Module Name':<16}{'Ident':<8}{'Code':>6}{'Data':>6}  {'File':<32}Creation Date")
    L.append(f"{'-----------':<16}{'-----':<8}{'----':>6}{'----':>6}  {'----':<32}-------------")
    for p in placed:
        o = p.obj
        f = "PASRTL.OLB (run-time library)" if p.from_library else Path(o.file).name
        L.append(f"{o.name:<16}{o.ident:<8}{len(o.code):>6X}{o.data_size:>6X}  {f:<32}{o.created}")

    refs: dict[str, list[str]] = {}
    for p in placed:
        for ref in p.obj.externals:
            refs.setdefault(ref.name, [])
            if p.obj.name not in refs[ref.name]:
                refs[ref.name].append(p.obj.name)
    L += _box("Symbol Cross Reference")
    L.append(f"{'Symbol':<20}{'Kind':<9}{'Value':<10}{'Defined By':<28}Referenced By ...")
    L.append(f"{'------':<20}{'----':<9}{'-----':<10}{'----------':<28}-----------------")
    for name in sorted(definitions):
        dp, sym = definitions[name]
        value = sym.value + (dp.code_base if sym.kind == "ROUTINE" else dp.data_base)
        where = dp.obj.name + (" (PASRTL.OLB)" if dp.from_library else "")
        L.append(f"{name:<20}{sym.kind:<9}{value:08X}  {where:<28}{' '.join(refs.get(name, []))}")

    L += _box("Symbols By Value")
    L.append(f"{'Value':<10}{'Symbol':<20}{'Kind':<9}Module")
    L.append(f"{'-----':<10}{'------':<20}{'----':<9}------")
    rows = []
    for name, (dp, sym) in definitions.items():
        value = sym.value + (dp.code_base if sym.kind == "ROUTINE" else dp.data_base)
        rows.append((sym.kind != "ROUTINE", value, name, sym.kind, dp.obj.name))
    for _k, value, name, kind, mod in sorted(rows):
        L.append(f"{value:08X}  {name:<20}{kind:<9}{mod}")

    L += _box("Routines (every procedure and function, for the traceback)")
    L.append(f"{'Module':<16}{'Routine':<24}{'Start':<10}{'End':<10}Level")
    L.append(f"{'------':<16}{'-------':<24}{'-----':<10}{'---':<10}-----")
    for mod, r in image.routines:
        L.append(f"{mod:<16}{r.name:<24}{r.start:08X}  {r.end:08X}  {r.level}")

    static_vars = [(mod, v) for mod, v in image.variables if v.routine is None]
    if static_vars:
        L += _box("Static Data (variables declared at the outermost level)")
        L.append(f"{'Module':<16}{'Variable':<24}{'Address':<10}Cells")
        L.append(f"{'------':<16}{'--------':<24}{'-------':<10}-----")
        base = {m.name: m.data_base for m in image.modules}
        for mod, v in static_vars:
            L.append(f"{mod:<16}{v.name:<24}{v.offset + base[mod]:08X}  {v.cells}")

    L += _box("Image Synopsis")
    main = image.routine_at(image.transfer)
    lib_mods = [p.obj.name for p in placed if p.from_library]
    L.append(f"Transfer address:          {image.transfer:08X}  ({main[1].name if main else '?'})")
    L.append(f"Code size:                 {len(image.code)} instructions")
    L.append(f"Static data:               {image.data_size} cells")
    L.append(f"Modules linked:            {len(placed)}")
    L.append(f"From PASRTL.OLB:           {', '.join(lib_mods) if lib_mods else '(none)'}")
    warnings = [d for d in diags if d.severity == "W"]
    L.append(f"Link warnings:             {len(warnings)}")
    return "\n".join(L) + "\n"

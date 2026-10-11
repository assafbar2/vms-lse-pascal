"""Readable text formats for object modules (.OBJ), object libraries (.OLB)
and executable images (.EXE).

An object module holds p-code whose addresses are relative to the start
of the module, a GLOBALS table (symbols the module defines for others),
an EXTERNALS table (symbols it needs, with the addresses of the
instructions that refer to them -- the fixup sites), and debug records
(routines, variables and source line numbers) used by the traceback.

An image is what LINK produces: the code of every module laid end to end
with all addresses resolved, plus the same debug records.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from . import VERSION
from .pcode import CODE, Instr, SymRef, format_instr, operand_kinds, parse_operands, strip_comment


class ObjFormatError(Exception):
    def __init__(self, message: str, line_no: int | None = None):
        super().__init__(message if line_no is None else f"line {line_no}: {message}")
        self.line_no = line_no


@dataclass
class Symbol:
    name: str
    kind: str            # "ROUTINE" or "DATA"
    value: int
    signature: str = ""


@dataclass
class ExternRef:
    name: str
    kind: str
    signature: str = ""
    sites: list[int] = field(default_factory=list)


@dataclass
class RoutineInfo:
    name: str
    start: int
    end: int
    level: int


@dataclass
class VarInfo:
    routine: int | None   # start address of the owning routine, None for static data
    name: str
    offset: int
    cells: int


@dataclass
class ObjectModule:
    name: str
    kind: str = "PROGRAM"
    source: str = ""
    ident: str = VERSION
    created: str = ""
    data_size: int = 0
    transfer: int | None = None
    globals: list[Symbol] = field(default_factory=list)
    externals: list[ExternRef] = field(default_factory=list)
    routines: list[RoutineInfo] = field(default_factory=list)
    variables: list[VarInfo] = field(default_factory=list)
    code: list[Instr] = field(default_factory=list)
    lines: list[tuple[int, int]] = field(default_factory=list)
    file: str = ""        # where it was read from (not stored in the text)

    def collect_externals(self, signatures: dict[str, str]):
        """Build the EXTERNALS table from the symbolic operands in the code."""
        refs: dict[str, ExternRef] = {}
        for addr, ins in enumerate(self.code):
            for kind, arg in zip(operand_kinds(ins.op), ins.args):
                if isinstance(arg, SymRef):
                    ref = refs.get(arg.name)
                    if ref is None:
                        ref = ExternRef(arg.name, "ROUTINE" if kind == CODE else "DATA",
                                        signatures.get(arg.name, ""))
                        refs[arg.name] = ref
                    ref.sites.append(addr)
        self.externals = list(refs.values())

    def line_for(self, addr: int) -> int | None:
        best = None
        for a, ln in self.lines:
            if a <= addr:
                best = ln
            else:
                break
        return best


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _split_fields(text: str) -> list[str]:
    """Split on blanks, keeping 'quoted strings' together (without the quotes)."""
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in " \t":
            i += 1
            continue
        if ch == "'":
            j = i + 1
            chars = []
            while j < len(text):
                if text[j] == "'":
                    if text[j + 1:j + 2] == "'":
                        chars.append("'")
                        j += 2
                        continue
                    break
                chars.append(text[j])
                j += 1
            else:
                raise ValueError("unterminated string")
            out.append("".join(chars))
            i = j + 1
            continue
        j = i
        while j < len(text) and text[j] not in " \t":
            j += 1
        out.append(text[i:j])
        i = j
    return out


def _code_lines(code: list[Instr]) -> list[str]:
    out = []
    for addr, ins in enumerate(code):
        text = f"  {addr:04X}  {format_instr(ins)}"
        if ins.comment:
            text = f"{text:<44}; {ins.comment}"
        out.append(text)
    return out


def write_object(m: ObjectModule) -> str:
    L = [
        "; VMS-LSE Pascal object module.  Addresses are hexadecimal;",
        "; frame offsets and counts are decimal.",
        f".MODULE    {m.name}",
        f".KIND      {m.kind}",
        f".IDENT     {_q(m.ident)}",
        f".SOURCE    {_q(m.source)}",
        f".CREATED   {_q(m.created)}",
        f".DATA      {m.data_size:04X}                 ; cells of static data",
    ]
    if m.transfer is not None:
        L.append(f".TRANSFER  {m.transfer:04X}                 ; main program entry point")
    L.append(".GLOBALS                        ; symbols defined here for other modules")
    for s in m.globals:
        L.append(f"  {s.name:<20} {s.kind:<8} {s.value:04X}  {_q(s.signature)}")
    L.append(".EXTERNALS                      ; symbols needed from elsewhere, and where they are used")
    for e in m.externals:
        sites = " ".join(f"{a:04X}" for a in e.sites)
        L.append(f"  {e.name:<20} {e.kind:<8} {_q(e.signature)}  {sites}")
    L.append(".ROUTINES                       ; debug: routine, first and last address, nesting level")
    for r in m.routines:
        L.append(f"  {r.name:<20} {r.start:04X} {r.end:04X} {r.level}")
    L.append(".VARIABLES                      ; debug: owning routine (* = static), name, offset, cells")
    for v in m.variables:
        if v.routine is None:
            L.append(f"  {'*':<6} {v.name:<20} {v.offset:04X} {v.cells}")
        else:
            L.append(f"  {v.routine:04X}   {v.name:<20} {v.offset} {v.cells}")
    L.append(".CODE")
    L.extend(_code_lines(m.code))
    L.append(".LINES                          ; debug: first address of each source line")
    for addr, line in m.lines:
        L.append(f"  {addr:04X} {line}")
    L.append(".END")
    return "\n".join(L) + "\n"


_HEADER_KEYS = {".MODULE", ".KIND", ".IDENT", ".SOURCE", ".CREATED", ".DATA", ".TRANSFER"}
_SECTIONS = {".GLOBALS", ".EXTERNALS", ".ROUTINES", ".VARIABLES", ".CODE", ".LINES"}


def read_object(text: str, file: str = "") -> ObjectModule:
    lines = text.splitlines()
    m: ObjectModule | None = None
    section = None
    ended = False
    for no, raw in enumerate(lines, 1):
        line = strip_comment(raw).strip()
        if not line:
            continue
        try:
            word = line.split(None, 1)[0].upper()
            rest = line[len(word):].strip()
            if word.startswith("."):
                if word == ".MODULE":
                    if m is not None:
                        raise ObjFormatError("second .MODULE record", no)
                    m = ObjectModule(name=rest.upper(), file=file)
                    continue
                if m is None:
                    raise ObjFormatError("file does not start with a .MODULE record", no)
                if word == ".END":
                    ended = True
                    break
                if word in _HEADER_KEYS:
                    f = _split_fields(rest)
                    value = f[0] if f else ""
                    if word == ".KIND":
                        if value.upper() not in ("PROGRAM", "MODULE"):
                            raise ObjFormatError(f"unknown kind {value!r}", no)
                        m.kind = value.upper()
                    elif word == ".IDENT":
                        m.ident = value
                    elif word == ".SOURCE":
                        m.source = value
                    elif word == ".CREATED":
                        m.created = value
                    elif word == ".DATA":
                        m.data_size = int(value, 16)
                    elif word == ".TRANSFER":
                        m.transfer = int(value, 16)
                    continue
                if word in _SECTIONS:
                    section = word
                    continue
                raise ObjFormatError(f"unknown record {word}", no)
            if m is None:
                raise ObjFormatError("file does not start with a .MODULE record", no)
            f = _split_fields(line)
            if section == ".GLOBALS":
                name, kind, value = f[0].upper(), f[1].upper(), int(f[2], 16)
                if kind not in ("ROUTINE", "DATA"):
                    raise ObjFormatError(f"unknown symbol kind {kind}", no)
                m.globals.append(Symbol(name, kind, value, f[3] if len(f) > 3 else ""))
            elif section == ".EXTERNALS":
                name, kind = f[0].upper(), f[1].upper()
                if kind not in ("ROUTINE", "DATA"):
                    raise ObjFormatError(f"unknown symbol kind {kind}", no)
                sig = f[2] if len(f) > 2 else ""
                m.externals.append(ExternRef(name, kind, sig, [int(a, 16) for a in f[3:]]))
            elif section == ".ROUTINES":
                m.routines.append(RoutineInfo(f[0].upper(), int(f[1], 16), int(f[2], 16), int(f[3])))
            elif section == ".VARIABLES":
                if f[0] == "*":
                    m.variables.append(VarInfo(None, f[1].upper(), int(f[2], 16), int(f[3])))
                else:
                    m.variables.append(VarInfo(int(f[0], 16), f[1].upper(), int(f[2]), int(f[3])))
            elif section == ".CODE":
                addr_text, _, rest = line.partition(" ")
                addr = int(addr_text, 16)
                if addr != len(m.code):
                    raise ObjFormatError(f"code address {addr_text} out of sequence", no)
                rest = rest.strip()
                op, _, operands = rest.partition(" ")
                op = op.upper()
                try:
                    operand_kinds(op)
                except KeyError:
                    raise ObjFormatError(f"unknown instruction {op}", no) from None
                code_part = strip_comment(raw)
                comment = raw[len(code_part) + 1:].strip() if len(code_part) < len(raw) else ""
                m.code.append(Instr(op, parse_operands(op, operands), 0, comment))
            elif section == ".LINES":
                m.lines.append((int(f[0], 16), int(f[1])))
            else:
                raise ObjFormatError("data outside any section", no)
        except ObjFormatError:
            raise
        except (ValueError, IndexError) as exc:
            raise ObjFormatError(str(exc) or "malformed record", no) from None
    if m is None:
        raise ObjFormatError("file does not start with a .MODULE record")
    if not ended:
        raise ObjFormatError("missing .END record")
    _attach_lines(m)
    for ref in m.externals:
        for site in ref.sites:
            if not 0 <= site < len(m.code):
                raise ObjFormatError(f"fixup site {site:04X} for {ref.name} is outside the code")
    return m


def _attach_lines(m: ObjectModule):
    i = 0
    current = 0
    for addr, ins in enumerate(m.code):
        while i < len(m.lines) and m.lines[i][0] <= addr:
            current = m.lines[i][1]
            i += 1
        ins.line = current


def line_table(code: list[Instr]) -> list[tuple[int, int]]:
    out = []
    last = None
    for addr, ins in enumerate(code):
        if ins.line and ins.line != last:
            out.append((addr, ins.line))
            last = ins.line
    return out


# ----------------------------------------------------------------------
# Object libraries
# ----------------------------------------------------------------------

def write_library(name: str, modules: list[ObjectModule], *, title: str = "", created: str = "") -> str:
    L = [
        "; VMS-LSE Pascal object library: object modules plus an index of their global symbols.",
        f".LIBRARY   {name}",
        f".TITLE     {_q(title)}",
        f".CREATED   {_q(created)}",
        ".INDEX                          ; symbol, module that defines it",
    ]
    for m in modules:
        for s in m.globals:
            L.append(f"  {s.name:<20} {m.name}")
    L.append("")
    text = "\n".join(L) + "\n"
    for m in modules:
        text += write_object(m) + "\n"
    return text + ".ENDLIBRARY\n"


@dataclass
class Library:
    name: str
    index: dict[str, str]
    modules: dict[str, ObjectModule]
    file: str = ""


def read_library(text: str, file: str = "") -> Library:
    name = ""
    index: dict[str, str] = {}
    modules: dict[str, ObjectModule] = {}
    chunk: list[str] | None = None
    in_index = False
    for no, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw).strip()
        word = line.split(None, 1)[0].upper() if line else ""
        if chunk is not None:
            chunk.append(raw)
            if word == ".END":
                m = read_object("\n".join(chunk), file)
                modules[m.name] = m
                chunk = None
            continue
        if not line:
            continue
        if word == ".LIBRARY":
            name = line.split(None, 1)[1].strip().upper() if " " in line else ""
        elif word in (".TITLE", ".CREATED"):
            in_index = False
        elif word == ".INDEX":
            in_index = True
        elif word == ".MODULE":
            in_index = False
            chunk = [raw]
        elif word == ".ENDLIBRARY":
            break
        elif in_index:
            f = line.split()
            if len(f) != 2:
                raise ObjFormatError("malformed index entry", no)
            index[f[0].upper()] = f[1].upper()
        else:
            raise ObjFormatError(f"unexpected record {word}", no)
    if chunk is not None:
        raise ObjFormatError("library ends inside a module")
    for sym, mod in index.items():
        if mod not in modules:
            raise ObjFormatError(f"index names module {mod}, which is not in the library")
    for m in modules.values():
        m.file = file
    return Library(name, index, modules, file)


# ----------------------------------------------------------------------
# Executable images
# ----------------------------------------------------------------------

@dataclass
class ImageModule:
    name: str
    code_base: int
    code_size: int
    data_base: int
    data_size: int
    file: str = ""
    source: str = ""


@dataclass
class Image:
    name: str
    transfer: int
    data_size: int
    ident: str = VERSION
    linked: str = ""
    modules: list[ImageModule] = field(default_factory=list)
    routines: list[tuple[str, RoutineInfo]] = field(default_factory=list)
    variables: list[tuple[str, VarInfo]] = field(default_factory=list)
    code: list[Instr] = field(default_factory=list)
    lines: list[tuple[str, int, int]] = field(default_factory=list)

    def module_at(self, addr: int) -> ImageModule | None:
        for m in self.modules:
            if m.code_base <= addr < m.code_base + m.code_size:
                return m
        return None

    def routine_at(self, addr: int) -> tuple[str, RoutineInfo] | None:
        best = None
        for mod, r in self.routines:
            if r.start <= addr <= r.end:
                if best is None or r.start >= best[1].start:
                    best = (mod, r)
        return best

    def line_at(self, addr: int) -> int | None:
        """Source line of the instruction at ``addr`` (None for code without line records)."""
        m = self.module_at(addr)
        if m is None:
            return None
        index = self.__dict__.get("_line_index")
        if index is None:
            index = {}
            for mod, a, ln in sorted(self.lines, key=lambda t: t[1]):
                addrs, nums = index.setdefault(mod, ([], []))
                addrs.append(a)
                nums.append(ln)
            self.__dict__["_line_index"] = index
        entry = index.get(m.name)
        if entry is None:
            return None
        i = bisect.bisect_right(entry[0], addr) - 1
        if i < 0 or entry[0][i] < m.code_base:
            return None
        return entry[1][i]


def write_image(img: Image) -> str:
    L = [
        "; VMS-LSE Pascal executable image.  Addresses are hexadecimal;",
        "; frame offsets and counts are decimal.",
        f".IMAGE     {img.name}",
        f".IDENT     {_q(img.ident)}",
        f".LINKED    {_q(img.linked)}",
        f".TRANSFER  {img.transfer:04X}                 ; where the program starts",
        f".DATA      {img.data_size:04X}                 ; cells of static data",
        ".MODULES                        ; module, code base and size, data base and size, object file, source",
    ]
    for m in img.modules:
        L.append(f"  {m.name:<16} {m.code_base:04X} {m.code_size:04X} {m.data_base:04X} {m.data_size:04X}"
                 f"  {_q(m.file)} {_q(m.source)}")
    L.append(".ROUTINES                       ; debug: module, routine, first and last address, level")
    for mod, r in img.routines:
        L.append(f"  {mod:<16} {r.name:<20} {r.start:04X} {r.end:04X} {r.level}")
    L.append(".VARIABLES                      ; debug: module, routine address (* = static), name, offset, cells")
    for mod, v in img.variables:
        if v.routine is None:
            L.append(f"  {mod:<16} {'*':<6} {v.name:<20} {v.offset:04X} {v.cells}")
        else:
            L.append(f"  {mod:<16} {v.routine:04X}   {v.name:<20} {v.offset} {v.cells}")
    L.append(".CODE")
    L.extend(_code_lines(img.code))
    L.append(".LINES                          ; debug: module, first address of each source line, line")
    for mod, addr, line in img.lines:
        L.append(f"  {mod:<16} {addr:04X} {line}")
    L.append(".END")
    return "\n".join(L) + "\n"


def read_image(text: str) -> Image:
    img: Image | None = None
    section = None
    header: dict[str, str] = {}
    ended = False
    for no, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw).strip()
        if not line:
            continue
        try:
            word = line.split(None, 1)[0].upper()
            rest = line[len(word):].strip()
            if word.startswith("."):
                if word == ".END":
                    ended = True
                    break
                if word in (".IMAGE", ".IDENT", ".LINKED", ".TRANSFER", ".DATA"):
                    f = _split_fields(rest)
                    header[word] = f[0] if f else ""
                    continue
                if word in (".MODULES", ".ROUTINES", ".VARIABLES", ".CODE", ".LINES"):
                    if img is None:
                        if ".IMAGE" not in header or ".TRANSFER" not in header:
                            raise ObjFormatError("missing .IMAGE or .TRANSFER record", no)
                        img = Image(name=header[".IMAGE"].upper(),
                                    transfer=int(header[".TRANSFER"], 16),
                                    data_size=int(header.get(".DATA", "0"), 16),
                                    ident=header.get(".IDENT", ""), linked=header.get(".LINKED", ""))
                    section = word
                    continue
                raise ObjFormatError(f"unknown record {word}", no)
            if img is None:
                raise ObjFormatError("data before the image header", no)
            if section == ".CODE":
                addr_text, _, rest = line.partition(" ")
                addr = int(addr_text, 16)
                if addr != len(img.code):
                    raise ObjFormatError(f"code address {addr_text} out of sequence", no)
                op, _, operands = rest.strip().partition(" ")
                op = op.upper()
                try:
                    kinds = operand_kinds(op)
                except KeyError:
                    raise ObjFormatError(f"unknown instruction {op}", no) from None
                args = parse_operands(op, operands)
                for k, a in zip(kinds, args):
                    if isinstance(a, SymRef):
                        raise ObjFormatError(f"unresolved symbol {a.name} in image", no)
                code_part = strip_comment(raw)
                comment = raw[len(code_part) + 1:].strip() if len(code_part) < len(raw) else ""
                img.code.append(Instr(op, args, 0, comment))
                continue
            f = _split_fields(line)
            if section == ".MODULES":
                img.modules.append(ImageModule(f[0].upper(), int(f[1], 16), int(f[2], 16), int(f[3], 16),
                                               int(f[4], 16), f[5] if len(f) > 5 else "",
                                               f[6] if len(f) > 6 else ""))
            elif section == ".ROUTINES":
                img.routines.append((f[0].upper(), RoutineInfo(f[1].upper(), int(f[2], 16), int(f[3], 16), int(f[4]))))
            elif section == ".VARIABLES":
                if f[1] == "*":
                    img.variables.append((f[0].upper(), VarInfo(None, f[2].upper(), int(f[3], 16), int(f[4]))))
                else:
                    img.variables.append((f[0].upper(), VarInfo(int(f[1], 16), f[2].upper(), int(f[3]), int(f[4]))))
            elif section == ".LINES":
                img.lines.append((f[0].upper(), int(f[1], 16), int(f[2])))
            else:
                raise ObjFormatError("data outside any section", no)
        except ObjFormatError:
            raise
        except (ValueError, IndexError) as exc:
            raise ObjFormatError(str(exc) or "malformed record", no) from None
    if img is None:
        raise ObjFormatError("not an image file (no .IMAGE header)")
    if not ended:
        raise ObjFormatError("missing .END record")
    if not 0 <= img.transfer < max(len(img.code), 1):
        raise ObjFormatError("transfer address is outside the code")
    img.lines.sort(key=lambda t: t[1])
    for addr, ins in enumerate(img.code):
        ins.line = img.line_at(addr) or 0
    return img

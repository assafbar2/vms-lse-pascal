"""The p-code virtual machine.

Runs an :class:`~pascal.objfile.Image` produced by LINK. See
:mod:`pascal.pcode` for the memory layout and the instruction set.

A fatal run-time error stops the program with a ``%PAS-F-...`` message
followed by a ``%TRACE-F-TRACEBACK`` symbolic stack dump that names each
active routine and the source line it had reached.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .messages import Diagnostic, diag
from .objfile import Image
from .pcode import OPCODES
from .rtl import HaltProgram, PascalRuntimeError, Runtime

MAXINT = 2147483647
MININT = -2147483648
MAX_REAL = 1.7976931348623157e308
STACK_LIMIT = 2_000_000
DEPTH_LIMIT = 20_000
TRACE_HEAD = 20
TRACE_TAIL = 5

OPS = {name: i for i, name in enumerate(OPCODES)}
(OP_LIT, OP_LITS, OP_LDG, OP_STG, OP_LAG, OP_LDL, OP_STL, OP_LAL, OP_LDI, OP_STI, OP_LAI,
 OP_IND, OP_STO, OP_MOVE, OP_LDBLK, OP_SMOVE, OP_SBLK, OP_INDEX, OP_OFFS, OP_ADDI, OP_SUBI,
 OP_MULI, OP_DIVI, OP_MODI, OP_NEGI, OP_ADDR, OP_SUBR, OP_MULR, OP_DIVR, OP_NEGR, OP_FLT,
 OP_FLT2, OP_EQU, OP_NEQ, OP_LES, OP_LEQ, OP_GRT, OP_GEQ, OP_AND, OP_OR, OP_NOT, OP_ABSI,
 OP_ABSR, OP_SQRI, OP_SQRR, OP_ODD, OP_CHR, OP_TRUNC, OP_ROUND, OP_SUCC, OP_PRED, OP_CHK,
 OP_DUP, OP_POP, OP_JMP, OP_JPF, OP_JPT, OP_MARK, OP_CALL, OP_ENTER, OP_RET, OP_RETF, OP_RETV,
 OP_NATIVE, OP_STOP, OP_CASERR) = range(len(OPCODES))


@dataclass
class VMResult:
    exit_status: int
    error: Diagnostic | None = None
    traceback: list[str] = field(default_factory=list)


class _Uninit(Exception):
    def __init__(self, addr: int):
        self.addr = addr


class VM:
    def __init__(self, image: Image, runtime: Runtime, max_steps: int | None = None):
        self.image = image
        self.rt = runtime
        self.max_steps = max_steps
        self.code = []
        for ins in image.code:
            op = OPS[ins.op]
            args = list(ins.args) + [None, None, None]
            if ins.op == "NATIVE":
                fn = runtime.natives.get(args[0])
                if fn is None:
                    raise ValueError(f"unknown run-time routine {args[0]}")
                args[0] = fn
            self.code.append((op, args[0], args[1], args[2]))
        self.M: list = [None] * image.data_size
        runtime.memory = self.M
        self.pc = image.transfer
        self.bp = image.data_size
        self.steps = 0

    # -- running -----------------------------------------------------------------
    def run(self) -> VMResult:
        M = self.M
        M.extend([0, -1, -1])
        try:
            self._loop()
            return VMResult(0)
        except HaltProgram:
            return VMResult(0)
        except _Uninit as u:
            return self._fail("UNINITVAR", {"name": self.describe_address(u.addr)})
        except PascalRuntimeError as e:
            return self._fail(e.ident, e.args_)
        except KeyboardInterrupt:
            return self._fail("CONTROLC", {})
        except RecursionError:
            return self._fail("STKOVF", {})
        except (IndexError, TypeError, ValueError, AttributeError, OverflowError) as exc:
            return self._fail("BUGCHECK", {"reason": f"{type(exc).__name__}: {exc}"})

    def _loop(self):
        M = self.M
        code = self.code
        pc = self.pc
        bp = self.bp
        steps = self.steps
        limit = self.max_steps if self.max_steps is not None else -1
        depth = 0
        append = M.append
        pop = M.pop
        try:
            while True:
                op, a, b, c = code[pc]
                pc += 1
                steps += 1
                if steps == limit:
                    raise PascalRuntimeError("STEPLIMIT", steps=limit)
                if op == OP_LDL:
                    v = M[bp + a]
                    if v is None:
                        raise _Uninit(bp + a)
                    append(v)
                elif op == OP_LIT:
                    append(a)
                elif op == OP_LDG:
                    v = M[a]
                    if v is None:
                        raise _Uninit(a)
                    append(v)
                elif op == OP_STL:
                    M[bp + a] = pop()
                elif op == OP_STG:
                    M[a] = pop()
                elif op == OP_MARK:
                    sl = bp
                    for _ in range(a):
                        sl = M[sl]
                    append(sl)
                    append(None)
                    append(None)
                elif op == OP_CALL:
                    depth += 1
                    if depth > DEPTH_LIMIT or len(M) > STACK_LIMIT:
                        raise PascalRuntimeError("STKOVF")
                    nbp = len(M) - b - 3
                    M[nbp + 1] = bp
                    M[nbp + 2] = pc
                    bp = nbp
                    pc = a
                elif op == OP_ENTER:
                    if a:
                        M.extend([None] * a)
                elif op == OP_NATIVE:
                    r = a(M[bp + 3:bp + 3 + b])
                    if r is not None:
                        append(r)
                elif op == OP_RET:
                    pc = M[bp + 2]
                    old = M[bp + 1]
                    del M[bp:]
                    bp = old
                    depth -= 1
                elif op == OP_RETV:
                    v = pop()
                    pc = M[bp + 2]
                    old = M[bp + 1]
                    del M[bp:]
                    bp = old
                    append(v)
                    depth -= 1
                elif op == OP_RETF:
                    v = M[bp + a]
                    if v is None:
                        self.pc, self.bp = pc, bp
                        r = self.image.routine_at(pc - 1)
                        raise PascalRuntimeError("NOFUNCRES", name=r[1].name if r else "?")
                    pc = M[bp + 2]
                    old = M[bp + 1]
                    del M[bp:]
                    bp = old
                    append(v)
                    depth -= 1
                elif op == OP_JPF:
                    if not pop():
                        pc = a
                elif op == OP_JPT:
                    if pop():
                        pc = a
                elif op == OP_JMP:
                    pc = a
                elif op == OP_ADDI:
                    y = pop()
                    r = M[-1] + y
                    if r > MAXINT or r < MININT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_SUBI:
                    y = pop()
                    r = M[-1] - y
                    if r > MAXINT or r < MININT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_MULI:
                    y = pop()
                    r = M[-1] * y
                    if r > MAXINT or r < MININT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_EQU:
                    y = pop()
                    M[-1] = 1 if M[-1] == y else 0
                elif op == OP_NEQ:
                    y = pop()
                    M[-1] = 1 if M[-1] != y else 0
                elif op == OP_LES:
                    y = pop()
                    M[-1] = 1 if M[-1] < y else 0
                elif op == OP_LEQ:
                    y = pop()
                    M[-1] = 1 if M[-1] <= y else 0
                elif op == OP_GRT:
                    y = pop()
                    M[-1] = 1 if M[-1] > y else 0
                elif op == OP_GEQ:
                    y = pop()
                    M[-1] = 1 if M[-1] >= y else 0
                elif op == OP_IND:
                    addr = M[-1]
                    v = M[addr]
                    if v is None:
                        raise _Uninit(addr)
                    M[-1] = v
                elif op == OP_STO:
                    v = pop()
                    M[pop()] = v
                elif op == OP_INDEX:
                    i = pop()
                    if i < a or i > b:
                        raise PascalRuntimeError("ARRINDVAL", value=i, low=a, high=b)
                    M[-1] += (i - a) * c
                elif op == OP_OFFS:
                    M[-1] += a
                elif op == OP_LAL:
                    append(bp + a)
                elif op == OP_LAG:
                    append(a)
                elif op == OP_LDI:
                    f = bp
                    for _ in range(a):
                        f = M[f]
                    v = M[f + b]
                    if v is None:
                        raise _Uninit(f + b)
                    append(v)
                elif op == OP_STI:
                    f = bp
                    for _ in range(a):
                        f = M[f]
                    M[f + b] = pop()
                elif op == OP_LAI:
                    f = bp
                    for _ in range(a):
                        f = M[f]
                    append(f + b)
                elif op == OP_LITS:
                    append(a)
                elif op == OP_DIVI:
                    y = pop()
                    x = M[-1]
                    if y == 0:
                        raise PascalRuntimeError("DIVBYZERO")
                    q = abs(x) // abs(y)
                    r = q if (x < 0) == (y < 0) else -q
                    if r > MAXINT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_MODI:
                    y = pop()
                    x = M[-1]
                    if y == 0:
                        raise PascalRuntimeError("DIVBYZERO")
                    r = abs(x) % abs(y)
                    M[-1] = r if x >= 0 else -r
                elif op == OP_NEGI:
                    r = -M[-1]
                    if r > MAXINT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_ADDR:
                    y = pop()
                    r = M[-1] + y
                    if not -MAX_REAL <= r <= MAX_REAL:
                        raise PascalRuntimeError("FLTOVF")
                    M[-1] = r
                elif op == OP_SUBR:
                    y = pop()
                    r = M[-1] - y
                    if not -MAX_REAL <= r <= MAX_REAL:
                        raise PascalRuntimeError("FLTOVF")
                    M[-1] = r
                elif op == OP_MULR:
                    y = pop()
                    r = M[-1] * y
                    if not -MAX_REAL <= r <= MAX_REAL:
                        raise PascalRuntimeError("FLTOVF")
                    M[-1] = r
                elif op == OP_DIVR:
                    y = pop()
                    if y == 0:
                        raise PascalRuntimeError("DIVBYZERO")
                    r = M[-1] / y
                    if not -MAX_REAL <= r <= MAX_REAL:
                        raise PascalRuntimeError("FLTOVF")
                    M[-1] = r
                elif op == OP_NEGR:
                    M[-1] = -M[-1]
                elif op == OP_FLT:
                    M[-1] = float(M[-1])
                elif op == OP_FLT2:
                    M[-2] = float(M[-2])
                elif op == OP_NOT:
                    M[-1] = 0 if M[-1] else 1
                elif op == OP_AND:
                    y = pop()
                    M[-1] = 1 if (M[-1] and y) else 0
                elif op == OP_OR:
                    y = pop()
                    M[-1] = 1 if (M[-1] or y) else 0
                elif op == OP_DUP:
                    append(M[-1])
                elif op == OP_POP:
                    pop()
                elif op == OP_CHK:
                    v = M[-1]
                    if v < a or v > b:
                        raise PascalRuntimeError("VALOUTRAN", value=v, low=a, high=b)
                elif op == OP_SUCC:
                    v = M[-1] + 1
                    if v > b:
                        raise PascalRuntimeError("VALOUTRAN", value=v, low=a, high=b)
                    M[-1] = v
                elif op == OP_PRED:
                    v = M[-1] - 1
                    if v < a:
                        raise PascalRuntimeError("VALOUTRAN", value=v, low=a, high=b)
                    M[-1] = v
                elif op == OP_CHR:
                    v = M[-1]
                    if v < 0 or v > 255:
                        raise PascalRuntimeError("VALOUTRAN", value=v, low=0, high=255)
                elif op == OP_ODD:
                    M[-1] = M[-1] & 1
                elif op == OP_ABSI:
                    r = abs(M[-1])
                    if r > MAXINT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_ABSR:
                    M[-1] = abs(M[-1])
                elif op == OP_SQRI:
                    r = M[-1] * M[-1]
                    if r > MAXINT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_SQRR:
                    r = M[-1] * M[-1]
                    if r > MAX_REAL:
                        raise PascalRuntimeError("FLTOVF")
                    M[-1] = r
                elif op == OP_TRUNC:
                    x = M[-1]
                    if not -MAX_REAL <= x <= MAX_REAL:
                        raise PascalRuntimeError("INTOVF")
                    r = int(x)
                    if r > MAXINT or r < MININT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_ROUND:
                    x = M[-1]
                    if not -MAX_REAL <= x <= MAX_REAL:
                        raise PascalRuntimeError("INTOVF")
                    r = int(x + 0.5) if x >= 0 else -int(-x + 0.5)
                    if r > MAXINT or r < MININT:
                        raise PascalRuntimeError("INTOVF")
                    M[-1] = r
                elif op == OP_MOVE:
                    src = pop()
                    dst = pop()
                    M[dst:dst + a] = M[src:src + a]
                elif op == OP_LDBLK:
                    addr = pop()
                    M.extend(M[addr:addr + a])
                elif op == OP_SMOVE:
                    s = pop()
                    dst = pop()
                    M[dst:dst + a] = [ord(ch) for ch in s.ljust(a)[:a]]
                elif op == OP_SBLK:
                    s = pop()
                    M.extend(ord(ch) for ch in s.ljust(a)[:a])
                elif op == OP_CASERR:
                    raise PascalRuntimeError("CASSELVAL", value=pop())
                elif op == OP_STOP:
                    return
                else:
                    raise ValueError(f"bad opcode {op}")
        finally:
            self.pc = pc
            self.bp = bp
            self.steps = steps

    # -- error reporting -------------------------------------------------------------
    def frames(self) -> list[tuple[int, int]]:
        """(frame base, pc) for each active routine, innermost first."""
        out = []
        bp, pc = self.bp, self.pc - 1
        M = self.M
        seen = 0
        while bp is not None and bp >= 0 and seen < DEPTH_LIMIT + 5:
            out.append((bp, pc))
            if bp + 2 >= len(M):
                break
            ret, dyn = M[bp + 2], M[bp + 1]
            if dyn is None or dyn < 0 or ret is None:
                break
            bp, pc = dyn, ret - 1
            seen += 1
        return out

    def describe_address(self, addr: int) -> str:
        img = self.image

        def named(v):
            return v.name if v.cells == 1 else f"{v.name}[...]"

        if addr < img.data_size:
            for m in img.modules:
                if m.data_base <= addr < m.data_base + m.data_size:
                    for mod, v in img.variables:
                        if mod == m.name and v.routine is None and v.offset <= addr - m.data_base < v.offset + v.cells:
                            return named(v)
            return "?"
        for base, pc in self.frames():
            if base <= addr:
                r = img.routine_at(pc)
                if r is not None:
                    for mod, v in img.variables:
                        if (v.routine == r[1].start and mod == r[0]
                                and v.offset <= addr - base < v.offset + v.cells):
                            return named(v)
                break
        return "(a temporary value)"

    def traceback(self) -> tuple[list[str], tuple[str | None, int | None]]:
        img = self.image
        lines = [
            "%TRACE-F-TRACEBACK, symbolic stack dump follows",
            "module name     routine name                     line       rel PC    abs PC",
        ]
        location = (None, None)
        frames = self.frames()
        shown = list(enumerate(frames))
        if len(frames) > TRACE_HEAD + TRACE_TAIL:
            shown = shown[:TRACE_HEAD] + [(-1, (0, 0))] + shown[-TRACE_TAIL:]
        for index, (_base, pc) in shown:
            if index < 0:
                hidden = len(frames) - TRACE_HEAD - TRACE_TAIL
                lines.append(f"                ... {hidden} more calls not shown ...")
                continue
            mod = img.module_at(pc)
            r = img.routine_at(pc)
            ln = img.line_at(pc)
            mname = mod.name if mod else "?"
            rname = r[1].name if r else "?"
            rel = pc - (mod.code_base if mod else 0)
            line_text = str(ln) if ln is not None else ""
            lines.append(f"{mname:<16}{rname:<32}{line_text:>5}      {rel:08X}  {pc:08X}")
            if location == (None, None) and ln is not None:
                location = (mod.source or mod.file if mod else None, ln)
        return lines, location

    def _fail(self, ident: str, args: dict) -> VMResult:
        tb, (file, line) = self.traceback()
        d = diag("PAS", ident, file=file, line=line, **args)
        self.rt.write_message(d.format(explain=self.rt.explain) + "\n" + "\n".join(tb))
        return VMResult(1, d, tb)

"""Code generation: annotated AST to p-code in an :class:`ObjectModule`.

Calls to WRITELN, READLN, SQRT, RANDOM and friends become calls to the
``PAS$...`` routines of the run-time library, so they show up in the
object module's EXTERNALS table and are resolved by LINK.
"""

from __future__ import annotations

from . import VERSION
from . import astnodes as A
from . import types as T
from .objfile import ObjectModule, RoutineInfo, Symbol, VarInfo, line_table
from .pcode import Instr, SymRef
from .rtl import ROUTINES as RTL_ROUTINES
from .semantic import FRAME_HEADER, ConstSym, RoutineSym, StdSym, UnitInfo, VarSym

DEFAULT_WIDTH = {"INTEGER": 10, "REAL": 12, "BOOLEAN": 6, "CHAR": 1}


class Label:
    __slots__ = ("addr",)

    def __init__(self):
        self.addr = None


class CodeGen:
    def __init__(self, program: A.Program, info: UnitInfo, source: str, created: str):
        self.program = program
        self.info = info
        self.code: list[Instr] = []
        self.level = 0
        self.line = 0
        self.temp_next = 0
        self.temp_max = 0
        self.routines: list[RoutineInfo] = []
        self.variables: list[VarInfo] = []
        self.signatures: dict[str, str] = {}
        self.obj = ObjectModule(name=info.name, kind=info.kind, source=source, ident=VERSION,
                                created=created, data_size=info.data_size)

    # -- emission helpers ----------------------------------------------------
    def emit(self, op: str, *args, comment: str = "") -> Instr:
        ins = Instr(op, list(args), self.line, comment)
        self.code.append(ins)
        return ins

    def place(self, label: Label):
        label.addr = len(self.code)

    def alloc_temp(self) -> int:
        off = self.temp_next
        self.temp_next += 1
        self.temp_max = max(self.temp_max, self.temp_next)
        return off

    def free_temp(self):
        self.temp_next -= 1

    def rtl(self, name: str, comment: str = ""):
        self.signatures[name] = RTL_ROUTINES[name][1]
        self.emit("CALL", SymRef(name), RTL_ROUTINES[name][2], comment=comment)

    def mark_global(self):
        """MARK for a call to an outermost-level routine (library or external)."""
        self.emit("MARK", self.level)

    # -- units -----------------------------------------------------------------
    def generate(self) -> ObjectModule:
        prog = self.program
        for v in self.info.globals:
            if not v.name.startswith("%"):
                self.variables.append(VarInfo(None, v.name.upper(), v.offset, v.type.size))
        self.routine_decls(prog.block)
        if prog.unit == "PROGRAM":
            start = len(self.code)
            self.level = 0
            self.temp_next = self.temp_max = FRAME_HEADER
            body = prog.block.body
            self.line = body.line
            enter = self.emit("ENTER", 0, comment="temporaries of the main program")
            self.statement(body)
            self.line = body.end_line or self.line
            self.emit("STOP", comment="end of program")
            enter.args[0] = self.temp_max - FRAME_HEADER
            self.routines.append(RoutineInfo(prog.name.upper(), start, len(self.code) - 1, 0))
            self.obj.transfer = start
        self.resolve()
        obj = self.obj
        obj.code = self.code
        obj.routines = sorted(self.routines, key=lambda r: r.start)
        obj.variables = self.variables
        obj.lines = line_table(self.code)
        for sym in self.info.exported_routines:
            obj.globals.append(Symbol(sym.ext_name, "ROUTINE", sym.label.addr, sym.signature()))
        for sym in self.info.exported_vars:
            obj.globals.append(Symbol(sym.ext_name, "DATA", sym.offset, sym.type.signature()))
        for name, sym in self.info.external_routines.items():
            self.signatures.setdefault(name, sym.signature())
        for name, sym in self.info.external_vars.items():
            self.signatures.setdefault(name, sym.type.signature())
        obj.collect_externals(self.signatures)
        return obj

    def resolve(self):
        for ins in self.code:
            for i, a in enumerate(ins.args):
                if isinstance(a, Label):
                    ins.args[i] = a.addr
                elif isinstance(a, RoutineSym):
                    ins.args[i] = a.label.addr

    def routine_decls(self, block: A.Block):
        for d in block.decls:
            if isinstance(d, A.RoutineDecl) and d.block is not None and isinstance(d.symbol, RoutineSym):
                self.routine(d)

    def routine(self, d: A.RoutineDecl):
        sym: RoutineSym = d.symbol
        if sym.external:
            return
        self.routine_decls(d.block)
        saved = (self.level, self.temp_next, self.temp_max)
        self.level = sym.level
        sym.label = sym.label or Label()
        self.place(sym.label)
        start = sym.label.addr
        first_temp = FRAME_HEADER + sym.param_cells + sym.local_cells
        self.temp_next = self.temp_max = first_temp
        self.line = d.line
        kind = "function" if sym.is_function else "procedure"
        enter = self.emit("ENTER", 0, comment=f"{kind} {sym.name.upper()}")
        self.statement(d.block.body)
        self.line = d.block.body.end_line or self.line
        if sym.is_function:
            self.emit("RETF", sym.result_offset, comment=f"return the value of {sym.name.upper()}")
        else:
            self.emit("RET")
        enter.args[0] = sym.local_cells + (self.temp_max - first_temp)
        self.routines.append(RoutineInfo(sym.name.upper(), start, len(self.code) - 1, sym.level))
        for v in getattr(sym, "locals", []):
            if not v.name.startswith("%"):
                self.variables.append(VarInfo(start, v.name.upper(), v.offset, 1 if v.by_ref else v.type.size))
        self.level, self.temp_next, self.temp_max = saved

    def ensure_label(self, sym: RoutineSym):
        if sym.label is None:
            sym.label = Label()
        return sym.label

    # -- variables -------------------------------------------------------------
    def frame_access(self, op_local: str, op_outer: str, level: int, offset: int, comment: str):
        if level == self.level:
            self.emit(op_local, offset, comment=comment)
        else:
            self.emit(op_outer, self.level - level, offset, comment=comment)

    def load_var(self, sym: VarSym):
        name = sym.name.upper()
        if sym.external:
            self.emit("LDG", SymRef(sym.ext_name), comment=name)
        elif sym.level == 0:
            self.emit("LDG", sym.offset, comment=name)
        else:
            self.frame_access("LDL", "LDI", sym.level, sym.offset, name)
            if sym.by_ref:
                self.emit("IND", comment=f"{name} is a VAR parameter")

    def store_var(self, sym: VarSym):
        name = sym.name.upper()
        if sym.external:
            self.emit("STG", SymRef(sym.ext_name), comment=name)
        elif sym.level == 0:
            self.emit("STG", sym.offset, comment=name)
        else:
            self.frame_access("STL", "STI", sym.level, sym.offset, name)

    def addr_var(self, sym: VarSym):
        name = sym.name.upper()
        if sym.external:
            self.emit("LAG", SymRef(sym.ext_name), comment=name)
        elif sym.level == 0:
            self.emit("LAG", sym.offset, comment=name)
        elif sym.by_ref:
            self.frame_access("LDL", "LDI", sym.level, sym.offset, f"address held in {name}")
        else:
            self.frame_access("LAL", "LAI", sym.level, sym.offset, name)

    def address(self, e: A.Expr):
        """Push the address of a variable reference."""
        if isinstance(e, A.Name):
            self.addr_var(e.symbol)
        elif isinstance(e, A.Index):
            self.address(e.base)
            t = e.base.type
            for idx in e.indexes:
                self.expr(idx)
                self.emit("INDEX", t.low, t.high, t.element.size)
                t = t.element
        elif isinstance(e, A.FieldRef):
            self.address(e.base)
            if e.field_offset:
                self.emit("OFFS", e.field_offset, comment=e.field_name.upper())
        else:
            raise AssertionError(f"not a variable: {e!r}")

    @staticmethod
    def string_constant(value: A.Expr) -> str | None:
        cv = getattr(value, "const_value", None)
        if isinstance(cv, str):
            return cv
        if isinstance(cv, int) and value.type is not None and value.type.base is T.CHAR:
            return chr(cv)
        return None

    def is_simple_var(self, e: A.Expr) -> bool:
        return isinstance(e, A.Name) and isinstance(e.symbol, VarSym) and not e.symbol.by_ref

    # -- expressions -----------------------------------------------------------
    def expr(self, e: A.Expr, want_real: bool = False):
        cv = getattr(e, "const_value", None)
        if cv is not None:
            if isinstance(cv, str):
                self.emit("LITS", cv)
            else:
                if want_real:
                    cv = float(cv)
                self.emit("LIT", cv)
            return
        self._expr(e)
        if want_real and T.is_integer(e.type):
            self.emit("FLT")

    def _expr(self, e: A.Expr):
        if isinstance(e, A.Name):
            sym = e.symbol
            if isinstance(sym, VarSym):
                self.load_var(sym)
            elif isinstance(sym, RoutineSym):
                self.call(sym, [])
            elif isinstance(sym, StdSym):
                self.std_function(e, sym, [])
            elif isinstance(sym, ConstSym):
                self.emit("LIT", sym.value)
            return
        if isinstance(e, (A.Index, A.FieldRef)):
            self.address(e)
            self.emit("IND")
            return
        if isinstance(e, A.FuncCall):
            if isinstance(e.symbol, RoutineSym):
                self.call(e.symbol, e.args)
            else:
                self.std_function(e, e.symbol, e.args)
            return
        if isinstance(e, A.Unary):
            if e.op == "NOT":
                self.expr(e.operand)
                self.emit("NOT")
            elif e.op == "-":
                self.expr(e.operand)
                self.emit("NEGI" if T.is_integer(e.type) else "NEGR")
            else:
                self.expr(e.operand)
            return
        if isinstance(e, A.Binary):
            self.binary(e)
            return
        raise AssertionError(f"cannot generate code for {e!r}")

    def binary(self, e: A.Binary):
        op = e.op
        if op in ("AND", "OR"):
            end = Label()
            self.expr(e.left)
            self.emit("DUP")
            self.emit("JPF" if op == "AND" else "JPT", end, comment=f"short-cut {op}")
            self.emit("POP")
            self.expr(e.right)
            self.place(end)
            return
        lt, rt = e.left.type, e.right.type
        n = getattr(e, "compare_length", None)
        if n is not None:
            for side in (e.left, e.right):
                text = self.string_constant(side)
                if text is not None:
                    self.emit("LITS", text.ljust(n))
                else:
                    self.address(side)
                    self.emit("LDSTR", n)
        real = (op == "/" or lt is T.REAL or rt is T.REAL) and T.is_numeric(lt) and T.is_numeric(rt)
        if n is None:
            self.expr(e.left)
            self.expr(e.right)
        if real:
            if T.is_integer(lt):
                self.emit("FLT2")
            if T.is_integer(rt):
                self.emit("FLT")
        ops = {
            "+": ("ADDI", "ADDR"), "-": ("SUBI", "SUBR"), "*": ("MULI", "MULR"), "/": ("DIVR", "DIVR"),
            "DIV": ("DIVI", "DIVI"), "MOD": ("MODI", "MODI"),
            "=": ("EQU", "EQU"), "<>": ("NEQ", "NEQ"), "<": ("LES", "LES"), "<=": ("LEQ", "LEQ"),
            ">": ("GRT", "GRT"), ">=": ("GEQ", "GEQ"),
        }
        self.emit(ops[op][1 if real else 0])

    def call(self, sym: RoutineSym, args: list[A.Expr]):
        name = sym.name.upper()
        self.emit("MARK", self.level - (sym.level - 1))
        for a, p in zip(args, sym.params):
            if p.by_ref:
                self.address(a)
            elif p.type.size > 1 or T.is_char_array(p.type):
                text = self.string_constant(a)
                if text is not None:
                    self.emit("LITS", text)
                    self.emit("SBLK", p.type.size)
                else:
                    self.address(a)
                    self.emit("LDBLK", p.type.size)
            else:
                self.expr(a, want_real=p.type is T.REAL)
                self.range_check(p.type, a)
        target = SymRef(sym.ext_name) if sym.external else self.ensure_label(sym)
        self.emit("CALL", target, sym.param_cells, comment=name)

    def range_check(self, target: T.Type, value: A.Expr):
        if not isinstance(target, T.SubrangeType):
            return
        vt = value.type
        if isinstance(vt, T.SubrangeType) and target.low <= vt.low and vt.high <= target.high:
            return
        cv = getattr(value, "const_value", None)
        if isinstance(cv, int) and target.low <= cv <= target.high:
            return
        self.emit("CHK", target.low, target.high, comment=f"range {target}")

    def std_function(self, e: A.Expr, sym: StdSym, args: list[A.Expr]):
        name = sym.name
        if name in ("EOF", "EOLN"):
            self.mark_global()
            self.rtl(f"PAS${name}")
            return
        if name == "RANDOM":
            self.mark_global()
            if args:
                self.expr(args[0])
                self.rtl("PAS$RANDOM", "RANDOM(n): 0..n-1")
            else:
                self.rtl("PAS$RANDOM_REAL")
            return
        a = args[0]
        at = a.type
        if name in ("SQRT", "SIN", "COS", "ARCTAN", "EXP", "LN"):
            self.mark_global()
            self.expr(a, want_real=True)
            self.rtl(f"PAS${name}")
            return
        self.expr(a)
        if name == "ABS":
            self.emit("ABSI" if T.is_integer(at) else "ABSR")
        elif name == "SQR":
            self.emit("SQRI" if T.is_integer(at) else "SQRR")
        elif name == "ODD":
            self.emit("ODD")
        elif name == "CHR":
            self.emit("CHR")
        elif name in ("SUCC", "PRED"):
            lo, hi = T.bounds(at.base)
            self.emit(name, lo, hi)
        elif name in ("TRUNC", "ROUND"):
            if at is T.REAL:
                self.emit(name)
        # ORD needs no code: ordinal values are already integers.

    # -- statements --------------------------------------------------------------
    def statement(self, s: A.Statement):
        if s.line:
            self.line = s.line
        if isinstance(s, A.Compound):
            for st in s.stmts:
                self.statement(st)
        elif isinstance(s, A.Assign):
            self.assignment(s)
        elif isinstance(s, A.ProcCall):
            self.proc_call(s)
        elif isinstance(s, A.If):
            self.if_statement(s)
        elif isinstance(s, A.While):
            top, end = Label(), Label()
            self.place(top)
            self.expr(s.cond)
            self.emit("JPF", end, comment="leave the WHILE loop")
            self.statement(s.body)
            self.line = s.line
            self.emit("JMP", top, comment="back to the WHILE test")
            self.place(end)
        elif isinstance(s, A.Repeat):
            top = Label()
            self.place(top)
            for st in s.body:
                self.statement(st)
            self.line = s.cond.line or self.line
            self.expr(s.cond)
            self.emit("JPF", top, comment="repeat UNTIL the condition is TRUE")
        elif isinstance(s, A.For):
            self.for_statement(s)
        elif isinstance(s, A.Case):
            self.case_statement(s)

    def if_statement(self, s: A.If):
        else_label, end = Label(), Label()
        self.expr(s.cond)
        self.emit("JPF", else_label if s.else_part is not None else end, comment="IF condition false")
        self.statement(s.then_part)
        if s.else_part is not None:
            self.emit("JMP", end, comment="skip the ELSE part")
            self.place(else_label)
            self.statement(s.else_part)
        self.place(end)

    def assignment(self, s: A.Assign):
        target = s.target
        if isinstance(target, A.Name) and isinstance(target.symbol, RoutineSym):
            sym = target.symbol
            self.expr(s.value, want_real=sym.result is T.REAL)
            self.range_check(sym.result, s.value)
            self.frame_access("STL", "STI", sym.level, sym.result_offset, f"result of {sym.name.upper()}")
            return
        self.assign_value(target, s.value)

    def assign_value(self, target: A.Expr, value: A.Expr):
        tt = target.type
        if tt.size > 1 or T.is_char_array(tt):
            self.address(target)
            text = self.string_constant(value)
            if text is not None:
                self.emit("LITS", text)
                self.emit("SMOVE", tt.size)
            else:
                self.address(value)
                self.emit("MOVE", tt.size)
            return
        if self.is_simple_var(target):
            self.expr(value, want_real=tt is T.REAL)
            self.range_check(tt, value)
            self.store_var(target.symbol)
        else:
            self.address(target)
            self.expr(value, want_real=tt is T.REAL)
            self.range_check(tt, value)
            self.emit("STO")

    def store_result_of(self, target: A.Expr, produce):
        """Store a value produced by ``produce()`` (e.g. a READ) into ``target``."""
        tt = target.type
        if self.is_simple_var(target):
            produce()
            if isinstance(tt, T.SubrangeType):
                self.emit("CHK", tt.low, tt.high, comment=f"range {tt}")
            self.store_var(target.symbol)
        else:
            self.address(target)
            produce()
            if isinstance(tt, T.SubrangeType):
                self.emit("CHK", tt.low, tt.high, comment=f"range {tt}")
            self.emit("STO")

    def proc_call(self, s: A.ProcCall):
        sym = s.symbol
        if isinstance(sym, RoutineSym):
            self.call(sym, s.args)
            return
        name = sym.name
        if name in ("WRITE", "WRITELN"):
            for a in s.io_args:
                self.write_arg(a)
            if name == "WRITELN":
                self.mark_global()
                self.rtl("PAS$WRITELN", "end the line")
        elif name in ("READ", "READLN"):
            for a in s.io_args:
                self.read_arg(a)
            if name == "READLN":
                self.mark_global()
                self.rtl("PAS$READLN", "skip to the next input line")
        elif name == "RANDOMIZE":
            self.mark_global()
            self.rtl("PAS$RANDOMIZE")
        elif name == "HALT":
            self.mark_global()
            self.rtl("PAS$HALT")

    def write_arg(self, a: A.Expr):
        value, width, prec = (a.value, a.width, a.precision) if isinstance(a, A.WriteArg) else (a, None, None)
        t = value.type

        def push_width(default: int):
            if width is not None:
                self.expr(width)
            else:
                self.emit("LIT", default, comment="default field width")

        self.mark_global()
        if T.is_char_array(t):
            self.address(value)
            self.emit("LIT", t.count)
            push_width(t.count)
            self.rtl("PAS$WRITE_CHARS")
        elif isinstance(t, T.StringType):
            self.expr(value)
            push_width(t.length)
            self.rtl("PAS$WRITE_STR")
        elif t is T.REAL:
            self.expr(value)
            push_width(DEFAULT_WIDTH["REAL"])
            if prec is not None:
                self.expr(prec)
            else:
                self.emit("LIT", -1, comment="no decimal places given: E notation")
            self.rtl("PAS$WRITE_REAL")
        elif t.base is T.BOOLEAN:
            self.expr(value)
            push_width(DEFAULT_WIDTH["BOOLEAN"])
            self.rtl("PAS$WRITE_BOOL")
        elif t.base is T.CHAR:
            self.expr(value)
            push_width(DEFAULT_WIDTH["CHAR"])
            self.rtl("PAS$WRITE_CHAR")
        elif isinstance(t.base, T.EnumType):
            self.expr(value)
            push_width(0)
            self.emit("LITS", ",".join(n.upper() for n in t.base.names))
            self.rtl("PAS$WRITE_ENUM")
        else:
            self.expr(value)
            push_width(DEFAULT_WIDTH["INTEGER"])
            self.rtl("PAS$WRITE_INT")

    def read_arg(self, a: A.Expr):
        t = a.type
        if T.is_char_array(t):
            self.mark_global()
            self.address(a)
            self.emit("LIT", t.count)
            self.rtl("PAS$READ_CHARS")
            return
        routine = "PAS$READ_REAL" if t is T.REAL else "PAS$READ_CHAR" if t.base is T.CHAR else "PAS$READ_INT"

        def produce():
            self.mark_global()
            self.rtl(routine, f"read {a.to_source()}")
        self.store_result_of(a, produce)

    def for_statement(self, s: A.For):
        sym: VarSym = s.var.symbol
        vt = sym.type
        start_t = self.alloc_temp()
        limit_t = self.alloc_temp()
        top, done = Label(), Label()
        self.expr(s.start)
        self.emit("STL", start_t, comment="FOR start value")
        self.expr(s.stop)
        self.emit("STL", limit_t, comment="FOR limit")
        self.emit("LDL", start_t)
        self.emit("LDL", limit_t)
        self.emit("LES" if s.down else "GRT")
        self.emit("JPT", done, comment="loop runs zero times")
        self.emit("LDL", start_t)
        if isinstance(vt, T.SubrangeType):
            self.emit("CHK", vt.low, vt.high, comment=f"range {vt}")
        self.store_var_any(s.var)
        if isinstance(vt, T.SubrangeType):
            self.emit("LDL", limit_t)
            self.emit("CHK", vt.low, vt.high, comment=f"range {vt}")
            self.emit("POP")
        self.place(top)
        self.statement(s.body)
        self.line = s.line
        self.load_var_any(s.var)
        self.emit("LDL", limit_t)
        self.emit("EQU")
        self.emit("JPT", done, comment="reached the limit")
        self.load_var_any(s.var)
        self.emit("LIT", 1)
        self.emit("SUBI" if s.down else "ADDI")
        self.store_var_any(s.var)
        self.emit("JMP", top, comment="next time round the FOR loop")
        self.place(done)
        self.free_temp()
        self.free_temp()

    def load_var_any(self, name: A.Name):
        self.load_var(name.symbol)

    def store_var_any(self, name: A.Name):
        sym = name.symbol
        if sym.by_ref:
            tmp = self.alloc_temp()
            self.emit("STL", tmp)
            self.addr_var(sym)
            self.emit("LDL", tmp)
            self.emit("STO")
            self.free_temp()
        else:
            self.store_var(sym)

    def case_statement(self, s: A.Case):
        tmp = self.alloc_temp()
        self.expr(s.selector)
        self.emit("STL", tmp, comment="CASE selector")
        end = Label()
        arm_labels = []
        for arm in s.arms:
            lab = Label()
            arm_labels.append(lab)
            for lo, hi in getattr(arm, "values", []):
                self.emit("LDL", tmp)
                if lo == hi:
                    self.emit("LIT", lo)
                    self.emit("EQU")
                else:
                    self.emit("LIT", lo)
                    self.emit("GEQ")
                    self.emit("LDL", tmp)
                    self.emit("LIT", hi)
                    self.emit("LEQ")
                    self.emit("AND")
                self.emit("JPT", lab)
        if s.otherwise is not None:
            for st in s.otherwise:
                self.statement(st)
            self.line = s.line
            self.emit("JMP", end)
        else:
            self.emit("LDL", tmp)
            self.emit("CASERR", comment="no CASE label matched")
        for arm, lab in zip(s.arms, arm_labels):
            self.place(lab)
            self.statement(arm.body)
            self.emit("JMP", end)
        self.place(end)
        self.free_temp()


def generate(program: A.Program, info: UnitInfo, source: str, created: str) -> ObjectModule:
    return CodeGen(program, info, source, created).generate()

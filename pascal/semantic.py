"""Semantic analysis: symbol tables, type checking and storage allocation.

The analyser walks the AST from the parser, reports VMS-style
diagnostics, and annotates the tree for the code generator:

* expression nodes get ``type`` (and ``const_value`` when known at compile time)
* names and calls get ``symbol``
* routine declarations get ``symbol`` (a :class:`RoutineSym`)

Storage: level-0 variables live in the module's static data area; the
variables and parameters of a routine live in its stack frame, starting
at offset 3 (cells 0-2 are the frame header: static link, dynamic link,
return address).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import astnodes as A
from . import types as T
from .messages import Diagnostic, diag

FRAME_HEADER = 3


# ----------------------------------------------------------------------
# Symbols
# ----------------------------------------------------------------------

class Symbol:
    what = "name"

    def __init__(self, name: str, line: int = 0):
        self.name = name
        self.line = line


class ConstSym(Symbol):
    what = "constant"

    def __init__(self, name, type_, value, line=0):
        super().__init__(name, line)
        self.type = type_
        self.value = value


class TypeSym(Symbol):
    what = "type"

    def __init__(self, name, type_, line=0):
        super().__init__(name, line)
        self.type = type_


class VarSym(Symbol):
    what = "variable"

    def __init__(self, name, type_, level, offset, *, by_ref=False, is_param=False, line=0):
        super().__init__(name, line)
        self.type = type_
        self.level = level
        self.offset = offset
        self.by_ref = by_ref
        self.is_param = is_param
        self.external = False
        self.exported = False

    @property
    def ext_name(self):
        return self.name.upper()


@dataclass
class Param:
    name: str
    type: T.Type
    by_ref: bool


class RoutineSym(Symbol):
    def __init__(self, name, is_function, params, result, level, line=0):
        super().__init__(name, line)
        self.is_function = is_function
        self.params: list[Param] = params
        self.result: T.Type | None = result
        self.level = level            # nesting level of the routine's body (1 = outermost routine)
        self.external = False
        self.exported = False
        self.forward = False
        self.result_offset = None
        self.result_assigned = False
        self.local_cells = 0          # cells allocated by ENTER (result slot + locals)
        self.node: A.RoutineDecl | None = None
        self.label = None             # set by the code generator

    @property
    def what(self):
        return "function" if self.is_function else "procedure"

    @property
    def ext_name(self):
        return self.name.upper()

    @property
    def param_cells(self):
        return sum(1 if p.by_ref else p.type.size for p in self.params)

    def signature(self) -> str:
        parts = ",".join(("VAR " if p.by_ref else "") + p.type.signature() for p in self.params)
        s = ("FUNCTION" if self.is_function else "PROCEDURE") + (f"({parts})" if parts else "")
        if self.is_function and self.result is not None:
            s += ":" + self.result.signature()
        return s


class StdSym(Symbol):
    def __init__(self, name, is_function):
        super().__init__(name)
        self.is_function = is_function

    @property
    def what(self):
        return "standard function" if self.is_function else "standard procedure"


class FileSym(Symbol):
    what = "file"


class ErrorSym(Symbol):
    what = "name"


STD_PROCEDURES = ["WRITE", "WRITELN", "READ", "READLN", "RANDOMIZE", "HALT"]
STD_FUNCTIONS = ["ABS", "SQR", "ODD", "ORD", "CHR", "SUCC", "PRED", "TRUNC", "ROUND",
                 "SQRT", "SIN", "COS", "ARCTAN", "EXP", "LN", "EOF", "EOLN", "RANDOM"]
MATH_FUNCTIONS = {"SQRT", "SIN", "COS", "ARCTAN", "EXP", "LN"}


class Scope:
    def __init__(self, parent: "Scope | None", level: int, routine: RoutineSym | None = None):
        self.parent = parent
        self.level = level
        self.routine = routine
        self.syms: dict[str, Symbol] = {}
        self.next_offset = FRAME_HEADER

    def lookup(self, name: str) -> Symbol | None:
        key = name.upper()
        s = self
        while s is not None:
            if key in s.syms:
                return s.syms[key]
            s = s.parent
        return None


def std_scope() -> Scope:
    sc = Scope(None, -1)
    for name, t in (("INTEGER", T.INTEGER), ("REAL", T.REAL), ("BOOLEAN", T.BOOLEAN), ("CHAR", T.CHAR)):
        sc.syms[name] = TypeSym(name, t)
    sc.syms["TRUE"] = ConstSym("TRUE", T.BOOLEAN, 1)
    sc.syms["FALSE"] = ConstSym("FALSE", T.BOOLEAN, 0)
    sc.syms["MAXINT"] = ConstSym("MAXINT", T.INTEGER, T.MAXINT)
    for name in STD_PROCEDURES:
        sc.syms[name] = StdSym(name, False)
    for name in STD_FUNCTIONS:
        sc.syms[name] = StdSym(name, True)
    for name in ("INPUT", "OUTPUT"):
        sc.syms[name] = FileSym(name)
    return sc


@dataclass
class UnitInfo:
    """What the code generator needs to know about a compiled unit."""
    name: str
    kind: str                         # "PROGRAM" or "MODULE"
    data_size: int = 0
    routines: list[RoutineSym] = field(default_factory=list)
    exported_vars: list[VarSym] = field(default_factory=list)
    exported_routines: list[RoutineSym] = field(default_factory=list)
    external_vars: dict[str, VarSym] = field(default_factory=dict)
    external_routines: dict[str, RoutineSym] = field(default_factory=dict)
    globals: list[VarSym] = field(default_factory=list)


def _fold_binary(op, a, b, result_type):
    try:
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return a / b if b != 0 else None
        if op == "DIV":
            if b == 0:
                return None
            q = abs(a) // abs(b)
            return q if (a < 0) == (b < 0) else -q
        if op == "MOD":
            if b == 0:
                return None
            r = abs(a) % abs(b)
            return r if a >= 0 else -r
        if op == "AND":
            return 1 if (a and b) else 0
        if op == "OR":
            return 1 if (a or b) else 0
        cmp = {"=": a == b, "<>": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}
        if op in cmp:
            return 1 if cmp[op] else 0
    except TypeError:
        return None
    return None


class Analyzer:
    def __init__(self, filename: str = "<buffer>"):
        self.filename = filename
        self.diagnostics: list[Diagnostic] = []
        self.std = std_scope()
        self.info: UnitInfo | None = None

    # -- helpers ---------------------------------------------------------------
    def error(self, ident: str, node: A.Node | None, **args):
        line = node.line if node is not None and node.line else None
        col = node.column if node is not None and node.column else None
        end = node.end_column if node is not None and node.end_line == node.line else None
        self.diagnostics.append(diag("PASCAL", ident, file=self.filename, line=line, column=col,
                                     end_column=end, **args))

    def declare(self, scope: Scope, name: str, sym: Symbol, node: A.Node):
        if name.startswith("%"):
            return
        key = name.upper()
        old = scope.syms.get(key)
        if old is not None and not isinstance(old, ErrorSym):
            self.error("MULDECL", node, name=name, first_line=old.line or None)
            return
        sym.line = node.line
        scope.syms[key] = sym

    def lookup(self, scope: Scope, name: str, node: A.Node) -> Symbol | None:
        sym = scope.lookup(name)
        if sym is None:
            if name.upper() == "STRING":
                self.error("NOTSUPP", node, feature="the STRING type (use PACKED ARRAY [1..n] OF CHAR)")
            else:
                self.error("UNDECLID", node, name=name)
            scope.syms[name.upper()] = ErrorSym(name)
            return None
        if isinstance(sym, ErrorSym):
            return None
        return sym

    # -- units and blocks ------------------------------------------------------
    def analyze(self, program: A.Program) -> UnitInfo:
        self.info = UnitInfo(name=program.name.upper(), kind=program.unit)
        for p in program.params:
            if p.upper() not in ("INPUT", "OUTPUT") and not p.startswith("%"):
                self.error("PROGPARAM", program, name=p)
        scope = Scope(self.std, 0)
        self.block(program.block, scope)
        return self.info

    def block(self, block: A.Block, scope: Scope):
        for d in block.decls:
            if isinstance(d, A.ConstDecl):
                self.const_decl(d, scope)
            elif isinstance(d, A.TypeDecl):
                t = self.resolve_type(d.spec, scope)
                if not T.is_error(t) and t.decl_name is None and not isinstance(t, type(T.INTEGER)):
                    t.decl_name = d.name
                self.declare(scope, d.name, TypeSym(d.name, t), d)
            elif isinstance(d, A.VarDecl):
                self.var_decl(d, scope)
            elif isinstance(d, A.RoutineDecl):
                self.routine_decl(d, scope)
        for sym in scope.syms.values():
            if isinstance(sym, RoutineSym) and sym.forward:
                self.error("FWDNOTDEF", sym.node, name=sym.name)
                sym.forward = False
        if block.body is not None:
            self.statement(block.body, scope)

    def const_decl(self, d: A.ConstDecl, scope: Scope):
        t = self.expr(d.value, scope)
        value = getattr(d.value, "const_value", None)
        if value is None and not T.is_error(t):
            self.error("CONSTEXPR", d.value)
            t = T.ERROR
        self.declare(scope, d.name, ConstSym(d.name, t, value), d)

    def var_decl(self, d: A.VarDecl, scope: Scope):
        t = self.resolve_type(d.spec, scope)
        external = exported = False
        for attr in d.attributes:
            if attr in ("GLOBAL", "EXTERNAL"):
                if scope.level != 0:
                    self.error("ATTRLEVEL", d, attr=attr)
                    continue
                if attr == "GLOBAL":
                    exported = True
                else:
                    external = True
            else:
                self.error("BADATTR", d, attr=attr)
        for name in d.names:
            if scope.level == 0:
                sym = VarSym(name, t, 0, None if external else self.info.data_size)
                if not external:
                    self.info.data_size += t.size
                    self.info.globals.append(sym)
            else:
                sym = VarSym(name, t, scope.level, scope.next_offset)
                scope.next_offset += t.size
            sym.external = external
            sym.exported = exported and not external
            self.declare(scope, name, sym, d)
            if sym.external and not name.startswith("%"):
                self.info.external_vars[sym.ext_name] = sym
            if sym.exported and not name.startswith("%"):
                self.info.exported_vars.append(sym)

    def routine_decl(self, d: A.RoutineDecl, scope: Scope):
        level = scope.level + 1
        attrs = []
        for attr in d.attributes:
            if attr in ("GLOBAL", "EXTERNAL"):
                if scope.level != 0:
                    self.error("ATTRLEVEL", d, attr=attr)
                else:
                    attrs.append(attr)
            else:
                self.error("BADATTR", d, attr=attr)
        if d.directive == "EXTERNAL" and scope.level != 0:
            self.error("ATTRLEVEL", d, attr="EXTERNAL")
        external = "EXTERNAL" in attrs or (d.directive == "EXTERNAL" and scope.level == 0)
        if external and d.block is not None:
            self.error("EXTBODY", d, name=d.name)

        existing = scope.syms.get(d.name.upper())
        if (isinstance(existing, RoutineSym) and existing.forward
                and existing.is_function == d.is_function and d.directive is None):
            sym = existing
            sym.forward = False
            if d.has_params or d.result is not None:
                params, result = self.resolve_heading(d, scope)
                same = (len(params) == len(sym.params)
                        and all(p.by_ref == q.by_ref and T.same_type(p.type, q.type)
                                for p, q in zip(params, sym.params))
                        and (result is None or sym.result is None or T.same_type(result, sym.result)))
                if not same:
                    self.error("HEADMISMAT", d, name=d.name)
        else:
            params, result = self.resolve_heading(d, scope)
            if d.is_function and result is None:
                self.error("SYMEXP", d, expected=":")
                result = T.ERROR
            sym = RoutineSym(d.name, d.is_function, params, result, level)
            sym.node = d
            self.declare(scope, d.name, sym, d)
            if d.directive == "FORWARD":
                sym.forward = True
                d.symbol = sym
                return
        d.symbol = sym
        if external:
            sym.external = True
            self.info.external_routines[sym.ext_name] = sym
            return
        if d.block is None:
            return
        if "GLOBAL" in attrs:
            sym.exported = True
            self.info.exported_routines.append(sym)

        inner = Scope(scope, level, routine=sym)
        for p in sym.params:
            v = VarSym(p.name, p.type, level, inner.next_offset, by_ref=p.by_ref, is_param=True)
            inner.next_offset += 1 if p.by_ref else p.type.size
            self.declare(inner, p.name, v, d)
        first_local = inner.next_offset
        if sym.is_function:
            sym.result_offset = inner.next_offset
            inner.next_offset += 1
        self.info.routines.append(sym)
        sym.result_assigned = False
        self.block(d.block, inner)
        sym.local_cells = inner.next_offset - first_local
        sym.locals = [s for s in inner.syms.values() if isinstance(s, VarSym)]
        if sym.is_function and not sym.result_assigned and not d.name.startswith("%"):
            self.error("NORESULT", d, name=d.name)

    def resolve_heading(self, d: A.RoutineDecl, scope: Scope):
        params = []
        for group in d.params:
            t = self.resolve_type(group.spec, scope)
            for name in group.names:
                params.append(Param(name, t, group.by_ref))
        result = None
        if d.is_function and d.result is not None:
            result = self.resolve_type(d.result, scope)
            if not T.is_error(result) and not (result.is_ordinal or result is T.REAL):
                self.error("FUNCTYPE", d.result, type=str(result))
                result = T.ERROR
        return params, result

    # -- types -----------------------------------------------------------------
    def resolve_type(self, spec: A.TypeSpec, scope: Scope) -> T.Type:
        if isinstance(spec, A.NamedType):
            sym = self.lookup(scope, spec.name, spec)
            if sym is None:
                return T.ERROR
            if not isinstance(sym, TypeSym):
                self.error("NOTTYPE", spec, name=spec.name, what=sym.what)
                return T.ERROR
            return sym.type
        if isinstance(spec, A.SubrangeType):
            lo_t = self.expr(spec.low, scope)
            hi_t = self.expr(spec.high, scope)
            lo = getattr(spec.low, "const_value", None)
            hi = getattr(spec.high, "const_value", None)
            if T.is_error(lo_t) or T.is_error(hi_t):
                return T.ERROR
            if lo is None or hi is None:
                self.error("CONSTEXPR", spec.low if lo is None else spec.high)
                return T.ERROR
            if not lo_t.is_ordinal or not hi_t.is_ordinal:
                self.error("NOTORDINAL", spec, what="a range bound", type=str(lo_t if not lo_t.is_ordinal else hi_t))
                return T.ERROR
            if lo_t.base is not hi_t.base:
                self.error("INCOMPTYPES", spec, op="..", left=str(lo_t), right=str(hi_t))
                return T.ERROR
            if lo > hi:
                self.error("BADRANGE", spec, low=T.format_ordinal(lo, lo_t), high=T.format_ordinal(hi, lo_t))
                return T.ERROR
            return T.SubrangeType(lo_t.base, lo, hi)
        if isinstance(spec, A.EnumType):
            et = T.EnumType(spec.names)
            for i, name in enumerate(spec.names):
                self.declare(scope, name, ConstSym(name, et, i), spec)
            return et
        if isinstance(spec, A.ArrayType):
            idx_types = []
            for ispec in spec.indexes:
                it = self.resolve_type(ispec, scope)
                if not T.is_error(it) and not it.is_ordinal:
                    self.error("NOTORDINAL", ispec, what="an array index type", type=str(it))
                    it = T.ERROR
                elif not T.is_error(it):
                    lo, hi = T.bounds(it)
                    if hi - lo + 1 > 1_000_000:
                        self.error("NOTSUPP", ispec, feature=f"an array index range as large as {it}")
                        it = T.ERROR
                idx_types.append(it)
            elem = self.resolve_type(spec.element, scope)
            if any(T.is_error(t) for t in idx_types) or T.is_error(elem):
                return T.ERROR
            t = elem
            for it in reversed(idx_types):
                t = T.ArrayType(it, t)
            if t.size > 1_000_000:
                self.error("NOTSUPP", spec, feature="arrays with more than 1000000 elements")
                return T.ERROR
            return t
        if isinstance(spec, A.RecordType):
            rt = T.RecordType()
            for fd in spec.fields:
                ft = self.resolve_type(fd.spec, scope)
                for name in fd.names:
                    if name.upper() in rt.fields:
                        self.error("MULDECL", fd, name=name)
                    elif not name.startswith("%"):
                        rt.add_field(name, ft)
            return rt
        return T.ERROR

    # -- statements --------------------------------------------------------------
    def statement(self, s: A.Statement, scope: Scope):
        if isinstance(s, A.Compound):
            for st in s.stmts:
                self.statement(st, scope)
        elif isinstance(s, A.Assign):
            self.assignment(s, scope)
        elif isinstance(s, A.ProcCall):
            self.proc_call(s, scope)
        elif isinstance(s, A.If):
            self.condition(s.cond, scope)
            self.statement(s.then_part, scope)
            if s.else_part is not None:
                self.statement(s.else_part, scope)
        elif isinstance(s, A.While):
            self.condition(s.cond, scope)
            self.statement(s.body, scope)
        elif isinstance(s, A.Repeat):
            for st in s.body:
                self.statement(st, scope)
            self.condition(s.cond, scope)
        elif isinstance(s, A.For):
            self.for_statement(s, scope)
        elif isinstance(s, A.Case):
            self.case_statement(s, scope)

    def condition(self, e: A.Expr, scope: Scope):
        t = self.expr(e, scope)
        if not T.is_error(t) and t.base is not T.BOOLEAN:
            example = "count > 0"
            if isinstance(e, A.Binary) and e.op in ("AND", "OR"):
                example = f"(...) {e.op} (...)"
            elif isinstance(e, A.Name):
                example = f"{e.name} > 0"
            self.error("NOTBOOL", e, type=str(t), example=example)

    def enclosing_function(self, sym: RoutineSym, scope: Scope) -> bool:
        s = scope
        while s is not None:
            if s.routine is sym:
                return True
            s = s.parent
        return False

    def assignment(self, s: A.Assign, scope: Scope):
        target = s.target
        if isinstance(target, A.Name):
            sym = scope.lookup(target.name)
            if isinstance(sym, RoutineSym) and sym.is_function and self.enclosing_function(sym, scope):
                target.symbol = sym
                target.type = sym.result
                sym.result_assigned = True
                vt = self.expr(s.value, scope)
                self.check_assign(sym.result, vt, s.value, s, target.name)
                return
        tt = self.designator(target, scope, purpose="assign")
        vt = self.expr(s.value, scope)
        self.check_assign(tt, vt, s.value, s, A.unparse(target))

    def check_assign(self, tt: T.Type, vt: T.Type, value: A.Expr, node: A.Node, target_name: str) -> bool:
        if T.is_error(tt) or T.is_error(vt):
            return True
        problem = self.assign_problem(tt, vt, value)
        if problem is None:
            return True
        ident, args = problem
        self.error(ident, node if ident not in ("OUTOFRANGE", "STRLENGTH") else value,
                   target_name=target_name, **args)
        return False

    def assign_problem(self, tt: T.Type, vt: T.Type, value: A.Expr | None):
        """None if a value of type vt may be assigned to type tt, else (ident, args)."""
        if tt is T.REAL and (vt is T.REAL or T.is_integer(vt)):
            return None
        if tt.is_ordinal and vt.is_ordinal and tt.base is vt.base:
            cv = getattr(value, "const_value", None) if value is not None else None
            if isinstance(cv, int) and isinstance(tt, T.SubrangeType) and not (tt.low <= cv <= tt.high):
                return ("OUTOFRANGE", dict(value=T.format_ordinal(cv, tt),
                                           low=T.format_ordinal(tt.low, tt),
                                           high=T.format_ordinal(tt.high, tt)))
            return None
        if T.is_char_array(tt) and isinstance(vt, T.StringType):
            if vt.length > tt.count:
                return ("STRLENGTH", dict(length=vt.length, type=str(tt)))
            return None
        if T.is_char_array(tt) and vt.base is T.CHAR and tt.count >= 1 and isinstance(value, A.StrLit):
            return None
        if isinstance(tt, T.ArrayType) and isinstance(vt, T.ArrayType) and T.same_type(tt, vt):
            return None
        if isinstance(tt, T.RecordType) and tt is vt:
            return None
        if T.is_integer(tt) and vt is T.REAL:
            return ("REALINT", {})
        return ("INCASSIGN", dict(source=str(vt), target=str(tt)))

    def for_statement(self, s: A.For, scope: Scope):
        vt = T.ERROR
        if isinstance(s.var, A.Name):
            sym = self.lookup(scope, s.var.name, s.var)
            if sym is not None:
                if isinstance(sym, VarSym) and (sym.type.is_ordinal or T.is_error(sym.type)):
                    vt = sym.type
                    s.var.symbol = sym
                    s.var.type = vt
                else:
                    self.error("FORVAR", s.var)
        for e in (s.start, s.stop):
            et = self.expr(e, scope)
            if not T.is_error(vt) and not T.is_error(et):
                problem = self.assign_problem(vt, et, e)
                if problem is not None and problem[0] != "OUTOFRANGE":
                    self.error("INCASSIGN", e, source=str(et), target=str(vt), target_name=s.var.name)
        self.statement(s.body, scope)

    def case_statement(self, s: A.Case, scope: Scope):
        st = self.expr(s.selector, scope)
        if not T.is_error(st) and not st.is_ordinal:
            self.error("NOTORDINAL", s.selector, what="a CASE selector", type=str(st))
            st = T.ERROR
        seen: dict[int, A.Node] = {}
        for arm in s.arms:
            values = []
            for lab in arm.labels:
                if isinstance(lab, A.CaseRange):
                    lo = self.case_label_value(lab.low, st, scope)
                    hi = self.case_label_value(lab.high, st, scope)
                    if lo is not None and hi is not None:
                        if lo > hi:
                            self.error("BADRANGE", lab, low=T.format_ordinal(lo, st), high=T.format_ordinal(hi, st))
                        else:
                            values.append((lo, hi))
                else:
                    v = self.case_label_value(lab, st, scope)
                    if v is not None:
                        values.append((v, v))
            for lo, hi in values:
                for v in range(lo, min(hi, lo + 10000) + 1):
                    if v in seen:
                        self.error("DUPCASE", arm, label=T.format_ordinal(v, st))
                        break
                    seen[v] = arm
            arm.values = values
            self.statement(arm.body, scope)
        if s.otherwise is not None:
            for stmt in s.otherwise:
                self.statement(stmt, scope)

    def case_label_value(self, e: A.Expr, st: T.Type, scope: Scope):
        t = self.expr(e, scope)
        if T.is_error(t):
            return None
        v = getattr(e, "const_value", None)
        if v is None:
            self.error("CONSTEXPR", e)
            return None
        if not T.is_error(st) and (not t.is_ordinal or t.base is not st.base):
            self.error("CASETYPE", e)
            return None
        return v

    # -- calls -------------------------------------------------------------------
    def proc_call(self, s: A.ProcCall, scope: Scope):
        if s.name.startswith("%"):
            return
        sym = self.lookup(scope, s.name, s)
        if sym is None:
            for a in s.args:
                self.expr(a, scope)
            return
        s.symbol = sym
        if isinstance(sym, StdSym) and not sym.is_function:
            self.std_procedure(s, sym, scope)
        elif isinstance(sym, RoutineSym) and not sym.is_function:
            self.check_args(sym, s.args, s, scope)
        elif isinstance(sym, (RoutineSym, StdSym)):
            self.error("FUNCSTMT", s, name=s.name)
        else:
            self.error("NOTPROC", s, name=s.name, what=sym.what)

    def root_symbol(self, e: A.Expr, scope: Scope):
        while isinstance(e, (A.Index, A.FieldRef)):
            e = e.base
        if isinstance(e, A.Name):
            return scope.lookup(e.name)
        return None

    def check_args(self, sym: RoutineSym, args: list[A.Expr], node: A.Node, scope: Scope):
        if len(args) != len(sym.params):
            self.error("ARGCOUNT", node, name=sym.name, expected=len(sym.params), found=len(args))
        for i, a in enumerate(args):
            if isinstance(a, A.WriteArg):
                self.error("WIDTHUSE", a)
                a = a.value
            if i >= len(sym.params):
                self.expr(a, scope)
                continue
            p = sym.params[i]
            if p.by_ref:
                if isinstance(a, A.PlaceholderExpr):
                    continue
                root = self.root_symbol(a, scope)
                if not isinstance(a, (A.Name, A.Index, A.FieldRef)) or not isinstance(root, (VarSym, ErrorSym, type(None))):
                    self.expr(a, scope)
                    self.error("VARARG", a, n=i + 1, name=sym.name)
                    continue
                at = self.designator(a, scope, purpose="var")
                if not T.is_error(at) and not T.is_error(p.type) and not T.same_type(at, p.type):
                    self.error("VARTYPE", a, n=i + 1, name=sym.name, found=str(at), expected=str(p.type))
            else:
                at = self.expr(a, scope)
                if T.is_error(at) or T.is_error(p.type):
                    continue
                problem = self.assign_problem(p.type, at, a)
                if problem is not None:
                    if problem[0] == "OUTOFRANGE":
                        self.error("OUTOFRANGE", a, **problem[1])
                    else:
                        self.error("ARGTYPE", a, n=i + 1, name=sym.name, found=str(at), expected=str(p.type))

    def skip_file_arg(self, args: list[A.Expr], file_name: str, scope: Scope) -> list[A.Expr]:
        if args and isinstance(args[0], A.Name):
            sym = scope.lookup(args[0].name)
            if isinstance(sym, FileSym):
                if sym.name != file_name:
                    self.error("BADUSE", args[0], name=args[0].name, what="file")
                args[0].symbol = sym
                return args[1:]
        return args

    def std_procedure(self, s: A.ProcCall, sym: StdSym, scope: Scope):
        name = sym.name
        if name in ("WRITE", "WRITELN"):
            args = self.skip_file_arg(s.args, "OUTPUT", scope)
            s.io_args = args
            if name == "WRITE" and not args:
                self.error("ARGCOUNT", s, name=name, expected="at least 1", found=0)
            for a in args:
                self.write_arg(a, scope)
        elif name in ("READ", "READLN"):
            args = self.skip_file_arg(s.args, "INPUT", scope)
            s.io_args = args
            if name == "READ" and not args:
                self.error("ARGCOUNT", s, name=name, expected="at least 1", found=0)
            for i, a in enumerate(args):
                if isinstance(a, A.PlaceholderExpr):
                    continue
                if isinstance(a, A.WriteArg):
                    self.error("WIDTHUSE", a)
                    continue
                root = self.root_symbol(a, scope)
                if not isinstance(a, (A.Name, A.Index, A.FieldRef)) or not isinstance(root, (VarSym, ErrorSym, type(None))):
                    self.expr(a, scope)
                    self.error("VARARG", a, n=i + 1, name=name)
                    continue
                t = self.designator(a, scope, purpose="read")
                if T.is_error(t):
                    continue
                if not (T.is_integer(t) or t is T.REAL or t.base is T.CHAR or T.is_char_array(t)):
                    self.error("READTYPE", a, type=str(t))
        else:   # RANDOMIZE, HALT
            if s.args:
                self.error("ARGCOUNT", s, name=name, expected=0, found=len(s.args))
                for a in s.args:
                    self.expr(a, scope)

    def write_arg(self, a: A.Expr, scope: Scope):
        value = a.value if isinstance(a, A.WriteArg) else a
        t = self.expr(value, scope)
        if isinstance(a, A.WriteArg):
            a.type = t
            for part in (a.width, a.precision):
                if part is not None:
                    pt = self.expr(part, scope)
                    if not T.is_error(pt) and not T.is_integer(pt):
                        self.error("WIDTHTYPE", part)
            if a.precision is not None and not T.is_error(t) and t is not T.REAL:
                self.error("PRECREAL", a.precision)
        if T.is_error(t):
            return
        if not (t.is_ordinal or t is T.REAL or isinstance(t, T.StringType) or T.is_char_array(t)):
            self.error("WRITETYPE", value, type=str(t))

    def std_function(self, e: A.Expr, sym: StdSym, args: list[A.Expr], scope: Scope) -> T.Type:
        name = sym.name
        if name in ("EOF", "EOLN"):
            args = self.skip_file_arg(args, "INPUT", scope)
            e.io_args = args
            if args:
                self.error("ARGCOUNT", e, name=name, expected=0, found=len(args))
            return T.BOOLEAN
        if name == "RANDOM":
            if not args:
                return T.REAL
            if len(args) > 1:
                self.error("ARGCOUNT", e, name=name, expected=1, found=len(args))
            at = self.expr(args[0], scope)
            if not T.is_error(at) and not T.is_integer(at):
                self.error("ARGTYPE", args[0], n=1, name=name, found=str(at), expected="INTEGER")
            return T.INTEGER
        if len(args) != 1:
            self.error("ARGCOUNT", e, name=name, expected=1, found=len(args))
            for a in args:
                self.expr(a, scope)
            return T.ERROR
        a = args[0]
        if isinstance(a, A.WriteArg):
            self.error("WIDTHUSE", a)
            return T.ERROR
        at = self.expr(a, scope)
        if T.is_error(at):
            return T.ERROR
        cv = getattr(a, "const_value", None)

        def bad(expected):
            self.error("ARGTYPE", a, n=1, name=name, found=str(at), expected=expected)
            return T.ERROR

        if name in ("ABS", "SQR"):
            if T.is_integer(at):
                if isinstance(cv, int):
                    e.const_value = abs(cv) if name == "ABS" else cv * cv
                return T.INTEGER
            if at is T.REAL:
                return T.REAL
            return bad("INTEGER or REAL")
        if name == "ODD":
            if not T.is_integer(at):
                return bad("INTEGER")
            if isinstance(cv, int):
                e.const_value = cv % 2
            return T.BOOLEAN
        if name == "ORD":
            if not at.is_ordinal:
                return bad("an ordinal value (INTEGER, CHAR, BOOLEAN)")
            if isinstance(cv, int):
                e.const_value = cv
            return T.INTEGER
        if name == "CHR":
            if not T.is_integer(at):
                return bad("INTEGER")
            if isinstance(cv, int) and 0 <= cv <= 255:
                e.const_value = cv
            return T.CHAR
        if name in ("SUCC", "PRED"):
            if not at.is_ordinal:
                return bad("an ordinal value (INTEGER, CHAR, BOOLEAN)")
            if isinstance(cv, int):
                v = cv + (1 if name == "SUCC" else -1)
                lo, hi = T.bounds(at.base)
                if lo <= v <= hi:
                    e.const_value = v
            return at.base
        if name in ("TRUNC", "ROUND"):
            if not (at is T.REAL or T.is_integer(at)):
                return bad("REAL")
            return T.INTEGER
        if name in MATH_FUNCTIONS:
            if not T.is_numeric(at):
                return bad("INTEGER or REAL")
            return T.REAL
        return T.ERROR

    # -- expressions ---------------------------------------------------------------
    def designator(self, e: A.Expr, scope: Scope, purpose: str = "value") -> T.Type:
        """Type of a variable reference; reports an error if ``e`` is not a variable."""
        if isinstance(e, A.PlaceholderExpr):
            e.type = T.ERROR
            return T.ERROR
        if isinstance(e, A.Name):
            sym = self.lookup(scope, e.name, e)
            if sym is None:
                e.type = T.ERROR
                return T.ERROR
            e.symbol = sym
            if isinstance(sym, VarSym):
                e.type = sym.type
                return sym.type
            if purpose in ("assign", "read", "var"):
                self.error("NOTVAR", e, name=e.name, what=sym.what)
                e.type = T.ERROR
                return T.ERROR
            return self.expr(e, scope)
        if isinstance(e, A.Index):
            bt = self.designator(e.base, scope, purpose)
            t = bt
            for idx in e.indexes:
                it = self.expr(idx, scope)
                if T.is_error(t):
                    continue
                if not isinstance(t, T.ArrayType):
                    if t is bt:
                        self.error("NOTARRAY", e.base, what=f'"{A.unparse(e.base)}"')
                    else:
                        self.error("INDEXCOUNT", idx)
                    t = T.ERROR
                    continue
                if not T.is_error(it):
                    if not it.is_ordinal or it.base is not t.index.base:
                        self.error("INDEXTYPE", idx, expected=str(t.index), found=str(it))
                    else:
                        cv = getattr(idx, "const_value", None)
                        if isinstance(cv, int) and not (t.low <= cv <= t.high):
                            self.error("OUTOFRANGE", idx, value=T.format_ordinal(cv, t.index),
                                       low=T.format_ordinal(t.low, t.index),
                                       high=T.format_ordinal(t.high, t.index))
                t = t.element
            e.type = t
            return t
        if isinstance(e, A.FieldRef):
            bt = self.designator(e.base, scope, purpose)
            if T.is_error(bt):
                e.type = T.ERROR
                return T.ERROR
            if not isinstance(bt, T.RecordType):
                self.error("NOTRECORD", e, what=f'"{A.unparse(e.base)}"', field=e.field_name)
                e.type = T.ERROR
                return T.ERROR
            f = bt.fields.get(e.field_name.upper())
            if f is None:
                self.error("NOFIELD", e, field=e.field_name)
                e.type = T.ERROR
                return T.ERROR
            e.field_offset = f[1]
            e.type = f[2]
            return f[2]
        if purpose in ("assign", "read"):
            self.expr(e, scope)
            self.error("NOTVAR", e, name=A.unparse(e), what="calculated value")
            e.type = T.ERROR
            return T.ERROR
        return self.expr(e, scope)

    def expr(self, e: A.Expr, scope: Scope) -> T.Type:
        t = self._expr(e, scope)
        e.type = t
        return t

    def _expr(self, e: A.Expr, scope: Scope) -> T.Type:
        if isinstance(e, A.IntLit):
            e.const_value = e.value
            return T.INTEGER
        if isinstance(e, A.RealLit):
            e.const_value = e.value
            return T.REAL
        if isinstance(e, A.StrLit):
            if len(e.value) == 1:
                e.const_value = ord(e.value)
                return T.CHAR
            e.const_value = e.value
            return T.StringType(len(e.value))
        if isinstance(e, A.PlaceholderExpr):
            return T.ERROR
        if isinstance(e, A.WriteArg):
            self.error("WIDTHUSE", e)
            return self.expr(e.value, scope)
        if isinstance(e, A.Name):
            sym = self.lookup(scope, e.name, e)
            if sym is None:
                return T.ERROR
            e.symbol = sym
            if isinstance(sym, VarSym):
                return sym.type
            if isinstance(sym, ConstSym):
                e.const_value = sym.value
                return sym.type
            if isinstance(sym, RoutineSym):
                if not sym.is_function:
                    self.error("NOTFUNC", e, name=e.name)
                    return T.ERROR
                if sym.params:
                    self.error("ARGCOUNT", e, name=e.name, expected=len(sym.params), found=0)
                return sym.result or T.ERROR
            if isinstance(sym, StdSym):
                if not sym.is_function:
                    self.error("NOTFUNC", e, name=e.name)
                    return T.ERROR
                if sym.name in ("EOF", "EOLN", "RANDOM"):
                    return self.std_function(e, sym, [], scope)
                self.error("ARGCOUNT", e, name=e.name, expected=1, found=0)
                return T.ERROR
            self.error("BADUSE", e, name=e.name, what=sym.what)
            return T.ERROR
        if isinstance(e, (A.Index, A.FieldRef)):
            return self.designator(e, scope)
        if isinstance(e, A.FuncCall):
            if e.name.startswith("%"):
                return T.ERROR
            sym = self.lookup(scope, e.name, e)
            if sym is None:
                for a in e.args:
                    self.expr(a, scope)
                return T.ERROR
            e.symbol = sym
            if isinstance(sym, StdSym) and sym.is_function:
                return self.std_function(e, sym, e.args, scope)
            if isinstance(sym, RoutineSym) and sym.is_function:
                self.check_args(sym, e.args, e, scope)
                return sym.result or T.ERROR
            if isinstance(sym, (RoutineSym, StdSym)):
                self.error("NOTFUNC", e, name=e.name)
            else:
                self.error("BADUSE", e, name=e.name, what=sym.what)
            for a in e.args:
                self.expr(a, scope)
            return T.ERROR
        if isinstance(e, A.Unary):
            t = self.expr(e.operand, scope)
            if T.is_error(t):
                return T.ERROR
            cv = getattr(e.operand, "const_value", None)
            if e.op == "NOT":
                if t.base is not T.BOOLEAN:
                    if T.is_integer(t):
                        self.error("BOOLOPINT", e, op="NOT", type=str(t))
                    else:
                        self.error("INCOPERAND", e, op="NOT", type=str(t))
                    return T.ERROR
                if isinstance(cv, int):
                    e.const_value = 0 if cv else 1
                return T.BOOLEAN
            if not T.is_numeric(t):
                self.error("INCOPERAND", e, op=e.op, type=str(t))
                return T.ERROR
            if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                e.const_value = -cv if e.op == "-" else cv
            return T.INTEGER if T.is_integer(t) else T.REAL
        if isinstance(e, A.Binary):
            return self.binary(e, scope)
        return T.ERROR

    @staticmethod
    def string_compare_length(left, lt, right, rt) -> int | None:
        """Length to compare a character array with another one or with a string constant."""
        def length(e, t):
            if T.is_char_array(t):
                return t.count, False
            cv = getattr(e, "const_value", None)
            if isinstance(t, T.StringType) and isinstance(cv, str):
                return len(cv), True
            if t.base is T.CHAR and isinstance(cv, int):
                return 1, True
            return None, False
        (ln, lconst), (rn, rconst) = length(left, lt), length(right, rt)
        if ln is None or rn is None:
            return None
        if lconst or rconst:
            return max(ln, rn) if (rn <= ln if rconst else ln <= rn) else None
        return ln if ln == rn else None

    def binary(self, e: A.Binary, scope: Scope) -> T.Type:
        lt = self.expr(e.left, scope)
        rt = self.expr(e.right, scope)
        if T.is_error(lt) or T.is_error(rt):
            return T.ERROR
        op = e.op
        result: T.Type
        if op in ("+", "-", "*", "/"):
            for side, st in ((e.left, lt), (e.right, rt)):
                if not T.is_numeric(st):
                    self.error("INCOPERAND", side, op=op, type=str(st))
                    return T.ERROR
            if op == "/" or lt is T.REAL or rt is T.REAL:
                result = T.REAL
            else:
                result = T.INTEGER
        elif op in ("DIV", "MOD"):
            for side, st in ((e.left, lt), (e.right, rt)):
                if st is T.REAL:
                    self.error("REALDIV", side, op=op)
                    return T.ERROR
                if not T.is_integer(st):
                    self.error("INCOPERAND", side, op=op, type=str(st))
                    return T.ERROR
            result = T.INTEGER
        elif op in ("AND", "OR"):
            for side, st in ((e.left, lt), (e.right, rt)):
                if st.base is not T.BOOLEAN:
                    if T.is_numeric(st):
                        self.error("BOOLOPINT", side, op=op, type=str(st))
                    else:
                        self.error("INCOPERAND", side, op=op, type=str(st))
                    return T.ERROR
            result = T.BOOLEAN
        else:   # comparisons
            ok = (
                (T.is_numeric(lt) and T.is_numeric(rt))
                or (lt.is_ordinal and rt.is_ordinal and lt.base is rt.base)
                or (isinstance(lt, T.StringType) and isinstance(rt, T.StringType) and lt.length == rt.length)
            )
            if not ok and (T.is_char_array(lt) or T.is_char_array(rt)):
                n = self.string_compare_length(e.left, lt, e.right, rt)
                if n is not None:
                    e.compare_length = n
                    ok = True
            if not ok:
                self.error("INCOMPTYPES", e, op=op, left=str(lt), right=str(rt))
                return T.ERROR
            result = T.BOOLEAN
        a = getattr(e.left, "const_value", None)
        b = getattr(e.right, "const_value", None)
        if a is not None and b is not None and not isinstance(a, str) and not isinstance(b, str):
            v = _fold_binary(op, a, b, result)
            if v is not None:
                if result is T.INTEGER and not (T.MININT <= v <= T.MAXINT):
                    v = None
                elif result is T.REAL:
                    v = float(v)
                if v is not None:
                    e.const_value = v
        return result


def analyze(program: A.Program, filename: str = "<buffer>") -> tuple[UnitInfo, list[Diagnostic]]:
    an = Analyzer(filename)
    info = an.analyze(program)
    return info, an.diagnostics

"""Abstract syntax tree for the Pascal subset.

Every node has ``kind`` (a short lower-case string such as ``"var"``,
``"assign"`` or ``"if"``), a source position (``line``, ``column``,
``end_line``, ``end_column``), and ``children()``. Use :func:`walk` to
visit every node of a tree.

Names keep the spelling used in the source; compare them with
``.upper()`` because Pascal is not case sensitive.

After semantic analysis, expression nodes also carry ``type`` (a
:mod:`pascal.types` type) and name nodes carry ``symbol``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Iterator


@dataclass(eq=False, kw_only=True)
class Node:
    line: int = 0
    column: int = 0
    end_line: int = 0
    end_column: int = 0

    kind = "node"
    is_statement = False
    is_expression = False
    type = None      # filled in by semantic analysis (expressions)
    symbol = None    # filled in by semantic analysis (names, calls)

    def children(self) -> Iterator["Node"]:
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, Node):
                yield v
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, Node):
                        yield item

    def walk(self) -> Iterator["Node"]:
        return walk(self)

    def find_all(self, kind: str) -> list["Node"]:
        return [n for n in walk(self) if n.kind == kind]

    def to_source(self) -> str:
        return unparse(self)


def walk(node: Node) -> Iterator[Node]:
    """Yield ``node`` and all its descendants, depth first, in source order."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(list(n.children())))


# ----------------------------------------------------------------------
# Program structure and declarations
# ----------------------------------------------------------------------

@dataclass(eq=False, kw_only=True)
class Program(Node):
    name: str
    unit: str = "PROGRAM"           # "PROGRAM" or "MODULE"
    params: list[str] = field(default_factory=list)
    block: "Block"
    kind = "program"

    @property
    def is_module(self) -> bool:
        return self.unit == "MODULE"

    def declarations(self) -> list[Node]:
        """All declarations anywhere in the program (including inside routines)."""
        return [n for n in walk(self) if isinstance(n, (ConstDecl, TypeDecl, VarDecl, RoutineDecl))]

    def variables(self) -> list[tuple[str, str]]:
        """(name, type text) for every variable declared anywhere, in source order."""
        out = []
        for n in walk(self):
            if isinstance(n, VarDecl):
                out.extend((name, n.spec.text) for name in n.names)
        return out

    def statements(self) -> list[Node]:
        return [n for n in walk(self) if n.is_statement]


@dataclass(eq=False, kw_only=True)
class Block(Node):
    decls: list[Node] = field(default_factory=list)
    body: "Compound | None" = None
    kind = "block"

    @property
    def consts(self):
        return [d for d in self.decls if isinstance(d, ConstDecl)]

    @property
    def types(self):
        return [d for d in self.decls if isinstance(d, TypeDecl)]

    @property
    def vars(self):
        return [d for d in self.decls if isinstance(d, VarDecl)]

    @property
    def routines(self):
        return [d for d in self.decls if isinstance(d, RoutineDecl)]


@dataclass(eq=False, kw_only=True)
class ConstDecl(Node):
    name: str
    value: Node
    kind = "const"


@dataclass(eq=False, kw_only=True)
class TypeDecl(Node):
    name: str
    spec: "TypeSpec"
    kind = "type"


@dataclass(eq=False, kw_only=True)
class VarDecl(Node):
    names: list[str]
    spec: "TypeSpec"
    attributes: list[str] = field(default_factory=list)
    kind = "var"

    @property
    def type_name(self) -> str:
        return self.spec.text


@dataclass(eq=False, kw_only=True)
class ParamDecl(Node):
    names: list[str]
    spec: "TypeSpec"
    by_ref: bool = False
    kind = "param"


@dataclass(eq=False, kw_only=True)
class RoutineDecl(Node):
    name: str
    params: list[ParamDecl] = field(default_factory=list)
    result: "TypeSpec | None" = None
    block: Block | None = None
    directive: str | None = None    # "FORWARD", "EXTERNAL" or None
    attributes: list[str] = field(default_factory=list)
    has_params: bool = True         # False when the parameter list was left out entirely
    kind = "routine"

    @property
    def is_function(self) -> bool:
        return self.kind == "function"


@dataclass(eq=False, kw_only=True)
class ProcedureDecl(RoutineDecl):
    kind = "procedure"


@dataclass(eq=False, kw_only=True)
class FunctionDecl(RoutineDecl):
    kind = "function"


# ----------------------------------------------------------------------
# Type specifications (as written in the source)
# ----------------------------------------------------------------------

@dataclass(eq=False, kw_only=True)
class TypeSpec(Node):
    kind = "typespec"

    @property
    def text(self) -> str:
        return unparse(self)


@dataclass(eq=False, kw_only=True)
class NamedType(TypeSpec):
    name: str
    kind = "named_type"


@dataclass(eq=False, kw_only=True)
class SubrangeType(TypeSpec):
    low: Node
    high: Node
    kind = "subrange_type"


@dataclass(eq=False, kw_only=True)
class EnumType(TypeSpec):
    names: list[str]
    kind = "enum_type"


@dataclass(eq=False, kw_only=True)
class ArrayType(TypeSpec):
    indexes: list[TypeSpec]
    element: TypeSpec
    packed: bool = False
    kind = "array_type"


@dataclass(eq=False, kw_only=True)
class FieldDecl(Node):
    names: list[str]
    spec: TypeSpec
    kind = "field"


@dataclass(eq=False, kw_only=True)
class RecordType(TypeSpec):
    fields: list[FieldDecl] = field(default_factory=list)
    packed: bool = False
    kind = "record_type"


@dataclass(eq=False, kw_only=True)
class PlaceholderType(TypeSpec):
    name: str
    required: bool = True
    text_: str = ""
    kind = "placeholder_type"


# ----------------------------------------------------------------------
# Statements
# ----------------------------------------------------------------------

@dataclass(eq=False, kw_only=True)
class Statement(Node):
    is_statement = True
    kind = "statement"


@dataclass(eq=False, kw_only=True)
class Compound(Statement):
    stmts: list[Statement] = field(default_factory=list)
    kind = "compound"


@dataclass(eq=False, kw_only=True)
class Assign(Statement):
    target: Node
    value: Node
    kind = "assign"

    @property
    def target_name(self) -> str:
        """Name of the variable being assigned (the array/record name for a[i] or r.f)."""
        n = self.target
        while isinstance(n, (Index, FieldRef)):
            n = n.base
        return n.name if isinstance(n, Name) else ""


@dataclass(eq=False, kw_only=True)
class ProcCall(Statement):
    name: str
    args: list[Node] = field(default_factory=list)
    kind = "call"


@dataclass(eq=False, kw_only=True)
class If(Statement):
    cond: Node
    then_part: Statement
    else_part: Statement | None = None
    kind = "if"


@dataclass(eq=False, kw_only=True)
class While(Statement):
    cond: Node
    body: Statement
    kind = "while"


@dataclass(eq=False, kw_only=True)
class Repeat(Statement):
    body: list[Statement] = field(default_factory=list)
    cond: Node = None
    kind = "repeat"


@dataclass(eq=False, kw_only=True)
class For(Statement):
    var: "Name"
    start: Node
    stop: Node
    down: bool = False
    body: Statement = None
    kind = "for"


@dataclass(eq=False, kw_only=True)
class CaseRange(Node):
    low: Node
    high: Node
    kind = "range"


@dataclass(eq=False, kw_only=True)
class CaseArm(Node):
    labels: list[Node]
    body: Statement
    kind = "case_arm"


@dataclass(eq=False, kw_only=True)
class Case(Statement):
    selector: Node
    arms: list[CaseArm] = field(default_factory=list)
    otherwise: list[Statement] | None = None
    kind = "case"


@dataclass(eq=False, kw_only=True)
class Empty(Statement):
    kind = "empty"


@dataclass(eq=False, kw_only=True)
class PlaceholderStmt(Statement):
    name: str
    required: bool = True
    text: str = ""
    kind = "placeholder"


# ----------------------------------------------------------------------
# Expressions
# ----------------------------------------------------------------------

@dataclass(eq=False, kw_only=True)
class Expr(Node):
    is_expression = True
    kind = "expr"


@dataclass(eq=False, kw_only=True)
class IntLit(Expr):
    value: int
    kind = "int"


@dataclass(eq=False, kw_only=True)
class RealLit(Expr):
    value: float
    text: str = ""
    kind = "real"


@dataclass(eq=False, kw_only=True)
class StrLit(Expr):
    value: str
    kind = "string"


@dataclass(eq=False, kw_only=True)
class Name(Expr):
    name: str
    kind = "name"


@dataclass(eq=False, kw_only=True)
class Index(Expr):
    base: Expr
    indexes: list[Expr]
    kind = "index"


@dataclass(eq=False, kw_only=True)
class FieldRef(Expr):
    base: Expr
    field_name: str
    kind = "field_ref"


@dataclass(eq=False, kw_only=True)
class FuncCall(Expr):
    name: str
    args: list[Expr] = field(default_factory=list)
    kind = "funccall"


@dataclass(eq=False, kw_only=True)
class Binary(Expr):
    op: str          # upper case: "+", "-", "*", "/", "DIV", "MOD", "AND", "OR", "=", "<>", "<", "<=", ">", ">="
    left: Expr
    right: Expr
    kind = "binary"


@dataclass(eq=False, kw_only=True)
class Unary(Expr):
    op: str          # "-", "+", "NOT"
    operand: Expr
    kind = "unary"


@dataclass(eq=False, kw_only=True)
class WriteArg(Expr):
    value: Expr
    width: Expr | None = None
    precision: Expr | None = None
    kind = "write_arg"


@dataclass(eq=False, kw_only=True)
class PlaceholderExpr(Expr):
    name: str
    required: bool = True
    text: str = ""
    kind = "placeholder_expr"


# ----------------------------------------------------------------------
# Unparsing: canonical Pascal text for a node
# ----------------------------------------------------------------------

_PREC = {"=": 1, "<>": 1, "<": 1, "<=": 1, ">": 1, ">=": 1,
         "+": 2, "-": 2, "OR": 2,
         "*": 3, "/": 3, "DIV": 3, "MOD": 3, "AND": 3}


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def unparse(n: Node, indent: int = 0) -> str:
    """Canonical source text for an expression, type or statement (keywords upper case)."""
    pad = "  " * indent
    if n is None:
        return ""
    if isinstance(n, IntLit):
        return str(n.value)
    if isinstance(n, RealLit):
        return n.text or repr(n.value)
    if isinstance(n, StrLit):
        return _q(n.value)
    if isinstance(n, Name):
        return n.name
    if isinstance(n, Index):
        return f"{unparse(n.base)}[{', '.join(unparse(i) for i in n.indexes)}]"
    if isinstance(n, FieldRef):
        return f"{unparse(n.base)}.{n.field_name}"
    if isinstance(n, FuncCall):
        return f"{n.name}({', '.join(unparse(a) for a in n.args)})"
    if isinstance(n, WriteArg):
        s = unparse(n.value)
        if n.width is not None:
            s += ":" + unparse(n.width)
        if n.precision is not None:
            s += ":" + unparse(n.precision)
        return s
    if isinstance(n, Binary):
        p = _PREC.get(n.op, 0)

        def side(e, right=False):
            s = unparse(e)
            if isinstance(e, Binary) and (_PREC.get(e.op, 0) < p or (right and _PREC.get(e.op, 0) == p)):
                return f"({s})"
            return s
        return f"{side(n.left)} {n.op} {side(n.right, True)}"
    if isinstance(n, Unary):
        inner = unparse(n.operand)
        if isinstance(n.operand, Binary):
            inner = f"({inner})"
        return f"NOT {inner}" if n.op == "NOT" else f"{n.op}{inner}"
    if isinstance(n, (PlaceholderExpr, PlaceholderStmt)):
        return n.text or ("%{" + n.name + "}%" if n.required else "%[" + n.name + "]%")
    if isinstance(n, PlaceholderType):
        return n.text_ or ("%{" + n.name + "}%" if n.required else "%[" + n.name + "]%")
    if isinstance(n, CaseRange):
        return f"{unparse(n.low)}..{unparse(n.high)}"
    # Types
    if isinstance(n, NamedType):
        return n.name.upper()
    if isinstance(n, SubrangeType):
        return f"{unparse(n.low)}..{unparse(n.high)}"
    if isinstance(n, EnumType):
        return "(" + ", ".join(n.names) + ")"
    if isinstance(n, ArrayType):
        packed = "PACKED " if n.packed else ""
        return f"{packed}ARRAY [{', '.join(unparse(i) for i in n.indexes)}] OF {unparse(n.element)}"
    if isinstance(n, RecordType):
        parts = "; ".join(f"{', '.join(f.names)} : {unparse(f.spec)}" for f in n.fields)
        return f"RECORD {parts} END"
    # Statements
    if isinstance(n, Assign):
        return f"{pad}{unparse(n.target)} := {unparse(n.value)}"
    if isinstance(n, ProcCall):
        if n.args:
            return f"{pad}{n.name}({', '.join(unparse(a) for a in n.args)})"
        return f"{pad}{n.name}"
    if isinstance(n, Compound):
        inner = ";\n".join(unparse(s, indent + 1) for s in n.stmts)
        return f"{pad}BEGIN\n{inner}\n{pad}END"
    if isinstance(n, If):
        s = f"{pad}IF {unparse(n.cond)} THEN\n{unparse(n.then_part, indent + 1)}"
        if n.else_part is not None:
            s += f"\n{pad}ELSE\n{unparse(n.else_part, indent + 1)}"
        return s
    if isinstance(n, While):
        return f"{pad}WHILE {unparse(n.cond)} DO\n{unparse(n.body, indent + 1)}"
    if isinstance(n, Repeat):
        inner = ";\n".join(unparse(s, indent + 1) for s in n.body)
        return f"{pad}REPEAT\n{inner}\n{pad}UNTIL {unparse(n.cond)}"
    if isinstance(n, For):
        direction = "DOWNTO" if n.down else "TO"
        return (f"{pad}FOR {unparse(n.var)} := {unparse(n.start)} {direction} {unparse(n.stop)} DO\n"
                f"{unparse(n.body, indent + 1)}")
    if isinstance(n, Case):
        lines = [f"{pad}CASE {unparse(n.selector)} OF"]
        for arm in n.arms:
            labels = ", ".join(unparse(lab) for lab in arm.labels)
            lines.append(f"{pad}  {labels}: {unparse(arm.body).strip()};")
        if n.otherwise is not None:
            lines.append(f"{pad}  OTHERWISE " + "; ".join(unparse(s).strip() for s in n.otherwise))
        lines.append(f"{pad}END")
        return "\n".join(lines)
    if isinstance(n, Empty):
        return pad
    return f"{pad}<{n.kind}>"

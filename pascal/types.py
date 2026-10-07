"""Pascal types as seen by the semantic analyser and code generator.

Every value occupies one or more *cells* in the p-code machine; scalars
take one cell, arrays and records take the sum of their parts.
"""

from __future__ import annotations

MININT = -2147483648
MAXINT = 2147483647


class Type:
    size = 1
    decl_name: str | None = None   # set when the type was named in a TYPE section

    @property
    def is_ordinal(self) -> bool:
        return False

    @property
    def base(self) -> "Type":
        return self

    def __str__(self) -> str:
        return self.decl_name.upper() if self.decl_name else self.describe()

    def describe(self) -> str:
        return "?"

    def signature(self) -> str:
        return self.describe()


class _Simple(Type):
    def __init__(self, name: str, ordinal: bool):
        self.name = name
        self._ordinal = ordinal

    @property
    def is_ordinal(self):
        return self._ordinal

    def describe(self):
        return self.name

    def __repr__(self):
        return self.name


INTEGER = _Simple("INTEGER", True)
REAL = _Simple("REAL", False)
BOOLEAN = _Simple("BOOLEAN", True)
CHAR = _Simple("CHAR", True)


class ErrorType(Type):
    """Type of an expression that already produced an error; compatible with everything."""

    def describe(self):
        return "unknown"

    def __repr__(self):
        return "ErrorType"


ERROR = ErrorType()


class EnumType(Type):
    def __init__(self, names: list[str]):
        self.names = names

    @property
    def is_ordinal(self):
        return True

    def describe(self):
        return "(" + ", ".join(n.upper() for n in self.names) + ")"


class SubrangeType(Type):
    def __init__(self, base: Type, low: int, high: int):
        self._base = base.base
        self.low = low
        self.high = high

    @property
    def is_ordinal(self):
        return True

    @property
    def base(self):
        return self._base

    def describe(self):
        return f"{format_ordinal(self.low, self._base)}..{format_ordinal(self.high, self._base)}"


class StringType(Type):
    """Type of a string literal of two or more characters (or zero)."""

    def __init__(self, length: int):
        self.length = length

    def describe(self):
        return "string"


class ArrayType(Type):
    def __init__(self, index: Type, element: Type):
        self.index = index
        self.element = element
        self.low, self.high = bounds(index)
        self.count = self.high - self.low + 1
        self.size = self.count * element.size

    def describe(self):
        packed = ""
        return f"{packed}ARRAY [{self.index}] OF {self.element}"

    def signature(self):
        return f"ARRAY[{self.index.signature()}]OF {self.element.signature()}"


class RecordType(Type):
    def __init__(self):
        self.fields: dict[str, tuple[str, int, Type]] = {}
        self.size = 0

    def add_field(self, name: str, t: Type):
        self.fields[name.upper()] = (name, self.size, t)
        self.size += t.size

    def describe(self):
        parts = "; ".join(f"{n.upper()} : {t}" for n, _, t in self.fields.values())
        return f"RECORD {parts} END"

    def signature(self):
        parts = ";".join(f"{n.upper()}:{t.signature()}" for n, _, t in self.fields.values())
        return f"RECORD({parts})"


def is_error(t: Type | None) -> bool:
    return t is None or isinstance(t, ErrorType)


def bounds(t: Type) -> tuple[int, int]:
    if isinstance(t, SubrangeType):
        return t.low, t.high
    if isinstance(t, EnumType):
        return 0, len(t.names) - 1
    if t is CHAR:
        return 0, 255
    if t is BOOLEAN:
        return 0, 1
    return MININT, MAXINT


def is_integer(t: Type) -> bool:
    return t.base is INTEGER


def is_numeric(t: Type) -> bool:
    return t.base is INTEGER or t is REAL


def is_char_array(t: Type) -> bool:
    return isinstance(t, ArrayType) and t.element.base is CHAR and t.index.base is INTEGER


def format_ordinal(value: int, t: Type) -> str:
    b = t.base
    if b is CHAR:
        ch = chr(value) if 0 <= value < 256 else "?"
        return f"'{ch}'" if ch.isprintable() else f"CHR({value})"
    if b is BOOLEAN:
        return "TRUE" if value else "FALSE"
    if isinstance(b, EnumType) and 0 <= value < len(b.names):
        return b.names[value].upper()
    return str(value)


def same_type(a: Type, b: Type) -> bool:
    """Types that are interchangeable (used for VAR parameters and structured assignment)."""
    if a is b:
        return True
    if isinstance(a, SubrangeType) and isinstance(b, SubrangeType):
        return a.base is b.base and a.low == b.low and a.high == b.high
    if isinstance(a, ArrayType) and isinstance(b, ArrayType):
        return (bounds(a.index) == bounds(b.index) and a.index.base is b.index.base
                and same_type(a.element, b.element))
    return False

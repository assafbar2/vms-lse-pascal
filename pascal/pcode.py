"""The p-code instruction set.

The p-code machine is a stack machine. Memory is one array of cells:
static data of all linked modules comes first, followed by the stack.
Each procedure call builds a frame on the stack:

    bp+0  static link   (frame of the lexically enclosing routine)
    bp+1  dynamic link  (caller's bp)
    bp+2  return address
    bp+3  parameters, then the function result slot, locals and temporaries

Operand kinds:

    code   code address (hexadecimal) or the name of an external routine
    data   static data address (hexadecimal) or the name of an external variable
    int    decimal integer (frame offset, count, level difference, bound)
    const  numeric constant (integer or real)
    str    string constant in single quotes
    name   name of a native run-time routine
"""

from __future__ import annotations

from dataclasses import dataclass, field

CODE, DATA, INT, CONST, STR, NAME = "code", "data", "int", "const", "str", "name"

# opcode: (operand kinds, description)
OPCODES: dict[str, tuple[tuple[str, ...], str]] = {
    "LIT":    ((CONST,), "push a constant"),
    "LITS":   ((STR,), "push a string constant"),
    "LDG":    ((DATA,), "push the value of a static variable"),
    "STG":    ((DATA,), "pop a value into a static variable"),
    "LAG":    ((DATA,), "push the address of a static variable"),
    "LDL":    ((INT,), "push the value of a local variable (frame offset)"),
    "STL":    ((INT,), "pop a value into a local variable"),
    "LAL":    ((INT,), "push the address of a local variable"),
    "LDI":    ((INT, INT), "push a variable of an enclosing routine (levels out, offset)"),
    "STI":    ((INT, INT), "pop into a variable of an enclosing routine"),
    "LAI":    ((INT, INT), "push the address of a variable of an enclosing routine"),
    "IND":    ((), "replace an address by the value stored there"),
    "STO":    ((), "pop a value and an address; store the value there"),
    "MOVE":   ((INT,), "pop source and destination addresses; copy n cells"),
    "LDBLK":  ((INT,), "pop an address; push the n cells stored there"),
    "SMOVE":  ((INT,), "pop a string and an address; store it as n characters"),
    "SBLK":   ((INT,), "pop a string; push it as n character cells"),
    "INDEX":  ((INT, INT, INT), "pop index and array address; push element address (low, high, element size)"),
    "OFFS":   ((INT,), "add a field offset to the address on top of the stack"),
    "ADDI":   ((), "integer add"),
    "SUBI":   ((), "integer subtract"),
    "MULI":   ((), "integer multiply"),
    "DIVI":   ((), "integer divide (DIV)"),
    "MODI":   ((), "integer remainder (MOD)"),
    "NEGI":   ((), "integer negate"),
    "ADDR":   ((), "real add"),
    "SUBR":   ((), "real subtract"),
    "MULR":   ((), "real multiply"),
    "DIVR":   ((), "real divide (/)"),
    "NEGR":   ((), "real negate"),
    "FLT":    ((), "convert the integer on top of the stack to real"),
    "FLT2":   ((), "convert the integer just below the top of the stack to real"),
    "EQU":    ((), "compare equal"),
    "NEQ":    ((), "compare not equal"),
    "LES":    ((), "compare less than"),
    "LEQ":    ((), "compare less or equal"),
    "GRT":    ((), "compare greater than"),
    "GEQ":    ((), "compare greater or equal"),
    "AND":    ((), "boolean AND"),
    "OR":     ((), "boolean OR"),
    "NOT":    ((), "boolean NOT"),
    "ABSI":   ((), "integer absolute value"),
    "ABSR":   ((), "real absolute value"),
    "SQRI":   ((), "integer square"),
    "SQRR":   ((), "real square"),
    "ODD":    ((), "TRUE if the integer is odd"),
    "CHR":    ((), "check that an integer is a character code"),
    "TRUNC":  ((), "real to integer, dropping the fraction"),
    "ROUND":  ((), "real to integer, rounding"),
    "SUCC":   ((INT, INT), "add one, checking the type's bounds"),
    "PRED":   ((INT, INT), "subtract one, checking the type's bounds"),
    "CHK":    ((INT, INT), "check that the value is within bounds"),
    "DUP":    ((), "duplicate the top of the stack"),
    "POP":    ((), "discard the top of the stack"),
    "JMP":    ((CODE,), "jump"),
    "JPF":    ((CODE,), "pop a boolean; jump if FALSE"),
    "JPT":    ((CODE,), "pop a boolean; jump if TRUE"),
    "MARK":   ((INT,), "start a call: push a frame header (static link found n levels out)"),
    "CALL":   ((CODE, INT), "call a routine with n cells of arguments"),
    "ENTER":  ((INT,), "allocate n cells of local storage"),
    "RET":    ((), "return from a procedure"),
    "RETF":   ((INT,), "return from a function with the result at the given frame offset"),
    "RETV":   ((), "return from a function with the result on top of the stack"),
    "NATIVE": ((NAME, INT), "run a built-in run-time routine with n argument cells"),
    "STOP":   ((), "end of the main program"),
    "CASERR": ((), "pop a CASE selector that matched no label; stop with an error"),
    "LDSTR":  ((INT,), "pop the address of n characters; push them as one string (for comparisons)"),
}


@dataclass(frozen=True)
class SymRef:
    """A reference to a symbol defined in another module, resolved by the linker."""
    name: str

    def __str__(self):
        return self.name


@dataclass
class Instr:
    op: str
    args: list = field(default_factory=list)
    line: int = 0
    comment: str = ""


def operand_kinds(op: str) -> tuple[str, ...]:
    return OPCODES[op][0]


def format_operand(kind: str, value) -> str:
    if kind in (CODE, DATA):
        if isinstance(value, SymRef):
            return value.name
        return f"{value:04X}"
    if kind == STR:
        return "'" + str(value).replace("'", "''") + "'"
    if kind == CONST:
        if isinstance(value, float):
            return repr(value)
        return str(value)
    return str(value)


def format_instr(ins: Instr) -> str:
    kinds = operand_kinds(ins.op)
    ops = " ".join(format_operand(k, v) for k, v in zip(kinds, ins.args))
    return f"{ins.op:<7}{ops}".rstrip()


def parse_operands(op: str, text: str) -> list:
    """Parse the operand text of one instruction (the inverse of format_instr)."""
    kinds = operand_kinds(op)
    values = []
    rest = text.strip()
    for kind in kinds:
        if not rest:
            raise ValueError(f"{op} needs {len(kinds)} operand(s)")
        if kind == STR:
            if not rest.startswith("'"):
                raise ValueError(f"{op} needs a quoted string")
            i = 1
            chars = []
            while True:
                if i >= len(rest):
                    raise ValueError("unterminated string")
                if rest[i] == "'":
                    if rest[i + 1:i + 2] == "'":
                        chars.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                chars.append(rest[i])
                i += 1
            values.append("".join(chars))
            rest = rest[i:].strip()
            continue
        parts = rest.split(None, 1)
        tok = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        if kind in (CODE, DATA):
            if tok[0].isdigit():
                values.append(int(tok, 16))
            else:
                values.append(SymRef(tok.upper()))
        elif kind == INT:
            values.append(int(tok))
        elif kind == CONST:
            if any(c in tok for c in ".eEn"):
                values.append(float(tok))
            else:
                values.append(int(tok))
        else:
            values.append(tok.upper())
    if rest:
        raise ValueError(f"unexpected text after {op}: {rest!r}")
    return values


def strip_comment(line: str) -> str:
    """Remove a ';' comment from a line, ignoring ';' inside quoted strings."""
    in_str = False
    for i, ch in enumerate(line):
        if ch == "'":
            in_str = not in_str
        elif ch == ";" and not in_str:
            return line[:i]
    return line

"""Lexical analysis: turns Pascal source text into a list of tokens.

Names are not case sensitive, so identifier and keyword tokens carry an
upper-case ``value`` next to the ``text`` exactly as written.

LSE placeholders (``%{name}%`` required, ``%[name]%`` optional, either one
optionally followed by ``...``) become PLACEHOLDER tokens, and each one is
reported as ``%PASCAL-E-PLACEHOLDER`` so the user can find and fill it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .messages import Diagnostic, diag

KEYWORDS = {
    "AND", "ARRAY", "BEGIN", "CASE", "CONST", "DIV", "DO", "DOWNTO", "ELSE", "END",
    "FOR", "FUNCTION", "IF", "MOD", "MODULE", "NOT", "OF", "OR", "OTHERWISE",
    "PACKED", "PROCEDURE", "PROGRAM", "RECORD", "REPEAT", "THEN", "TO", "TYPE",
    "UNTIL", "VAR", "WHILE",
    # Reserved words of features this subset leaves out.
    "FILE", "GOTO", "IN", "LABEL", "NIL", "SET", "WITH",
}

UNSUPPORTED_KEYWORDS = {"FILE", "GOTO", "IN", "LABEL", "NIL", "SET", "WITH"}

SYMBOLS = [":=", "<=", ">=", "<>", "..", "(", ")", "[", "]", ".", ",", ";", ":",
           "=", "<", ">", "+", "-", "*", "/", "^", "@"]

MAXINT = 2147483647


@dataclass
class Token:
    kind: str           # "IDENT", "INT", "REAL", "STRING", "PLACEHOLDER", "EOF", a keyword or a symbol
    text: str           # source text as written
    value: object       # IDENT/keyword: upper-case name; INT/REAL: number; STRING: str; PLACEHOLDER: name
    line: int
    column: int         # 1-based
    end_line: int
    end_column: int     # column just after the last character
    required: bool = True   # placeholders: %{...}% (True) or %[...]% (False)

    def __repr__(self):
        return f"Token({self.kind}, {self.text!r}, {self.line}:{self.column})"


class Lexer:
    def __init__(self, text: str, filename: str = "<buffer>"):
        self.src = text.replace("\r\n", "\n").replace("\r", "\n")
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []
        self.diagnostics: list[Diagnostic] = []

    def error(self, ident, line, column, **args):
        self.diagnostics.append(diag("PASCAL", ident, file=self.filename, line=line,
                                     column=column, **args))

    def peek(self, offset=0) -> str:
        p = self.pos + offset
        return self.src[p] if p < len(self.src) else ""

    def advance(self, n=1) -> str:
        s = self.src[self.pos:self.pos + n]
        for ch in s:
            if ch == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
        self.pos += n
        return s

    def add(self, kind, text, value, line, col, required=True):
        self.tokens.append(Token(kind, text, value, line, col, self.line, self.col, required))

    def tokenize(self) -> list[Token]:
        src = self.src
        while True:
            self.skip_space_and_comments()
            if self.pos >= len(src):
                break
            ch = src[self.pos]
            line, col = self.line, self.col
            if ch == "%" and self.peek(1) in ("{", "["):
                self.placeholder()
            elif ch.isalpha() or ch == "_":
                self.identifier()
            elif ch.isdigit():
                self.number()
            elif ch == "'":
                self.string()
            elif ch == '"':
                self.double_quoted_string()
            else:
                for sym in SYMBOLS:
                    if src.startswith(sym, self.pos):
                        self.advance(len(sym))
                        self.add(sym, sym, sym, line, col)
                        break
                else:
                    self.advance()
                    shown = ch if ch.isprintable() else f"\\x{ord(ch):02X}"
                    self.error("ILLCHAR", line, col, char=shown)
        self.tokens.append(Token("EOF", "", None, self.line, self.col, self.line, self.col))
        return self.tokens

    def skip_space_and_comments(self):
        src = self.src
        while self.pos < len(src):
            ch = src[self.pos]
            if ch in " \t\n\f\v":
                self.advance()
            elif ch == "{":
                self.comment("}", 1)
            elif ch == "(" and self.peek(1) == "*":
                self.comment("*)", 2)
            else:
                break

    def comment(self, closer, opener_len):
        line, col = self.line, self.col
        end = self.src.find(closer, self.pos + opener_len)
        if end < 0:
            self.error("UNTERMCOM", line, col)
            self.advance(len(self.src) - self.pos)
        else:
            self.advance(end + len(closer) - self.pos)

    def placeholder(self):
        line, col = self.line, self.col
        src = self.src
        start = self.pos
        required = src[self.pos + 1] == "{"
        p = self.pos + 2
        depth = 1
        while p < len(src) and src[p] != "\n":
            two = src[p:p + 2]
            if two in ("%{", "%["):
                depth += 1
                p += 2
            elif two in ("}%", "]%"):
                depth -= 1
                p += 2
                if depth == 0:
                    break
            else:
                p += 1
        if depth != 0:
            # Not a well-formed placeholder: treat the "%" as a stray character.
            self.advance()
            self.error("ILLCHAR", line, col, char="%")
            return
        name = src[start + 2:p - 2]
        if src.startswith("...", p):
            p += 3
        text = src[start:p]
        self.advance(p - start)
        self.add("PLACEHOLDER", text, name.strip(), line, col, required)
        self.error("PLACEHOLDER", line, col, placeholder=text)
        self.diagnostics[-1].end_column = self.col

    def identifier(self):
        line, col = self.line, self.col
        src = self.src
        p = self.pos
        while p < len(src) and (src[p].isalnum() or src[p] in "_$"):
            p += 1
        text = self.advance(p - self.pos)
        upper = text.upper()
        kind = upper if upper in KEYWORDS else "IDENT"
        self.add(kind, text, upper, line, col)

    def number(self):
        line, col = self.line, self.col
        src = self.src
        p = self.pos
        while p < len(src) and src[p].isdigit():
            p += 1
        is_real = False
        bad = False
        if p < len(src) and src[p] == "." and src[p + 1:p + 2] != "." and src[p + 1:p + 2] != ")":
            is_real = True
            p += 1
            if not (p < len(src) and src[p].isdigit()):
                bad = True
            while p < len(src) and src[p].isdigit():
                p += 1
        if p < len(src) and src[p] in "eE":
            q = p + 1
            if q < len(src) and src[q] in "+-":
                q += 1
            if q < len(src) and src[q].isdigit():
                is_real = True
                p = q
                while p < len(src) and src[p].isdigit():
                    p += 1
        # A number glued to letters (e.g. "12abc") is malformed.
        while p < len(src) and (src[p].isalnum() or src[p] == "_"):
            bad = True
            p += 1
        text = self.advance(p - self.pos)
        if bad:
            self.error("BADNUM", line, col, text=text)
            self.add("INT", text, 0, line, col)
            return
        if is_real:
            self.add("REAL", text, float(text), line, col)
        else:
            value = int(text)
            if value > MAXINT:
                self.error("INTTOOBIG", line, col, text=text)
                value = MAXINT
            self.add("INT", text, value, line, col)

    def string(self):
        line, col = self.line, self.col
        src = self.src
        p = self.pos + 1
        chars = []
        while True:
            if p >= len(src) or src[p] == "\n":
                self.error("UNTERMSTR", line, col)
                break
            if src[p] == "'":
                if src[p + 1:p + 2] == "'":
                    chars.append("'")
                    p += 2
                    continue
                p += 1
                break
            chars.append(src[p])
            p += 1
        text = self.advance(p - self.pos)
        self.add("STRING", text, "".join(chars), line, col)

    def double_quoted_string(self):
        line, col = self.line, self.col
        src = self.src
        end = src.find('"', self.pos + 1)
        nl = src.find("\n", self.pos + 1)
        if end < 0 or (0 <= nl < end):
            self.advance()
            self.error("ILLCHAR", line, col, char='"')
            return
        text = self.advance(end + 1 - self.pos)
        value = text[1:-1]
        fixed = "'" + value.replace("'", "''") + "'"
        self.error("DBLQUOTE", line, col, fixed=fixed)
        self.add("STRING", text, value, line, col)


def tokenize(text: str, filename: str = "<buffer>") -> tuple[list[Token], list[Diagnostic]]:
    lx = Lexer(text, filename)
    tokens = lx.tokenize()
    return tokens, lx.diagnostics

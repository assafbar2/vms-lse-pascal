"""Recursive-descent parser producing the AST in :mod:`pascal.astnodes`.

The parser keeps going after an error so that one compile can report
several problems, and it tolerates LSE placeholders anywhere a name,
type, statement or expression could be, so a half-finished template
still produces a useful tree (the tutor relies on this).
"""

from __future__ import annotations

from . import astnodes as A
from .lexer import Token, UNSUPPORTED_KEYWORDS, tokenize
from .messages import Diagnostic, diag

EXPECT_MESSAGES = {
    ";": "SEMIEXP", ".": "PERIODEXP", ":": "COLONEXP", ":=": "ASSIGNEXP", "=": "EQLEXP",
    ")": "RPAREXP", "]": "RBRACKEXP", "[": "LBRACKEXP", "THEN": "THENEXP", "DO": "DOEXP",
    "OF": "OFEXP", "END": "ENDEXP", "UNTIL": "UNTILEXP", "BEGIN": "BEGINEXP", "..": "DOTDOTEXP",
    "IDENT": "IDENTEXP", "TO": "TOEXP",
}

# Missing tokens the parser can pretend were there and carry on.
INSERTABLE = {";", ")", "]", "[", "THEN", "DO", "OF", ":=", ":", "=", "END", ".", "UNTIL", "TO", ".."}

STATEMENT_STARTS = {"IDENT", "BEGIN", "IF", "WHILE", "REPEAT", "FOR", "CASE", "PLACEHOLDER", "GOTO", "WITH"}
CLOSERS = {"END", "UNTIL", "EOF", "OTHERWISE", "ELSE", "."}
DECL_STARTS = {"CONST", "TYPE", "VAR", "PROCEDURE", "FUNCTION", "BEGIN", "LABEL", "["}
RELOPS = {"=", "<>", "<", "<=", ">", ">="}
ADDOPS = {"+", "-", "OR"}
MULOPS = {"*", "/", "DIV", "MOD", "AND"}

MAX_ERRORS = 40


class ParseError(Exception):
    """Raised to abandon the current statement or declaration after reporting an error."""


class TooManyErrors(Exception):
    pass


def _short(text: str, limit: int = 24) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


class Parser:
    def __init__(self, tokens: list[Token], filename: str = "<buffer>"):
        self.toks = tokens
        self.i = 0
        self.filename = filename
        self.diagnostics: list[Diagnostic] = []
        self._last_error_at = -1
        self._errors = 0

    # -- token helpers -------------------------------------------------
    @property
    def tok(self) -> Token:
        return self.toks[self.i]

    @property
    def prev(self) -> Token | None:
        return self.toks[self.i - 1] if self.i > 0 else None

    def peek(self, n: int = 1) -> Token:
        return self.toks[min(self.i + n, len(self.toks) - 1)]

    def advance(self) -> Token:
        t = self.toks[self.i]
        if t.kind != "EOF":
            self.i += 1
        return t

    def at(self, *kinds) -> bool:
        return self.tok.kind in kinds

    def accept(self, kind) -> Token | None:
        if self.tok.kind == kind:
            return self.advance()
        return None

    def skip_placeholders(self):
        while self.tok.kind == "PLACEHOLDER":
            self.advance()

    def finish(self, node: A.Node, start: Token) -> A.Node:
        node.line, node.column = start.line, start.column
        end = self.prev if self.i > 0 and self.prev is not None else start
        if end is not None and (end.line, end.column) >= (start.line, start.column):
            node.end_line, node.end_column = end.end_line, end.end_column
        else:
            node.end_line, node.end_column = start.end_line, start.end_column
        return node

    # -- error reporting -------------------------------------------------
    def error(self, ident: str, tok: Token | None = None, *, force: bool = False, **args):
        tok = tok or self.tok
        if not force and self.i == self._last_error_at:
            return
        self._last_error_at = self.i
        line, col, end = tok.line, tok.column, tok.end_column
        if tok.kind == "EOF" and self.prev is not None:
            line, col, end = self.prev.end_line, self.prev.end_column, self.prev.end_column
        self.diagnostics.append(diag("PASCAL", ident, file=self.filename, line=line, column=col,
                                     end_column=end, **args))
        if ident != "PLACEHOLDER":
            self._errors += 1
            if self._errors >= MAX_ERRORS:
                self.diagnostics.append(diag("PASCAL", "TOOMANYERR", file=self.filename,
                                             line=line, column=col))
                raise TooManyErrors

    def report_expected(self, kind: str):
        ident = EXPECT_MESSAGES.get(kind, "SYMEXP")
        prev = self.prev
        args = {"expected": kind, "found": self.tok.text or "end of file"}
        if prev is not None:
            args["prev_line"] = prev.end_line
            args["prev_text"] = _short(prev.text)
        self.error(ident, **args)

    def expect(self, kind: str) -> Token | None:
        if self.tok.kind == "PLACEHOLDER" and kind != "PLACEHOLDER":
            self.skip_placeholders()
        if self.tok.kind == kind:
            return self.advance()
        self.report_expected(kind)
        if kind in INSERTABLE:
            return None
        raise ParseError

    def expect_ident(self) -> Token:
        t = self.tok
        if t.kind in ("IDENT", "PLACEHOLDER"):
            return self.advance()
        self.error("IDENTEXP", found=t.text or "end of file")
        raise ParseError

    def sync(self, stop: set[str]):
        while self.tok.kind not in stop and self.tok.kind != "EOF":
            self.advance()

    def sync_decl(self):
        while not self.at("EOF"):
            if self.at(";"):
                self.advance()
                return
            if self.tok.kind in DECL_STARTS or self.tok.kind == "END":
                return
            self.advance()

    def unsupported(self, feature: str):
        self.error("NOTSUPP", feature=feature)
        raise ParseError

    # -- program structure -----------------------------------------------
    def parse_unit(self) -> A.Program | None:
        try:
            return self._unit()
        except TooManyErrors:
            return None
        except ParseError:
            return None

    def _unit(self) -> A.Program | None:
        self.skip_placeholders()
        start = self.tok
        if not self.at("PROGRAM", "MODULE"):
            self.error("PROGEXP")
            return None
        unit = self.advance().kind
        try:
            name_tok = self.expect_ident()
            name = name_tok.text
        except ParseError:
            name = "?"
        params: list[str] = []
        if self.accept("("):
            try:
                params = self.ident_list()
            except ParseError:
                self.sync({")", ";"})
            self.expect(")")
        self.skip_placeholders()
        self.expect(";")
        if unit == "PROGRAM":
            block = self.block()
        else:
            bstart = self.tok
            decls = self.declarations()
            if self.at("BEGIN"):
                self.error("MODBODY")
                self.compound()
            block = self.finish(A.Block(decls=decls, body=None), bstart)
            self.expect_end(start)
        self.skip_placeholders()
        if not self.at("EOF"):
            self.expect(".")
        else:
            self.report_expected(".")
        self.skip_placeholders()
        if not self.at("EOF") and not any(d.is_error for d in self.diagnostics):
            self.error("EXTRATEXT")
        prog = A.Program(name=name, unit=unit, params=params, block=block)
        return self.finish(prog, start)

    def block(self) -> A.Block:
        start = self.tok
        decls = self.declarations()
        if self.at("BEGIN"):
            body = self.compound()
        else:
            self.report_expected("BEGIN")
            bstart = self.tok
            if self.tok.kind in STATEMENT_STARTS:
                stmts = self.stmt_sequence({"END"})
                body = self.finish(A.Compound(stmts=stmts), bstart)
                self.expect("END")
            else:
                body = self.finish(A.Compound(stmts=[]), bstart)
        return self.finish(A.Block(decls=decls, body=body), start)

    def declarations(self) -> list[A.Node]:
        decls: list[A.Node] = []
        while True:
            k = self.tok.kind
            if k == "PLACEHOLDER":
                self.advance()
            elif k == "CONST":
                decls.extend(self.const_part())
            elif k == "TYPE":
                decls.extend(self.type_part())
            elif k == "VAR":
                decls.extend(self.var_part())
            elif k in ("PROCEDURE", "FUNCTION", "["):
                start = self.i
                try:
                    decls.append(self.routine_decl())
                except ParseError:
                    self.sync_decl()
                    if self.i == start:
                        self.advance()
            elif k == "LABEL":
                self.error("NOTSUPP", feature="LABEL (and GOTO)")
                self.advance()
                self.sync_decl()
            else:
                return decls

    def const_part(self) -> list[A.Node]:
        self.advance()
        out = []
        while self.at("IDENT") or (self.at("PLACEHOLDER") and self.peek().kind in ("=", ":=")):
            start = self.advance()
            try:
                if self.at(":="):
                    self.error("EQLEXP")
                    self.advance()
                else:
                    self.expect("=")
                value = self.expression()
                out.append(self.finish(A.ConstDecl(name=start.text, value=value), start))
                self.expect(";")
            except ParseError:
                self.sync_decl()
        return out

    def type_part(self) -> list[A.Node]:
        self.advance()
        out = []
        while self.at("IDENT") or (self.at("PLACEHOLDER") and self.peek().kind == "="):
            start = self.advance()
            try:
                self.expect("=")
                spec = self.type_spec()
                out.append(self.finish(A.TypeDecl(name=start.text, spec=spec), start))
                self.expect(";")
            except ParseError:
                self.sync_decl()
        return out

    def var_part(self) -> list[A.Node]:
        self.advance()
        out = []
        while (self.at("IDENT", "[")
               or (self.at("PLACEHOLDER") and self.peek().kind in (",", ":"))):
            start = self.tok
            try:
                attrs = self.attributes() if self.at("[") else []
                names = self.ident_list()
                self.expect(":")
                if self.at("["):
                    attrs += self.attributes()
                spec = self.type_spec()
                out.append(self.finish(A.VarDecl(names=names, spec=spec, attributes=attrs), start))
                self.expect(";")
            except ParseError:
                self.sync_decl()
        return out

    def attributes(self) -> list[str]:
        self.expect("[")
        attrs = [self.expect_ident().value]
        while self.accept(","):
            attrs.append(self.expect_ident().value)
        self.expect("]")
        return [a for a in attrs if isinstance(a, str)]

    def ident_list(self) -> list[str]:
        names = [self.expect_ident().text]
        while self.accept(","):
            names.append(self.expect_ident().text)
        return names

    def routine_decl(self) -> A.RoutineDecl:
        start = self.tok
        attrs = self.attributes() if self.at("[") else []
        if not self.at("PROCEDURE", "FUNCTION"):
            self.report_expected("PROCEDURE")
            raise ParseError
        is_func = self.advance().kind == "FUNCTION"
        name = self.expect_ident().text
        params: list[A.ParamDecl] = []
        has_params = False
        if self.at("PLACEHOLDER") and self.peek().kind in (";", ":", "("):
            self.advance()
        if self.at("("):
            params = self.formal_params()
            has_params = True
        result = None
        if is_func and self.accept(":"):
            result = self.param_type()
        self.skip_placeholders()
        self.expect(";")
        directive = None
        block = None
        if self.at("IDENT") and self.tok.value in ("FORWARD", "EXTERNAL", "EXTERN"):
            directive = "FORWARD" if self.tok.value == "FORWARD" else "EXTERNAL"
            self.advance()
            self.expect(";")
        else:
            block = self.block()
            self.expect(";")
        cls = A.FunctionDecl if is_func else A.ProcedureDecl
        node = cls(name=name, params=params, result=result, block=block, directive=directive,
                   attributes=attrs, has_params=has_params)
        return self.finish(node, start)

    def formal_params(self) -> list[A.ParamDecl]:
        self.expect("(")
        groups = []
        while True:
            if self.at("PLACEHOLDER") and self.peek().kind in (";", ")"):
                self.advance()
            elif self.at(")"):
                break
            else:
                start = self.tok
                by_ref = bool(self.accept("VAR"))
                names = self.ident_list()
                self.expect(":")
                spec = self.param_type()
                groups.append(self.finish(A.ParamDecl(names=names, spec=spec, by_ref=by_ref), start))
            if not self.accept(";"):
                break
        self.expect(")")
        return groups

    def param_type(self) -> A.TypeSpec:
        t = self.tok
        if t.kind == "IDENT":
            self.advance()
            return self.finish(A.NamedType(name=t.text), t)
        if t.kind == "PLACEHOLDER":
            self.advance()
            return self.finish(A.PlaceholderType(name=t.value, required=t.required, text_=t.text), t)
        self.error("PARAMTYPE")
        return self.type_spec()

    # -- types -------------------------------------------------------------
    def type_spec(self) -> A.TypeSpec:
        t = self.tok
        k = t.kind
        if k == "PACKED":
            self.advance()
            spec = self.type_spec()
            if isinstance(spec, (A.ArrayType, A.RecordType)):
                spec.packed = True
            return spec
        if k == "ARRAY":
            self.advance()
            self.expect("[")
            idx = [self.type_spec()]
            while self.accept(","):
                idx.append(self.type_spec())
            self.expect("]")
            self.expect("OF")
            elem = self.type_spec()
            return self.finish(A.ArrayType(indexes=idx, element=elem), t)
        if k == "RECORD":
            self.advance()
            fields = self.field_list()
            self.expect_end(t)
            return self.finish(A.RecordType(fields=fields), t)
        if k == "(":
            self.advance()
            names = self.ident_list()
            self.expect(")")
            return self.finish(A.EnumType(names=names), t)
        if k == "PLACEHOLDER":
            self.advance()
            return self.finish(A.PlaceholderType(name=t.value, required=t.required, text_=t.text), t)
        if k == "^":
            self.unsupported("pointer types (^)")
        if k in ("SET", "FILE"):
            self.unsupported(f"the {k} type")
        if k not in ("IDENT", "INT", "STRING", "+", "-"):
            self.error("TYPEEXP")
            raise ParseError
        low = self.simple_expression()
        if self.accept(".."):
            high = self.simple_expression()
            return self.finish(A.SubrangeType(low=low, high=high), t)
        if isinstance(low, A.Name):
            return self.finish(A.NamedType(name=low.name), t)
        if isinstance(low, A.PlaceholderExpr):
            return self.finish(A.PlaceholderType(name=low.name, required=low.required, text_=low.text), t)
        self.report_expected("..")
        raise ParseError

    def field_list(self) -> list[A.FieldDecl]:
        fields = []
        while self.at("IDENT", "PLACEHOLDER"):
            start = self.tok
            names = self.ident_list()
            self.expect(":")
            spec = self.type_spec()
            fields.append(self.finish(A.FieldDecl(names=names, spec=spec), start))
            if not self.accept(";"):
                break
        if self.at("CASE"):
            self.unsupported("variant records (CASE inside RECORD)")
        return fields

    def expect_end(self, opener: Token):
        if self.at("PLACEHOLDER"):
            self.skip_placeholders()
        if self.at("END"):
            self.advance()
            return
        self.error("ENDEXP", opener=opener.text.upper(), open_line=opener.line)

    # -- statements ----------------------------------------------------------
    def compound(self) -> A.Compound:
        begin = self.expect("BEGIN") or self.tok
        stmts = self.stmt_sequence({"END"})
        self.expect_end(begin)
        return self.finish(A.Compound(stmts=stmts), begin)

    def stmt_sequence(self, terminators: set[str]) -> list[A.Statement]:
        stmts = [self.statement()]
        while True:
            if self.at(";"):
                semi = self.advance()
                if self.at("ELSE"):
                    self.error("ELSESEMI", semi, force=True, prev_line=semi.line)
                    self.advance()
                    s = self.statement()
                    if stmts and isinstance(stmts[-1], A.If) and stmts[-1].else_part is None:
                        stmts[-1].else_part = s
                    continue
                stmts.append(self.statement())
                continue
            k = self.tok.kind
            if k in terminators or k in CLOSERS:
                break
            if k in STATEMENT_STARTS:
                if not (isinstance(stmts[-1], A.PlaceholderStmt) or k == "PLACEHOLDER"):
                    self.report_expected(";")
                stmts.append(self.statement())
                continue
            before = self.i
            self.error("SYNTAX", found=self.tok.text)
            self.sync({";"} | terminators | CLOSERS)
            if self.i == before:
                self.advance()
        return stmts

    def statement(self) -> A.Statement:
        start = self.tok
        try:
            return self._statement()
        except ParseError:
            self.sync({";", "END", "UNTIL", "ELSE", "OTHERWISE"})
            return self.finish(A.Empty(), start)

    def _statement(self) -> A.Statement:
        t = self.tok
        k = t.kind
        if k == "IDENT":
            return self.simple_statement()
        if k == "BEGIN":
            return self.compound()
        if k == "IF":
            self.advance()
            cond = self.expression()
            self.expect("THEN")
            then_part = self.statement()
            else_part = None
            if self.accept("ELSE"):
                else_part = self.statement()
            return self.finish(A.If(cond=cond, then_part=then_part, else_part=else_part), t)
        if k == "WHILE":
            self.advance()
            cond = self.expression()
            self.expect("DO")
            body = self.statement()
            return self.finish(A.While(cond=cond, body=body), t)
        if k == "REPEAT":
            self.advance()
            body = self.stmt_sequence({"UNTIL"})
            if self.at("PLACEHOLDER"):
                self.skip_placeholders()
            if self.accept("UNTIL"):
                cond = self.expression()
            else:
                self.report_expected("UNTIL")
                cond = self.finish(A.Name(name="TRUE"), self.tok)
            return self.finish(A.Repeat(body=body, cond=cond), t)
        if k == "FOR":
            self.advance()
            vt = self.expect_ident()
            if vt.kind == "PLACEHOLDER":
                var = self.finish(A.PlaceholderExpr(name=vt.value, required=vt.required, text=vt.text), vt)
            else:
                var = self.finish(A.Name(name=vt.text), vt)
            if self.at("="):
                self.error("ASSIGNEXP")
                self.advance()
            else:
                self.expect(":=")
            start = self.expression()
            down = False
            if self.accept("DOWNTO"):
                down = True
            elif not self.accept("TO"):
                self.report_expected("TO")
            stop = self.expression()
            self.expect("DO")
            body = self.statement()
            return self.finish(A.For(var=var, start=start, stop=stop, down=down, body=body), t)
        if k == "CASE":
            return self.case_statement()
        if k == "PLACEHOLDER":
            self.advance()
            return self.finish(A.PlaceholderStmt(name=t.value, required=t.required, text=t.text), t)
        if k in ("GOTO", "WITH"):
            self.unsupported(f"the {k} statement")
        return self.finish(A.Empty(), t)

    def simple_statement(self) -> A.Statement:
        t = self.tok
        target = self.designator()
        if self.accept(":="):
            value = self.expression()
            return self.finish(A.Assign(target=target, value=value), t)
        if self.at("="):
            self.error("EQASSIGN", target=A.unparse(target))
            self.advance()
            value = self.expression()
            return self.finish(A.Assign(target=target, value=value), t)
        if isinstance(target, A.Name):
            args = self.call_args() if self.at("(") else []
            return self.finish(A.ProcCall(name=target.name, args=args), t)
        self.report_expected(":=")
        raise ParseError

    def case_statement(self) -> A.Case:
        t = self.advance()
        selector = self.expression()
        self.expect("OF")
        arms = []
        otherwise = None
        while True:
            if self.at("PLACEHOLDER") and self.peek().kind not in (":", ",", ".."):
                self.advance()
                self.accept(";")
                continue
            if self.at("END", "EOF"):
                break
            if self.at("OTHERWISE", "ELSE"):
                self.advance()
                otherwise = self.stmt_sequence({"END"})
                break
            astart = self.tok
            try:
                labels = [self.case_label()]
                while self.accept(","):
                    labels.append(self.case_label())
                self.expect(":")
                body = self.statement()
                arms.append(self.finish(A.CaseArm(labels=labels, body=body), astart))
            except ParseError:
                self.sync({";", "END", "OTHERWISE"})
            if not self.accept(";"):
                if self.at("END", "OTHERWISE", "ELSE", "EOF"):
                    continue
                self.report_expected(";")
                if self.i == astart and not self.at("EOF"):
                    self.advance()
        self.expect_end(t)
        return self.finish(A.Case(selector=selector, arms=arms, otherwise=otherwise), t)

    def case_label(self) -> A.Node:
        t = self.tok
        low = self.expression()
        if self.accept(".."):
            high = self.expression()
            return self.finish(A.CaseRange(low=low, high=high), t)
        return low

    def call_args(self) -> list[A.Expr]:
        self.expect("(")
        args: list[A.Expr] = []
        if self.accept(")"):
            return args
        while True:
            start = self.tok
            a = self.expression()
            if self.at(":"):
                self.advance()
                width = self.expression()
                precision = None
                if self.accept(":"):
                    precision = self.expression()
                a = self.finish(A.WriteArg(value=a, width=width, precision=precision), start)
            args.append(a)
            if self.at("PLACEHOLDER") and self.peek().kind in (",", ")"):
                self.advance()
            if not self.accept(","):
                break
        self.expect(")")
        return args

    # -- expressions -----------------------------------------------------------
    def expression(self) -> A.Expr:
        t = self.tok
        left = self.simple_expression()
        if self.tok.kind in RELOPS:
            op = self.advance().kind
            right = self.simple_expression()
            left = self.finish(A.Binary(op=op, left=left, right=right), t)
            if self.tok.kind in RELOPS:
                self.error("CHAINREL")
                self.advance()
                self.simple_expression()
        elif self.at("IN"):
            self.unsupported("sets and the IN operator")
        return left

    def simple_expression(self) -> A.Expr:
        t = self.tok
        if self.at("+", "-"):
            op = self.advance().kind
            left = self.finish(A.Unary(op=op, operand=self.term()), t)
        else:
            left = self.term()
        while self.tok.kind in ADDOPS:
            op = self.advance().kind
            right = self.term()
            left = self.finish(A.Binary(op=op, left=left, right=right), t)
        return left

    def term(self) -> A.Expr:
        t = self.tok
        left = self.factor()
        while self.tok.kind in MULOPS:
            op = self.advance().kind
            right = self.factor()
            left = self.finish(A.Binary(op=op, left=left, right=right), t)
        return left

    def factor(self) -> A.Expr:
        t = self.tok
        k = t.kind
        if k == "INT":
            self.advance()
            return self.finish(A.IntLit(value=t.value), t)
        if k == "REAL":
            self.advance()
            return self.finish(A.RealLit(value=t.value, text=t.text), t)
        if k == "STRING":
            self.advance()
            return self.finish(A.StrLit(value=t.value), t)
        if k == "IDENT":
            if self.peek().kind == "(":
                self.advance()
                args = self.call_args()
                return self.finish(A.FuncCall(name=t.text, args=args), t)
            return self.designator()
        if k == "(":
            self.advance()
            e = self.expression()
            self.expect(")")
            return e
        if k == "NOT":
            self.advance()
            return self.finish(A.Unary(op="NOT", operand=self.factor()), t)
        if k in ("+", "-"):
            self.advance()
            return self.finish(A.Unary(op=k, operand=self.factor()), t)
        if k == "PLACEHOLDER":
            self.advance()
            return self.finish(A.PlaceholderExpr(name=t.value, required=t.required, text=t.text), t)
        if k == "[":
            self.unsupported("sets")
        if k in ("NIL", "^", "@"):
            self.unsupported("pointers")
        if k in UNSUPPORTED_KEYWORDS:
            self.unsupported(f'"{k}"')
        self.error("EXPREXP", found=t.text or "end of file")
        raise ParseError

    def designator(self) -> A.Expr:
        t = self.expect_ident()
        if t.kind == "PLACEHOLDER":
            node: A.Expr = self.finish(A.PlaceholderExpr(name=t.value, required=t.required, text=t.text), t)
        else:
            node = self.finish(A.Name(name=t.text), t)
        while True:
            if self.at("["):
                self.advance()
                idx = [self.expression()]
                while self.accept(","):
                    idx.append(self.expression())
                self.expect("]")
                node = self.finish(A.Index(base=node, indexes=idx), t)
            elif self.at(".") and self.peek().kind == "IDENT":
                self.advance()
                f = self.advance()
                node = self.finish(A.FieldRef(base=node, field_name=f.text), t)
            elif self.at("^"):
                self.unsupported("pointers")
            else:
                return node


def parse(text: str, filename: str = "<buffer>") -> tuple[A.Program | None, list[Diagnostic], list[Token]]:
    """Lex and parse ``text``. Returns (ast or None, diagnostics, tokens)."""
    tokens, diags = tokenize(text, filename)
    p = Parser(tokens, filename)
    ast = p.parse_unit()
    all_diags = diags + p.diagnostics
    all_diags.sort(key=lambda d: (d.line or 0, d.column or 0))
    return ast, all_diags, tokens

"""Parser for LSE language definition files (``languages/*.lse``).

The format follows VAX LSE's ``DEFINE`` commands::

    ! comment
    DEFINE LANGUAGE PASCAL
      /FILE_TYPES=(.PAS)
      /INITIAL_STRING="%{compilation_unit}%"
      /TAB_INCREMENT=2
    END DEFINE

    DEFINE TOKEN WHILE /LANGUAGE=PASCAL
      /DESCRIPTION="Repeat a statement as long as a test stays TRUE."
      /EXAMPLE="WHILE tries < 10 DO"
      /EXAMPLE="  tries := tries + 1"
      "WHILE %{boolean_expression}% DO"
      "  %{statement}%"
    END DEFINE

    DEFINE PLACEHOLDER statement /LANGUAGE=PASCAL /TYPE=MENU
      /SEPARATOR=";" /DUPLICATION=VERTICAL
      /DESCRIPTION="One action for the program to do."
      /EXAMPLE="WRITELN('Hello')"
      "assignment"   /PLACEHOLDER
      "IF"           /TOKEN
      "INTEGER"
    END DEFINE

Qualifiers may sit on the ``DEFINE`` line or on their own lines.
Quoted lines are the template body (tokens, nonterminal placeholders)
or the menu choices (menu placeholders); a choice marked ``/TOKEN``
expands that token, ``/PLACEHOLDER`` expands that placeholder, and an
unmarked choice is inserted as literal text. Inside quotes ``""`` is a
literal quote. Repeating ``/DESCRIPTION`` or ``/EXAMPLE`` adds lines.

Placeholder types: ``NONTERMINAL`` (expands to its body), ``MENU`` (the
user picks a choice) and ``TERMINAL`` (cannot be expanded; the user types
over it). Without ``/TYPE`` a placeholder with a body is NONTERMINAL and
one without is TERMINAL.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .placeholders import PLACEHOLDER_RE

PLACEHOLDER_TYPES = ("NONTERMINAL", "MENU", "TERMINAL")
DUPLICATIONS = ("CONTEXT_DEPENDENT", "VERTICAL", "HORIZONTAL")


class LangDefError(Exception):
    def __init__(self, filename: str, line: int, text: str) -> None:
        super().__init__(f"{filename}, line {line}: {text}")
        self.filename, self.line, self.text = filename, line, text


@dataclass
class MenuOption:
    text: str
    kind: str = "TEXT"  # TEXT, TOKEN or PLACEHOLDER
    description: str = ""


@dataclass
class TokenDef:
    name: str
    body: list[str] = field(default_factory=list)
    description: list[str] = field(default_factory=list)
    example: list[str] = field(default_factory=list)
    line: int = 0

    @property
    def summary(self) -> str:
        return self.description[0] if self.description else ""


@dataclass
class PlaceholderDef:
    name: str
    type: str = ""
    body: list[str] = field(default_factory=list)
    options: list[MenuOption] = field(default_factory=list)
    separator: str = ""
    duplication: str = "CONTEXT_DEPENDENT"
    description: list[str] = field(default_factory=list)
    example: list[str] = field(default_factory=list)
    line: int = 0

    @property
    def summary(self) -> str:
        return self.description[0] if self.description else ""

    @property
    def expandable(self) -> bool:
        return self.type in ("NONTERMINAL", "MENU")


@dataclass
class Language:
    name: str
    file_types: list[str] = field(default_factory=list)
    initial_string: list[str] = field(default_factory=list)
    tab_increment: int = 2
    tokens: dict[str, TokenDef] = field(default_factory=dict)
    placeholders: dict[str, PlaceholderDef] = field(default_factory=dict)
    source: str = ""

    @property
    def display_name(self) -> str:
        return self.name.capitalize()

    def token(self, name: str) -> TokenDef | None:
        return self.tokens.get(name.upper())

    def placeholder(self, name: str) -> PlaceholderDef | None:
        return self.placeholders.get(name.lower())

    def validate(self) -> list[str]:
        """Return a list of problems (empty when the definition is sound)."""
        problems: list[str] = []

        def check_refs(where: str, lines: list[str]) -> None:
            for text in lines:
                for m in PLACEHOLDER_RE.finditer(text):
                    if self.placeholder(m.group("name")) is None:
                        problems.append(f"{where}: undefined placeholder {m.group(0)}")

        check_refs("INITIAL_STRING", self.initial_string)
        for tok in self.tokens.values():
            where = f"TOKEN {tok.name}"
            if not tok.body:
                problems.append(f"{where}: empty body")
            if not tok.description:
                problems.append(f"{where}: missing /DESCRIPTION")
            if not tok.example:
                problems.append(f"{where}: missing /EXAMPLE")
            check_refs(where, tok.body)
        for ph in self.placeholders.values():
            where = f"PLACEHOLDER {ph.name}"
            if not ph.description:
                problems.append(f"{where}: missing /DESCRIPTION")
            if not ph.example:
                problems.append(f"{where}: missing /EXAMPLE")
            if ph.type == "NONTERMINAL" and not ph.body:
                problems.append(f"{where}: NONTERMINAL with empty body")
            if ph.type == "MENU" and not ph.options:
                problems.append(f"{where}: MENU with no choices")
            check_refs(where, ph.body)
            for opt in ph.options:
                if opt.kind == "TOKEN" and self.token(opt.text) is None:
                    problems.append(f"{where}: menu choice {opt.text!r} is not a token")
                if opt.kind == "PLACEHOLDER" and self.placeholder(opt.text) is None:
                    problems.append(f"{where}: menu choice {opt.text!r} is not a placeholder")
        return problems


# ----- tokenizer for one definition line -----------------------------------

_QUAL_RE = re.compile(r"/(?P<name>[A-Za-z_]+)(?:\s*=\s*)?")


def _read_string(text: str, i: int, fname: str, lineno: int) -> tuple[str, int]:
    assert text[i] == '"'
    out = []
    i += 1
    while i < len(text):
        ch = text[i]
        if ch == '"':
            if i + 1 < len(text) and text[i + 1] == '"':
                out.append('"')
                i += 2
                continue
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise LangDefError(fname, lineno, "unterminated string")


def _split_items(text: str, fname: str, lineno: int) -> list[tuple[str, object]]:
    """Split a line into ``("word", w)``, ``("string", s)`` and
    ``("qual", (name, value))`` items. Value is None, a str or a list."""
    items: list[tuple[str, object]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace() or ch == ",":
            i += 1
        elif ch == "!":
            break
        elif ch == '"':
            s, i = _read_string(text, i, fname, lineno)
            items.append(("string", s))
        elif ch == "/":
            m = _QUAL_RE.match(text, i)
            if not m:
                raise LangDefError(fname, lineno, f"bad qualifier at column {i + 1}")
            name = m.group("name").upper()
            has_value = "=" in m.group(0)
            i = m.end()
            value: object = None
            if has_value:
                value, i = _read_value(text, i, fname, lineno)
            items.append(("qual", (name, value)))
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '/"!,':
                j += 1
            items.append(("word", text[i:j]))
            i = j
    return items


def _read_value(text: str, i: int, fname: str, lineno: int) -> tuple[object, int]:
    n = len(text)
    if i < n and text[i] == '"':
        return _read_string(text, i, fname, lineno)
    if i < n and text[i] == "(":
        i += 1
        values: list[str] = []
        while i < n and text[i] != ")":
            if text[i].isspace() or text[i] == ",":
                i += 1
            elif text[i] == '"':
                s, i = _read_string(text, i, fname, lineno)
                values.append(s)
            else:
                j = i
                while j < n and not text[j].isspace() and text[j] not in ",)":
                    j += 1
                values.append(text[i:j])
                i = j
        if i >= n:
            raise LangDefError(fname, lineno, "missing ')'")
        return values, i + 1
    j = i
    while j < n and not text[j].isspace() and text[j] not in "/!":
        j += 1
    return text[i:j], j


# ----- parser ---------------------------------------------------------------


def parse(text: str, filename: str = "<string>") -> dict[str, Language]:
    """Parse definition text; return languages keyed by upper-case name."""
    languages: dict[str, Language] = {}
    current_lang: Language | None = None
    defn: dict | None = None

    def lang_for(name: str | None, lineno: int) -> Language:
        if name:
            lang = languages.get(name.upper())
            if lang is None:
                raise LangDefError(filename, lineno, f"language {name} is not defined yet")
            return lang
        if current_lang is None:
            raise LangDefError(filename, lineno, "no DEFINE LANGUAGE before this definition")
        return current_lang

    for lineno, raw in enumerate(text.splitlines(), start=1):
        items = _split_items(raw, filename, lineno)
        if not items:
            continue
        kind0, val0 = items[0]
        if kind0 == "word" and str(val0).upper() == "DEFINE":
            if defn is not None:
                raise LangDefError(filename, lineno, "DEFINE inside another DEFINE (missing END DEFINE?)")
            if len(items) < 3 or items[1][0] != "word":
                raise LangDefError(filename, lineno, "expected DEFINE LANGUAGE|TOKEN|PLACEHOLDER name")
            what = str(items[1][1]).upper()
            if what not in ("LANGUAGE", "TOKEN", "PLACEHOLDER"):
                raise LangDefError(filename, lineno, f"cannot DEFINE {what}")
            if items[2][0] not in ("word", "string"):
                raise LangDefError(filename, lineno, f"missing {what.lower()} name")
            defn = {"what": what, "name": str(items[2][1]), "line": lineno,
                    "quals": [], "body": []}
            rest = items[3:]
        elif kind0 == "word" and str(val0).upper() == "END":
            if defn is None:
                raise LangDefError(filename, lineno, "END DEFINE without DEFINE")
            if len(items) < 2 or str(items[1][1]).upper() != "DEFINE":
                raise LangDefError(filename, lineno, "expected END DEFINE")
            current_lang = _finish(defn, languages, current_lang, lang_for, filename)
            defn = None
            continue
        else:
            if defn is None:
                raise LangDefError(filename, lineno, f"unexpected text outside DEFINE: {raw.strip()}")
            rest = items
        _collect(defn, rest, filename, lineno)
    if defn is not None:
        raise LangDefError(filename, defn["line"], f"DEFINE {defn['what']} {defn['name']} has no END DEFINE")
    return languages


def _collect(defn: dict, items: list, fname: str, lineno: int) -> None:
    i = 0
    while i < len(items):
        kind, val = items[i]
        if kind == "qual":
            defn["quals"].append((val[0], val[1], lineno))
            i += 1
        elif kind == "string":
            entry = {"text": val, "quals": [], "line": lineno}
            i += 1
            while i < len(items) and items[i][0] == "qual":
                entry["quals"].append(items[i][1])
                i += 1
            defn["body"].append(entry)
        else:
            raise LangDefError(fname, lineno, f"unexpected word {val!r} (body lines must be quoted)")


def _as_text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(value)
    return "" if value is None else str(value)


def _finish(defn, languages, current_lang, lang_for, fname):
    what, name, line = defn["what"], defn["name"], defn["line"]
    quals = defn["quals"]
    body = defn["body"]
    if what == "LANGUAGE":
        lang = Language(name=name.upper(), source=fname)
        for qname, value, qline in quals:
            if qname == "FILE_TYPES":
                vals = value if isinstance(value, list) else [_as_text(value)]
                lang.file_types = [v if v.startswith(".") else "." + v for v in vals]
            elif qname == "INITIAL_STRING":
                lang.initial_string.extend(_as_text(value).split("\\n"))
            elif qname == "TAB_INCREMENT":
                try:
                    lang.tab_increment = int(_as_text(value))
                except ValueError:
                    raise LangDefError(fname, qline, "TAB_INCREMENT must be a number") from None
            else:
                raise LangDefError(fname, qline, f"unknown qualifier /{qname} for LANGUAGE")
        if body:
            raise LangDefError(fname, body[0]["line"], "DEFINE LANGUAGE takes no body lines")
        languages[lang.name] = lang
        return lang

    lang_name = None
    for qname, value, _ in quals:
        if qname == "LANGUAGE":
            lang_name = _as_text(value)
    lang = lang_for(lang_name, line)

    if what == "TOKEN":
        tok = TokenDef(name=name.upper(), line=line)
        for qname, value, qline in quals:
            if qname == "LANGUAGE":
                continue
            if qname == "DESCRIPTION":
                tok.description.append(_as_text(value))
            elif qname == "EXAMPLE":
                tok.example.append(_as_text(value))
            else:
                raise LangDefError(fname, qline, f"unknown qualifier /{qname} for TOKEN")
        for entry in body:
            if entry["quals"]:
                raise LangDefError(fname, entry["line"], "token body lines take no qualifiers")
            tok.body.append(entry["text"])
        if tok.name in lang.tokens:
            raise LangDefError(fname, line, f"token {tok.name} defined twice")
        lang.tokens[tok.name] = tok
        return current_lang

    ph = PlaceholderDef(name=name, line=line)
    for qname, value, qline in quals:
        if qname == "LANGUAGE":
            continue
        if qname == "DESCRIPTION":
            ph.description.append(_as_text(value))
        elif qname == "EXAMPLE":
            ph.example.append(_as_text(value))
        elif qname == "TYPE":
            ph.type = _as_text(value).upper()
            if ph.type not in PLACEHOLDER_TYPES:
                raise LangDefError(fname, qline, f"/TYPE must be one of {', '.join(PLACEHOLDER_TYPES)}")
        elif qname == "SEPARATOR":
            ph.separator = _as_text(value)
        elif qname == "DUPLICATION":
            ph.duplication = _as_text(value).upper()
            if ph.duplication not in DUPLICATIONS:
                raise LangDefError(fname, qline, f"/DUPLICATION must be one of {', '.join(DUPLICATIONS)}")
        else:
            raise LangDefError(fname, qline, f"unknown qualifier /{qname} for PLACEHOLDER")
    if not ph.type:
        ph.type = "NONTERMINAL" if body else "TERMINAL"
    for entry in body:
        if ph.type == "MENU":
            opt = MenuOption(text=entry["text"])
            for qname, value in entry["quals"]:
                if qname in ("TOKEN", "PLACEHOLDER"):
                    opt.kind = qname
                elif qname == "DESCRIPTION":
                    opt.description = _as_text(value)
                else:
                    raise LangDefError(fname, entry["line"], f"unknown menu qualifier /{qname}")
            ph.options.append(opt)
        else:
            if entry["quals"]:
                raise LangDefError(fname, entry["line"], "only MENU choices take qualifiers")
            ph.body.append(entry["text"])
    if ph.type == "TERMINAL" and body:
        raise LangDefError(fname, line, f"TERMINAL placeholder {name} cannot have a body")
    key = ph.name.lower()
    if key in lang.placeholders:
        raise LangDefError(fname, line, f"placeholder {ph.name} defined twice")
    lang.placeholders[key] = ph
    return current_lang


def load_file(path: str) -> dict[str, Language]:
    with open(path, encoding="utf-8") as f:
        return parse(f.read(), os.path.basename(path))


LANGUAGE_DIR = os.path.join(os.path.dirname(__file__), "languages")


class LanguageRegistry:
    """All languages from ``lse/languages/*.lse``, loaded on first use."""

    def __init__(self, directory: str = LANGUAGE_DIR) -> None:
        self.directory = directory
        self._languages: dict[str, Language] | None = None
        self.errors: list[str] = []

    @property
    def languages(self) -> dict[str, Language]:
        if self._languages is None:
            self._languages = {}
            try:
                names = sorted(os.listdir(self.directory))
            except OSError:
                names = []
            for entry in names:
                if entry.lower().endswith(".lse"):
                    try:
                        self._languages.update(load_file(os.path.join(self.directory, entry)))
                    except (LangDefError, OSError) as e:
                        self.errors.append(str(e))
        return self._languages

    def get(self, name: str) -> Language | None:
        return self.languages.get(name.upper())

    def for_file(self, filename: str) -> Language | None:
        ext = os.path.splitext(filename.split(";")[0])[1].lower()
        if not ext:
            return None
        for lang in self.languages.values():
            if ext in (t.lower() for t in lang.file_types):
                return lang
        return None

"""Command registry, ``LSE>`` command-line parser and Tab completion.

Commands have multi-word names (``GOTO FILE``, ``SET THEME``) that can be
abbreviated VMS-style to any unique prefix of each word (``GO F``,
``SET TH AMB``). Qualifiers follow a slash and may also be abbreviated:
``RUN/SEED=5``, ``COMPILE /LIST``, ``SET MESSAGES /NOEXPLAIN``.

Every key binding names a command from this registry, so anything a key
does can also be typed at ``LSE>``. Other layers (tutor, help library)
add their own commands with ``CommandRegistry.register``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable

from .files import split_version

if TYPE_CHECKING:
    from .editor import Editor

Completer = Callable[["Editor", str], Iterable[str]]


class CommandError(Exception):
    def __init__(self, ident: str, text: str) -> None:
        super().__init__(text)
        self.ident, self.text = ident, text


@dataclass
class Param:
    """A positional parameter.

    ``kind`` is ``text`` (one word or a quoted string), ``rest`` (the rest
    of the line), ``int``, ``choice`` (one of ``choices``), ``file`` or
    ``buffer``. A missing required parameter with a ``prompt`` is asked for
    on the command line, VMS style (``_File: ``).
    """

    name: str
    kind: str = "text"
    required: bool = False
    prompt: str | None = None
    choices: list[str] | Callable[["Editor"], list[str]] | None = None
    initial: Callable[["Editor"], str] | None = None
    completer: Completer | None = None

    def choice_list(self, editor: "Editor") -> list[str]:
        if callable(self.choices):
            return list(self.choices(editor))
        return list(self.choices or [])

    def complete(self, editor: "Editor", partial: str) -> list[str]:
        if self.completer is not None:
            return sorted(set(self.completer(editor, partial)))
        if self.kind == "choice":
            return [c for c in self.choice_list(editor) if c.upper().startswith(partial.upper())]
        if self.kind == "file":
            return complete_files(editor.cwd, partial)
        if self.kind == "buffer":
            return [b for b in editor.buffers if b.upper().startswith(partial.upper())]
        return []


@dataclass
class Qualifier:
    name: str
    kind: str = "flag"  # flag, int or text
    negatable: bool = False
    help: str = ""


@dataclass
class Command:
    name: str
    handler: Callable[["Editor", "Args"], Any]
    help: str = ""
    params: list[Param] = field(default_factory=list)
    qualifiers: list[Qualifier] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    group: str = "Editing"
    typing: bool = False

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def usage(self) -> str:
        parts = [self.name]
        for p in self.params:
            label = p.name if p.kind != "choice" or not isinstance(p.choices, list) \
                else "|".join(p.choices)
            parts.append(label if p.required else f"[{label}]")
        for q in self.qualifiers:
            if q.kind == "flag":
                parts.append(f"[/{'[NO]' if q.negatable else ''}{q.name}]")
            else:
                parts.append(f"[/{q.name}=n]" if q.kind == "int" else f"[/{q.name}=text]")
        return " ".join(parts)


@dataclass
class Args:
    params: dict[str, Any] = field(default_factory=dict)
    quals: dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def get(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)

    def __getitem__(self, name: str) -> Any:
        return self.params[name]

    def qual(self, name: str, default: Any = None) -> Any:
        return self.quals.get(name, default)


@dataclass
class Parsed:
    command: Command
    args: Args
    missing: list[Param] = field(default_factory=list)


@dataclass
class _Tok:
    value: str
    quoted: bool
    start: int
    end: int

    @property
    def head(self) -> str:
        if self.quoted:
            return self.value
        return self.value.split("/", 1)[0]

    @property
    def tail_quals(self) -> list[str]:
        if self.quoted or "/" not in self.value:
            return []
        return ["/" + q for q in self.value.split("/")[1:] if q]


def _tokenize(text: str) -> list[_Tok]:
    toks: list[_Tok] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        start = i
        if text[i] == '"':
            out = []
            i += 1
            while i < n:
                if text[i] == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        out.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                out.append(text[i])
                i += 1
            toks.append(_Tok("".join(out), True, start, i))
            continue
        while i < n and not text[i].isspace():
            if text[i] == '"' and "=" in text[start:i]:
                i += 1
                while i < n and text[i] != '"':
                    i += 1
            i += 1
        toks.append(_Tok(text[start:i], False, start, i))
    return toks


def quote(value: str) -> str:
    if value and not any(c.isspace() for c in value) and '"' not in value:
        return value
    return '"' + value.replace('"', '""') + '"'


def _common_prefix(words: list[str]) -> str:
    if not words:
        return ""
    lo, hi = min(words, key=str.upper).upper(), max(words, key=str.upper).upper()
    i = 0
    while i < min(len(lo), len(hi)) and lo[i] == hi[i]:
        i += 1
    return words[0][:i]


def complete_files(directory: str, partial: str) -> list[str]:
    head, leaf = os.path.split(partial)
    folder = os.path.join(directory, head) if not os.path.isabs(head) else head
    try:
        entries = os.listdir(folder or ".")
    except OSError:
        return []
    want_versions = ";" in leaf
    seen = set()
    out = []
    for entry in sorted(entries):
        if entry.startswith("."):
            continue
        name = entry if want_versions else split_version(entry)[0]
        if not name.upper().startswith(leaf.upper()) or name in seen:
            continue
        seen.add(name)
        full = os.path.join(folder, name)
        out.append(os.path.join(head, name) + ("/" if os.path.isdir(full) else ""))
    return out


@dataclass
class Completion:
    text: str
    candidates: list[str]


class CommandRegistry:
    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}

    def register(self, command: Command) -> Command:
        self.commands[command.name.upper()] = command
        return command

    def get(self, name: str) -> Command | None:
        return self.commands.get(" ".join(name.upper().split()))

    def __iter__(self):
        return iter(sorted(self.commands.values(), key=lambda c: c.name))

    def _entries(self) -> list[tuple[list[str], Command]]:
        out = []
        for cmd in self.commands.values():
            for name in cmd.names:
                out.append((name.upper().split(), cmd))
        return out

    # ----- parsing ------------------------------------------------------------

    def match(self, toks: list[_Tok]) -> tuple[Command, int]:
        cands: list[tuple[list[str], Command]] = []
        for words, cmd in self._entries():
            if len(words) > len(toks):
                continue
            if all(not toks[i].quoted and toks[i].head and words[i].startswith(toks[i].head.upper())
                   for i in range(len(words))):
                cands.append((words, cmd))
        if not cands:
            word = toks[0].head.upper() if toks else ""
            raise CommandError("NOSUCHCMD", f"no such command: {word}  (Tab shows the commands)")
        longest = max(len(w) for w, _ in cands)
        cands = [(w, c) for w, c in cands if len(w) == longest]
        exact = [(w, c) for w, c in cands
                 if all(toks[i].head.upper() == w[i] for i in range(len(w)))]
        if exact:
            cands = exact
        unique: dict[int, tuple[list[str], Command]] = {}
        for w, c in cands:
            unique.setdefault(id(c), (w, c))
        if len(unique) > 1:
            names = sorted({c.name for _, c in unique.values()})
            raise CommandError("AMBIGUOUS", "ambiguous command, could be: " + ", ".join(names))
        words, cmd = next(iter(unique.values()))
        return cmd, len(words)

    def parse(self, text: str, editor: "Editor | None" = None) -> Parsed:
        toks = _tokenize(text)
        if not toks:
            raise CommandError("NOCMD", "no command given")
        cmd, nwords = self.match(toks)
        qual_texts: list[str] = []
        for t in toks[:nwords]:
            qual_texts.extend(t.tail_quals)
        positionals: list[_Tok] = []
        rest_start: int | None = None
        for t in toks[nwords:]:
            if not t.quoted and t.value.startswith("/") and self._is_qualifier(cmd, t.value):
                qual_texts.append(t.value)
            else:
                if rest_start is None:
                    rest_start = t.start
                positionals.append(t)
        args = Args(text=text)
        for q in qual_texts:
            name, value = self._parse_qualifier(cmd, q)
            args.quals[name] = value
        missing: list[Param] = []
        pi = 0
        for idx, param in enumerate(cmd.params):
            if param.kind == "rest":
                if positionals[pi:]:
                    toks_left = positionals[pi:]
                    if len(toks_left) == 1 and toks_left[0].quoted:
                        value = toks_left[0].value
                    else:
                        value = text[toks_left[0].start:].strip()
                    args.params[param.name] = value
                    pi = len(positionals)
                elif param.required:
                    missing.append(param)
                continue
            if pi < len(positionals):
                args.params[param.name] = self._convert(param, positionals[pi], editor)
                pi += 1
            elif param.required:
                missing.append(param)
        if pi < len(positionals):
            extra = " ".join(t.value for t in positionals[pi:])
            raise CommandError("TOOMANYPARMS", f"too many parameters for {cmd.name}: {extra}")
        return Parsed(cmd, args, missing)

    @staticmethod
    def _qual_name(q: str) -> tuple[str, str | None]:
        body = q[1:]
        if "=" in body:
            name, value = body.split("=", 1)
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1].replace('""', '"')
            return name.upper(), value
        return body.upper(), None

    def _find_qualifier(self, cmd: Command, name: str) -> tuple[Qualifier, bool] | None:
        hits = [(q, False) for q in cmd.qualifiers if name and q.name.startswith(name)]
        if not hits and name.startswith("NO"):
            hits = [(q, True) for q in cmd.qualifiers
                    if q.negatable and len(name) > 2 and q.name.startswith(name[2:])]
        exact = [h for h in hits if h[0].name == (name[2:] if h[1] else name)]
        if exact:
            return exact[0]
        if len(hits) == 1:
            return hits[0]
        return None

    def _is_qualifier(self, cmd: Command, text: str) -> bool:
        return self._find_qualifier(cmd, self._qual_name(text)[0]) is not None or \
            not any(p.kind == "file" for p in cmd.params)

    def _parse_qualifier(self, cmd: Command, text: str) -> tuple[str, Any]:
        name, value = self._qual_name(text)
        found = self._find_qualifier(cmd, name)
        if found is None:
            known = ", ".join("/" + q.name for q in cmd.qualifiers) or "none"
            raise CommandError("IVQUAL", f"unknown qualifier /{name} for {cmd.name} (known: {known})")
        q, negated = found
        if q.kind == "flag":
            if value is not None:
                raise CommandError("NOVALUE", f"/{q.name} does not take a value")
            return q.name, not negated
        if negated or value is None:
            raise CommandError("VALREQ", f"/{q.name} needs a value, for example /{q.name}=5")
        if q.kind == "int":
            try:
                return q.name, int(value)
            except ValueError:
                raise CommandError("IVNUMBER", f"/{q.name} needs a number, not {value!r}") from None
        return q.name, value

    def _convert(self, param: Param, tok: _Tok, editor: "Editor | None") -> Any:
        value = tok.value
        if param.kind == "int":
            try:
                return int(value)
            except ValueError:
                raise CommandError("IVNUMBER", f"{param.name} must be a number, not {value!r}") from None
        if param.kind == "choice" and editor is not None:
            choices = param.choice_list(editor)
            hits = [c for c in choices if c.upper().startswith(value.upper())]
            exact = [c for c in hits if c.upper() == value.upper()]
            if exact:
                return exact[0]
            if len(hits) == 1:
                return hits[0]
            if not hits:
                raise CommandError("IVKEYW", f"{value} is not one of: {', '.join(choices)}")
            raise CommandError("AMBIGUOUS", f"{value} could be: {', '.join(hits)}")
        return value

    # ----- completion ---------------------------------------------------------

    def complete(self, text: str, editor: "Editor") -> Completion:
        """Complete the last word of ``text``; return new text and candidates."""
        toks = _tokenize(text)
        ends_space = not text or text[-1].isspace()
        partial = "" if ends_space or not toks else toks[-1].value
        done = toks if ends_space else toks[:-1]
        prefix_text = text[: len(text) - len(partial)] if partial else text
        words_done = [t for t in done if not (not t.quoted and t.value.startswith("/"))]
        cands: set[str] = set()
        upper_words = True

        for words, cmd in self._entries():
            k = len(words_done)
            if k >= len(words):
                continue
            if all(not words_done[i].quoted and words[i].startswith(words_done[i].head.upper())
                   for i in range(k)):
                if words[k].startswith(partial.upper()):
                    cands.add(words[k])
        param_cands: set[str] = set()
        try:
            cmd, nwords = self.match(words_done) if words_done else (None, 0)
        except CommandError:
            cmd, nwords = None, 0
        if cmd is not None:
            if partial.startswith("/"):
                pname = partial[1:].upper()
                for q in cmd.qualifiers:
                    for label in [q.name] + (["NO" + q.name] if q.negatable else []):
                        if label.startswith(pname):
                            cands.add("/" + label + ("=" if q.kind != "flag" else ""))
            else:
                idx = len(words_done) - nwords
                params = [p for p in cmd.params]
                if params:
                    if idx < len(params):
                        param = params[idx]
                    elif params[-1].kind == "rest":
                        param = params[-1]
                    else:
                        param = None
                    if param is not None:
                        param_cands = set(param.complete(editor, partial))
                        if param.kind in ("file", "buffer"):
                            upper_words = False
        all_cands = sorted(cands | param_cands, key=str.upper)
        if not all_cands:
            return Completion(text, [])
        command_toks = words_done if cands and not param_cands else words_done[:nwords]
        for t in command_toks:
            if not t.quoted and t.end <= len(prefix_text):
                prefix_text = prefix_text[:t.start] + t.value.upper() + prefix_text[t.end:]
        if len(all_cands) == 1:
            only = all_cands[0]
            tail = "" if only.endswith(("/", "=")) else " "
            return Completion(prefix_text + only + tail, all_cands)
        common = _common_prefix(all_cands)
        if len(common) > len(partial):
            fill = common.upper() if upper_words and not param_cands else common
            return Completion(prefix_text + fill, all_cands)
        return Completion(text, all_cands)

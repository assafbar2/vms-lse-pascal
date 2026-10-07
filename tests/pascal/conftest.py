import shutil
from pathlib import Path

import pytest

from pascal import api

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


class Builder:
    def __init__(self, directory: Path):
        self.dir = directory

    def write(self, name: str, source: str) -> Path:
        path = self.dir / f"{name}.PAS"
        path.write_text(source)
        return path

    def compile(self, name: str, source: str | None = None, **kw) -> api.CompileResult:
        if source is not None:
            self.write(name, source)
        return api.compile_file(self.dir / name, **kw)

    def build(self, name: str, source: str, *modules: tuple[str, str]) -> str:
        """Compile and link a program (plus modules); return the image path."""
        objs = []
        for mname, msrc in [(name, source), *modules]:
            r = self.compile(mname, msrc)
            assert r.ok, "\n".join(d.format() for d in r.diagnostics)
            objs.append(r.obj_path)
        lr = api.link(objs)
        assert lr.ok, "\n".join(d.format() for d in lr.diagnostics)
        return lr.exe_path

    def run(self, source: str, input_text: str = "", seed=None, name: str = "PROG", **kw) -> api.RunResult:
        exe = self.build(name, source)
        return api.run_image(exe, input_text=input_text, seed=seed, **kw)

    def output(self, source: str, input_text: str = "", **kw) -> str:
        r = self.run(source, input_text, **kw)
        assert r.error is None, r.output
        return r.output

    def copy_example(self, *names: str):
        for n in names:
            shutil.copy(EXAMPLES / f"{n}.PAS", self.dir / f"{n}.PAS")


@pytest.fixture
def pas(tmp_path) -> Builder:
    return Builder(tmp_path)


def errors_of(source: str, filename: str = "TEST.PAS") -> list[str]:
    """Message idents reported for ``source`` (parse + semantic analysis)."""
    return [d.ident for d in api.parse_source(source, filename).diagnostics]


@pytest.fixture
def idents():
    return errors_of


def wrap_body(body: str, decls: str = "") -> str:
    return f"PROGRAM T(INPUT, OUTPUT);\n{decls}\nBEGIN\n{body}\nEND.\n"


@pytest.fixture
def program():
    return wrap_body

"""Shared helpers for the editor tests (importable in any pytest import mode)."""

HELLO = """PROGRAM Hello(INPUT, OUTPUT);
BEGIN
  WRITELN('Hello, world')
END.
"""


def new_program(h, name="Hello"):
    """Open NEW.PAS and expand PROGRAM with a name; cursor on %[declarations]%..."""
    h.open("NEW.PAS")
    h.feed(f"<Tab><Enter>{name}<Tab>")
    return h

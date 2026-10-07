from lse import placeholders as ph
from lse.langdef import PlaceholderDef


def test_scan_finds_all_kinds():
    found = ph.scan(["x := %{expression}%;", "  %[statement]%... %{a}%%[b]%"])
    assert [(p.row, p.name, p.optional, p.is_list) for p in found] == [
        (0, "expression", False, False), (1, "statement", True, True),
        (1, "a", False, False), (1, "b", True, False)]
    assert found[1].text == "%[statement]%..."


def test_scan_ignores_pascal_comments_arrays_and_mismatches():
    assert ph.scan(["{ comment } a[1] := 2; %{oops]%"]) == []


def test_subrange_two_dots_is_not_a_list():
    found = ph.scan(["%{constant}%..%{constant}%"])
    assert len(found) == 2 and not found[0].is_list


def test_placeholder_at_and_navigation():
    lines = ["%{a}% x %{b}%", "%{c}%"]
    assert ph.placeholder_at(lines, 0, 0).name == "a"
    assert ph.placeholder_at(lines, 0, 4).name == "a"
    assert ph.placeholder_at(lines, 0, 5) is None
    nxt, wrapped = ph.next_placeholder(lines, 0, 0)
    assert nxt.name == "b" and not wrapped
    nxt, wrapped = ph.next_placeholder(lines, 1, 0)
    assert nxt.name == "a" and wrapped
    prv, wrapped = ph.previous_placeholder(lines, 0, 8)
    assert prv.name == "a" and not wrapped
    prv, wrapped = ph.previous_placeholder(lines, 0, 0)
    assert prv.name == "c" and wrapped
    assert ph.next_placeholder(["%{only}%"], 0, 0) is None


def test_word_at():
    assert ph.word_at("  WRITELN(", 9) == (2, 9, "WRITELN")
    assert ph.word_at("  IF x", 4) == (2, 4, "IF")
    assert ph.word_at("  ", 1) is None


def test_template_indents_and_places_cursor():
    lines = ["BEGIN", "  %{statement}%", "END"]
    res = ph.apply_template(lines, 1, 2, 15, ["WHILE %{c}% DO", "  %{statement}%"])
    assert res.lines == ["BEGIN", "  WHILE %{c}% DO", "    %{statement}%", "END"]
    assert res.cursor == (1, 8)


def test_template_without_placeholders_puts_cursor_at_end():
    res = ph.apply_template(["x : %{type}%;"], 0, 4, 12, ["INTEGER"])
    assert res.lines == ["x : INTEGER;"]
    assert res.cursor == (0, 11)


def test_vertical_duplication_adds_separator_and_copy():
    stmt = PlaceholderDef("statement", separator=";", duplication="VERTICAL")
    lines = ["BEGIN", "  %{statement}%...", "END."]
    p = ph.scan(lines)[0]
    dup = ph.duplication_for(p, stmt, lines[1])
    res = ph.apply_template(lines, 1, p.start, p.end, ["WRITELN(%{write_item}%...)"], dup)
    assert res.lines == ["BEGIN", "  WRITELN(%{write_item}%...);", "  %[statement]%...", "END."]
    assert res.cursor == (1, 10)


def test_horizontal_duplication():
    ident = PlaceholderDef("index_type", separator=", ", duplication="HORIZONTAL")
    lines = ["ARRAY [%{index_type}%...] OF INTEGER"]
    p = ph.scan(lines)[0]
    res = ph.apply_template(lines, 0, p.start, p.end, ["CHAR"], ph.duplication_for(p, ident, lines[0]))
    assert res.lines == ["ARRAY [CHAR, %[index_type]%...] OF INTEGER"]


def test_context_dependent_duplication():
    alone = ph.scan(["  %{x}%..."])[0]
    inline = ph.scan(["f(%{x}%...)"])[0]
    assert ph.duplication_for(alone, None, "  %{x}%...").vertical
    assert not ph.duplication_for(inline, None, "f(%{x}%...)").vertical
    assert ph.duplication_for(ph.scan(["%{x}%"])[0], None, "%{x}%") is None


def test_erase_line_and_list_separator():
    stmt = PlaceholderDef("statement", separator=";")
    lines = ["BEGIN", "  WRITELN('hi');", "  %[statement]%...", "END."]
    res = ph.erase(lines, ph.scan(lines)[0], stmt)
    assert res.lines == ["BEGIN", "  WRITELN('hi')", "END."]
    assert res.cursor == (1, 15)


def test_erase_horizontal_separator():
    ident = PlaceholderDef("identifier", separator=", ")
    lines = ["  a, %[identifier]%... : INTEGER;"]
    res = ph.erase(lines, ph.scan(lines)[0], ident)
    assert res.lines == ["  a : INTEGER;"]


def test_erase_inline_optional():
    lines = ["PROCEDURE P%[formal_parameters]%;"]
    assert ph.erase(lines, ph.scan(lines)[0]).lines == ["PROCEDURE P;"]


def test_erase_leftover_punctuation_joins_previous_line():
    lines = ["IF x THEN", "  y := 1", "%[else_part]%;", "z := 2"]
    res = ph.erase(lines, ph.scan(lines)[0])
    assert res.lines == ["IF x THEN", "  y := 1;", "z := 2"]


def test_erase_required_alone_removes_line():
    lines = ["VAR", "  %{x}%", "BEGIN"]
    assert ph.erase(lines, ph.scan(lines)[0]).lines == ["VAR", "BEGIN"]


def test_erase_last_line():
    assert ph.erase(["%{x}%"], ph.scan(["%{x}%"])[0]).lines == [""]

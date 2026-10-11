from pascal.lexer import tokenize


def kinds(text):
    toks, _ = tokenize(text)
    return [t.kind for t in toks]


def test_keywords_are_case_insensitive_and_identifiers_keep_spelling():
    toks, diags = tokenize("Program hello; BEGIN eNd.")
    assert [t.kind for t in toks] == ["PROGRAM", "IDENT", ";", "BEGIN", "END", ".", "EOF"]
    assert toks[1].text == "hello" and toks[1].value == "HELLO"
    assert diags == []


def test_numbers_and_ranges():
    toks, _ = tokenize("1..10 3.14 2E3 1.5e-2 42")
    assert [(t.kind, t.value) for t in toks[:-1]] == [
        ("INT", 1), ("..", ".."), ("INT", 10), ("REAL", 3.14), ("REAL", 2000.0),
        ("REAL", 0.015), ("INT", 42)]


def test_strings_with_doubled_quotes():
    toks, diags = tokenize("'It''s' 'x'")
    assert toks[0].value == "It's" and toks[1].value == "x"
    assert diags == []


def test_comments_both_styles():
    assert kinds("a { comment } b (* another *) c") == ["IDENT", "IDENT", "IDENT", "EOF"]


def test_vms_identifiers_with_dollar_and_underscore():
    toks, _ = tokenize("PAS$RANDOM my_var")
    assert toks[0].value == "PAS$RANDOM" and toks[1].value == "MY_VAR"


def test_lexical_errors():
    _, diags = tokenize("x := 'abc\ny := #;\n{ never closed")
    assert [d.ident for d in diags] == ["UNTERMSTR", "ILLCHAR", "UNTERMCOM"]
    assert diags[1].line == 2 and diags[1].column == 6


def test_double_quoted_string_gets_a_helpful_message():
    toks, diags = tokenize('WRITELN("Hello")')
    assert toks[2].kind == "STRING" and toks[2].value == "Hello"
    assert diags[0].ident == "DBLQUOTE"
    assert "'Hello'" in diags[0].hint


def test_integer_too_big_and_bad_number():
    _, diags = tokenize("x := 99999999999; y := 12abc")
    assert [d.ident for d in diags] == ["INTTOOBIG", "BADNUM"]


def test_placeholders_are_tokens_and_reported():
    toks, diags = tokenize("IF %{condition}% THEN %[statement]%...")
    ph = [t for t in toks if t.kind == "PLACEHOLDER"]
    assert [(t.value, t.required, t.text) for t in ph] == [
        ("condition", True, "%{condition}%"), ("statement", False, "%[statement]%...")]
    assert [d.ident for d in diags] == ["PLACEHOLDER", "PLACEHOLDER"]
    assert diags[0].text == "unexpanded placeholder %{condition}%"
    assert (diags[0].line, diags[0].column) == (1, 4)
    assert diags[0].end_column == 17


def test_nested_placeholder():
    toks, _ = tokenize("%[ELSE %{statement}%]% x")
    assert toks[0].kind == "PLACEHOLDER" and toks[0].value == "ELSE %{statement}%"
    assert toks[1].kind == "IDENT"

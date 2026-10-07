"""VMS-style messages for the compiler, linker and run-time system.

Every message looks like ``%FACILITY-S-IDENT, text`` and carries a
plain-English explanation and a hint, so that people new to Pascal can
understand what went wrong and what to do about it.

The catalog keeps two kinds of text for each message:

* ``explanation`` and ``hint`` are generic and contain no ``{fields}``;
  they are what :func:`get_message` returns.
* ``hint_detail`` (optional) is a template that is filled in with the
  details of one particular diagnostic, e.g. the line where a semicolon
  is missing. It is used when every field it needs is available.
"""

from __future__ import annotations

import string
import textwrap
from dataclasses import dataclass, field

SEVERITIES = ("S", "I", "W", "E", "F")
SEVERITY_NAMES = {
    "S": "success",
    "I": "informational",
    "W": "warning",
    "E": "error",
    "F": "fatal error",
}


@dataclass
class MessageInfo:
    facility: str
    ident: str
    severity: str
    template: str
    explanation: str
    hint: str
    hint_detail: str | None = field(default=None, repr=False)

    @property
    def code(self) -> str:
        return f"%{self.facility}-{self.severity}-{self.ident}"


@dataclass
class Diagnostic:
    file: str | None
    line: int | None
    column: int | None
    severity: str
    facility: str
    ident: str
    text: str
    explanation: str
    hint: str
    end_column: int | None = None

    @property
    def code(self) -> str:
        return f"%{self.facility}-{self.severity}-{self.ident}"

    @property
    def is_error(self) -> bool:
        return self.severity in ("E", "F")

    def location(self) -> str:
        if self.line is None:
            return ""
        if self.column is None:
            return f" at line {self.line}"
        return f" at line {self.line}, column {self.column}"

    def headline(self) -> str:
        return f"{self.code}, {self.text}{self.location()}"

    def format(self, explain: bool = True, width: int | None = None) -> str:
        lines = [self.headline()]
        if explain:
            lines.append("  Explanation: " + self.explanation)
            lines.append("  Hint: " + self.hint)
        if width:
            wrapped = []
            for i, ln in enumerate(lines):
                indent = "    " if i == 0 else " " * (ln.index(":") + 2)
                wrapped.extend(textwrap.wrap(ln, width, subsequent_indent=indent,
                                             break_on_hyphens=False) or [ln])
            lines = wrapped
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.headline()


def _m(facility, ident, severity, template, explanation, hint, hint_detail=None):
    return MessageInfo(facility, ident, severity, template, explanation, hint, hint_detail)


_CATALOG: list[MessageInfo] = [
    # ------------------------------------------------------------------
    # PASCAL: the compiler -- characters and words
    # ------------------------------------------------------------------
    _m("PASCAL", "ILLCHAR", "E", 'illegal character "{char}"',
       "This character has no meaning in Pascal, so the compiler cannot tell what you wanted.",
       "Delete the character, or put it inside a quoted string like 'this'.",
       'Delete "{char}", or put it inside a quoted string like \'{char}\'.'),
    _m("PASCAL", "DBLQUOTE", "E", "strings must be enclosed in single quotes (')",
       'Pascal writes text in single quotes, like \'Hello\'. Double quotes (") are not used.',
       "Replace each \" with ' -- for example WRITELN('Hello').",
       "Write the text as {fixed} instead."),
    _m("PASCAL", "UNTERMSTR", "E", "string is not terminated",
       "A string starts with ' and must end with ' on the same line. "
       "The compiler reached the end of the line before the closing quote.",
       "Add the closing ' at the end of the text. To put a quote inside a string, write it twice: 'It''s'."),
    _m("PASCAL", "UNTERMCOM", "E", "comment is not terminated",
       "A comment starts with { or (* and must end with } or *). "
       "The rest of the file was swallowed by the comment.",
       "Add } (or *) if the comment started with (*) where the comment should end."),
    _m("PASCAL", "PLACEHOLDER", "E", "unexpanded placeholder {placeholder}",
       "Placeholders like %{statement}% mark a spot in a template that still needs to be filled in. "
       "The compiler cannot compile a program that still contains one.",
       "Move to the placeholder (Tab) and type over it, expand it, or erase it (Ctrl-K) if you do not need it.",
       "Move to {placeholder} (Tab) and type over it, expand it, or erase it (Ctrl-K) if you do not need it."),
    _m("PASCAL", "BADNUM", "E", 'badly formed number "{text}"',
       "Numbers are digits, optionally with a decimal point and digits after it (3.14) "
       "or an exponent (1.5E3). This number does not follow that pattern.",
       "Check the number: a REAL needs digits on both sides of the point, like 0.5 rather than .5 or 5."),
    _m("PASCAL", "INTTOOBIG", "E", "integer constant {text} is larger than MAXINT (2147483647)",
       "INTEGER values must fit in 32 bits, so the largest one is 2147483647.",
       "Use a smaller number, or write it as a REAL (for example 1.0E10) if you need big values."),
    # ------------------------------------------------------------------
    # PASCAL: the compiler -- syntax
    # ------------------------------------------------------------------
    _m("PASCAL", "PROGEXP", "F", '"PROGRAM" or "MODULE" expected',
       "Every Pascal source file starts with a heading such as PROGRAM Hello(OUTPUT); "
       "(a program you can run) or MODULE Name; (a piece to LINK with a program).",
       "Start the file with PROGRAM Name(INPUT, OUTPUT); -- in LSE, type PROGRAM and press Tab."),
    _m("PASCAL", "SEMIEXP", "E", '";" expected',
       "Pascal statements and declarations are separated by semicolons. "
       "The compiler found the start of something new before the previous one was ended with \";\".",
       'Add ";" at the end of the previous statement or declaration.',
       'Add ";" at the end of line {prev_line}, after "{prev_text}".'),
    _m("PASCAL", "PERIODEXP", "E", '"." expected after the final END',
       'A program ends with END followed by a full stop: "END." The full stop tells the compiler '
       "the program is finished.",
       'Put a "." right after the last END of the program.'),
    _m("PASCAL", "COLONEXP", "E", '":" expected',
       'A colon separates a name from its type, as in "count : INTEGER", '
       'and a CASE label from its statement.',
       'Add ":" between the name and its type, for example "guess : INTEGER".'),
    _m("PASCAL", "ASSIGNEXP", "E", '":=" expected',
       'An assignment gives a variable a new value and is written with ":=", as in "tries := 0".',
       'Write ":=" between the variable and the new value, for example "tries := tries + 1".'),
    _m("PASCAL", "EQASSIGN", "E", '"=" found where ":=" (assignment) is needed',
       'In Pascal, "=" only compares two values (IF x = 5 THEN ...). '
       'To store a value in a variable you need ":=", which reads "becomes".',
       'Change "=" to ":=", for example "secret := 42".',
       'Change "=" to ":=" here: "{target} := ...".'),
    _m("PASCAL", "EQLEXP", "E", '"=" expected',
       'Constant and type declarations use "=", as in "CONST Max = 100;" or "TYPE Digit = 0..9;".',
       'Put "=" between the name and its value (":=" is only for assignments in statements).'),
    _m("PASCAL", "RPAREXP", "E", '")" expected',
       "Every opening parenthesis ( needs a matching closing parenthesis ).",
       'Add ")" to close the list or expression that was opened earlier.'),
    _m("PASCAL", "RBRACKEXP", "E", '"]" expected',
       "Array subscripts and array bounds are written in square brackets, like a[i] or ARRAY [1..10] OF INTEGER. "
       "The closing ] is missing.",
       'Add "]" after the subscript or bounds.'),
    _m("PASCAL", "LBRACKEXP", "E", '"[" expected',
       "An array type gives its index range in square brackets: ARRAY [1..10] OF INTEGER.",
       'Write the bounds in square brackets after ARRAY, for example ARRAY [1..10] OF INTEGER.'),
    _m("PASCAL", "THENEXP", "E", '"THEN" expected',
       "An IF statement has the form IF condition THEN statement. The word THEN is missing after the condition.",
       'Add THEN after the condition, for example "IF guess < secret THEN".'),
    _m("PASCAL", "DOEXP", "E", '"DO" expected',
       "WHILE and FOR loops have the form WHILE condition DO statement and FOR i := 1 TO n DO statement.",
       "Add DO before the statement that is to be repeated."),
    _m("PASCAL", "OFEXP", "E", '"OF" expected',
       'The word OF is needed in "CASE selector OF" and in "ARRAY [...] OF type".',
       "Add OF in the position shown."),
    _m("PASCAL", "TOEXP", "E", '"TO" or "DOWNTO" expected',
       "A FOR loop counts from a start value TO an end value (or DOWNTO when counting down): "
       "FOR i := 1 TO 10 DO ...",
       "Write TO (counting up) or DOWNTO (counting down) between the start and the end value."),
    _m("PASCAL", "ENDEXP", "E", '"END" expected',
       "Every BEGIN, CASE and RECORD must be closed by a matching END. "
       "The compiler reached a point where it needed END.",
       "Add END to close the BEGIN (or CASE/RECORD); check that each BEGIN has its own END.",
       'Add END to close the {opener} at line {open_line}.'),
    _m("PASCAL", "UNTILEXP", "E", '"UNTIL" expected',
       "A REPEAT loop has the form REPEAT statements UNTIL condition.",
       "Add UNTIL followed by the condition that ends the loop."),
    _m("PASCAL", "BEGINEXP", "E", '"BEGIN" expected',
       "The statements of a program, procedure or function are written between BEGIN and END, "
       "after the declarations.",
       "Add BEGIN before the first statement."),
    _m("PASCAL", "DOTDOTEXP", "E", '".." expected',
       'A range is written as two values separated by "..", for example 1..10 or \'A\'..\'Z\'.',
       'Write the range with two dots between the bounds, like 1..100.'),
    _m("PASCAL", "IDENTEXP", "E", "identifier expected",
       "A name (identifier) was expected here. Names start with a letter and may contain letters, "
       "digits and underscores; they cannot be reserved words like BEGIN or END.",
       "Write a name here, such as count or total.",
       'Write a name here; "{found}" cannot be used as a name.'),
    _m("PASCAL", "EXPREXP", "E", "expression expected",
       "A value was expected here: a number, a quoted string, a variable, or a calculation like x + 1.",
       "Write the value or calculation that belongs here.",
       'Write a value or calculation here; "{found}" cannot start one.'),
    _m("PASCAL", "TYPEEXP", "E", "type expected",
       "After the colon in a declaration the compiler expects a type such as INTEGER, REAL, "
       "BOOLEAN, CHAR, a range like 1..10, or ARRAY/RECORD.",
       "Write a type, for example INTEGER."),
    _m("PASCAL", "SYMEXP", "E", '"{expected}" expected',
       "The compiler expected a particular word or symbol here to complete the statement or declaration.",
       "Add the missing symbol in the position shown.",
       'Add "{expected}" in the position shown.'),
    _m("PASCAL", "SYNTAX", "E", 'syntax error at "{found}"',
       "The compiler did not expect this word or symbol here, so it could not understand the statement.",
       "Look at this spot and the end of the line before it; something is missing or out of place.",
       'Look at "{found}" and the line before it; something is missing or out of place.'),
    _m("PASCAL", "ELSESEMI", "E", '";" is not allowed before ELSE',
       "IF ... THEN ... ELSE ... is one statement. A semicolon before ELSE ends the IF statement early, "
       "so the ELSE has nothing to belong to.",
       'Delete the ";" just before ELSE.',
       'Delete the ";" at the end of line {prev_line}, just before ELSE.'),
    _m("PASCAL", "CHAINREL", "E", "comparisons cannot be chained",
       "Pascal cannot test two comparisons at once, such as 1 <= x <= 10.",
       "Write each comparison in parentheses and join them with AND: (1 <= x) AND (x <= 10)."),
    _m("PASCAL", "EXTRATEXT", "W", 'text after the final "END." is ignored',
       'The full stop after the last END marks the end of the program; anything after it is ignored.',
       'Remove the extra text, or move it before the final "END." if it belongs to the program.'),
    _m("PASCAL", "NOTSUPP", "E", '{feature} is not supported in this Pascal subset',
       "This is a real Pascal feature, but this teaching compiler leaves it out to keep things simple "
       "(pointers, sets, files, WITH and GOTO are not available).",
       "Rewrite this part using arrays, records, procedures and loops instead."),
    _m("PASCAL", "PARAMTYPE", "E", "parameter type must be a type name",
       "In a parameter list, each type must be a single name such as INTEGER or a type you declared "
       "in a TYPE section. A full ARRAY or RECORD description is not allowed there.",
       "Declare the type first, e.g. TYPE List = ARRAY [1..10] OF INTEGER; and then use \"x : List\"."),
    _m("PASCAL", "MODBODY", "E", "a MODULE cannot have a main program body",
       "A MODULE only contains declarations (constants, types, variables, procedures and functions) "
       "for other programs to use. It has no BEGIN ... END of its own and ends with END.",
       'Remove the BEGIN ... statements part, or change MODULE to PROGRAM if this is meant to run.'),
    _m("PASCAL", "TOOMANYERR", "F", "too many errors; compilation abandoned",
       "After this many errors, later messages are usually caused by the earlier ones.",
       "Fix the first few errors and compile again."),
    _m("PASCAL", "OPENIN", "F", 'error opening "{file}" as input',
       "The compiler could not read the source file. It may not exist, or the name may be misspelled.",
       "Check the file name and the directory you are in. Pascal source files end in .PAS."),
    _m("PASCAL", "OPENOUT", "F", 'error opening "{file}" as output',
       "The compiler could not write one of its output files (object, diagnostics or listing).",
       "Check that the directory is writable and the disk is not full."),
    _m("PASCAL", "BADATTR", "W", 'attribute [{attr}] is ignored',
       "This compiler understands the [GLOBAL] and [EXTERNAL] attributes; other attributes are ignored.",
       "Remove the attribute, or use [GLOBAL] / [EXTERNAL] for separate compilation."),
    _m("PASCAL", "PROGPARAM", "W", 'program parameter "{name}" is ignored',
       "Only the standard files INPUT (the keyboard) and OUTPUT (the screen) can be listed in the "
       "program heading; this subset has no other files.",
       "Use PROGRAM Name(INPUT, OUTPUT);"),
    # ------------------------------------------------------------------
    # PASCAL: the compiler -- meaning (declarations and types)
    # ------------------------------------------------------------------
    _m("PASCAL", "UNDECLID", "E", 'undeclared identifier "{name}"',
       "Pascal needs every name to be declared before it is used. "
       "This name was not found in any CONST, TYPE or VAR section, or as a procedure or function.",
       "Check the spelling, or declare it before use, for example in a VAR section.",
       'Check the spelling of "{name}", or declare it before use, e.g. VAR {name} : INTEGER;'),
    _m("PASCAL", "MULDECL", "E", '"{name}" is already declared in this block',
       "Each name can be declared only once in the same program, procedure or function. "
       "Pascal does not tell upper and lower case apart, so Count and COUNT are the same name.",
       "Use a different name, or delete the extra declaration.",
       'Use a different name, or delete one of the declarations of "{name}" (the first is at line {first_line}).'),
    _m("PASCAL", "NOTVAR", "E", '"{name}" is not a variable',
       "Only variables can be given new values (or be read into). "
       "Constants, types and procedures cannot be changed.",
       "Assign to a variable declared in a VAR section instead.",
       '"{name}" is a {what}; assign to a variable declared in a VAR section instead.'),
    _m("PASCAL", "NOTPROC", "E", '"{name}" is not a procedure',
       "A statement can call a procedure (like WRITELN), but this name is something else, "
       "so it cannot be used as a statement on its own.",
       "If you meant to change a variable, write an assignment like name := value.",
       '"{name}" is a {what}; if you meant to change it, write "{name} := value".'),
    _m("PASCAL", "FUNCSTMT", "E", 'the result of function "{name}" is not used',
       "A function calculates a value, so it must be used inside an expression; "
       "it cannot be a statement on its own like a procedure.",
       "Use the result, for example x := Name(...) or WRITELN(Name(...)).",
       "Use the result, for example x := {name}(...) or WRITELN({name}(...))."),
    _m("PASCAL", "NOTFUNC", "E", '"{name}" is a procedure and has no value',
       "Procedures carry out actions but do not return a value, so they cannot be used inside an expression.",
       "Call the procedure as a statement on its own, or turn it into a FUNCTION that returns a value."),
    _m("PASCAL", "NOTTYPE", "E", '"{name}" is not a type',
       "A type name was expected here (INTEGER, REAL, BOOLEAN, CHAR, or a name from a TYPE section).",
       "Use a type name such as INTEGER, or declare the type in a TYPE section.",
       '"{name}" is a {what}; use a type name such as INTEGER here.'),
    _m("PASCAL", "BADUSE", "E", '"{name}" is a {what} and cannot be used here',
       "This name is declared, but as a different kind of thing than this place needs "
       "(for example a type where a value is needed).",
       "Use a variable or constant here, or check that you picked the right name."),
    _m("PASCAL", "NOTCONST", "E", "constant value expected",
       "This place needs a value the compiler can work out before the program runs: "
       "a number, a quoted character, or a name from a CONST section.",
       "Use a literal value like 10 or 'A', or a constant declared in a CONST section."),
    _m("PASCAL", "INCASSIGN", "E", "cannot assign a value of type {source} to {target_name} of type {target}",
       "A variable can only hold values of its own type, so the value on the right of := must match "
       "the type of the variable on the left.",
       "Change the value so its type matches the variable, or declare the variable with a different type."),
    _m("PASCAL", "REALINT", "E", "cannot assign a REAL value to INTEGER variable {target_name}",
       "INTEGER variables hold whole numbers only. A REAL value (anything with a decimal point, "
       "or any result of \"/\") could have a fractional part.",
       "Use ROUND(x) or TRUNC(x) to turn the value into an INTEGER, or use DIV instead of / for whole-number division."),
    _m("PASCAL", "INCOPERAND", "E", 'operator "{op}" cannot be used with a value of type {type}',
       "Each operator works only on certain types: + - * / on numbers, AND OR NOT on BOOLEAN values.",
       "Check the value's type; you may need a different operator or a different variable."),
    _m("PASCAL", "INCOMPTYPES", "E", 'operator "{op}" cannot combine {left} with {right}',
       "Both sides of this operator must have compatible types, such as two numbers or two characters.",
       "Make both sides the same kind of value, e.g. compare a CHAR with 'A' and an INTEGER with 65."),
    _m("PASCAL", "REALDIV", "E", '"{op}" needs INTEGER operands',
       "DIV (whole-number division) and MOD (remainder) only work on INTEGER values.",
       "Use / to divide REAL values, or turn the value into an INTEGER first with ROUND or TRUNC."),
    _m("PASCAL", "BOOLOPINT", "E", '"{op}" needs BOOLEAN operands, found {type}',
       "AND and OR join two TRUE/FALSE conditions. In Pascal they bind more tightly than comparisons, "
       "so x > 0 AND x < 10 is read as x > (0 AND x) < 10.",
       "Put each comparison in parentheses: (x > 0) AND (x < 10)."),
    _m("PASCAL", "NOTBOOL", "E", "condition must be BOOLEAN, found {type}",
       "IF, WHILE and UNTIL need a condition that is either TRUE or FALSE, usually a comparison like guess = secret.",
       "Write a comparison here, such as count > 0.",
       "Write a comparison here, such as {example}."),
    _m("PASCAL", "ARGCOUNT", "E", '"{name}" needs {expected} argument(s) but {found} given',
       "A call must supply exactly one value for each parameter in the procedure or function heading.",
       "Look at the heading of the procedure or function and pass one value for each parameter."),
    _m("PASCAL", "ARGTYPE", "E", 'argument {n} of "{name}" has type {found}, but {expected} is needed',
       "Each value passed in a call must match the type of the corresponding parameter.",
       "Pass a value of the right type for this parameter."),
    _m("PASCAL", "VARARG", "E", 'argument {n} of "{name}" must be a variable',
       "This parameter is a VAR parameter (or the argument of READ/READLN): the procedure stores a "
       "value into it, so you must pass a variable, not a constant or calculation.",
       "Pass the name of a variable here."),
    _m("PASCAL", "VARTYPE", "E", 'VAR argument {n} of "{name}" has type {found}, but must be exactly {expected}',
       "A VAR parameter shares the caller's variable, so both must have exactly the same type.",
       "Pass a variable declared with exactly the parameter's type."),
    _m("PASCAL", "NOTARRAY", "E", "{what} is not an array, so it cannot be subscripted",
       "Square brackets select one element of an array, like scores[3]. This value is not an array.",
       "Remove the [ ... ], or declare the variable as an ARRAY."),
    _m("PASCAL", "NOTRECORD", "E", '{what} is not a record, so it has no field "{field}"',
       'A dot selects a field of a RECORD, like person.age. This value is not a record.',
       "Remove the .field part, or declare the variable as a RECORD."),
    _m("PASCAL", "NOFIELD", "E", 'record has no field named "{field}"',
       "The record type does not contain a field with this name.",
       "Check the spelling against the RECORD declaration."),
    _m("PASCAL", "INDEXTYPE", "E", "array index must be of type {expected}, found {found}",
       "The value inside [ ] must have the same type as the array's index range.",
       "Use an index of the type given in the ARRAY declaration."),
    _m("PASCAL", "INDEXCOUNT", "E", "too many subscripts",
       "The array has fewer dimensions than the number of subscripts given.",
       "Remove the extra subscripts; give one subscript per dimension of the array."),
    _m("PASCAL", "NOTORDINAL", "E", "{what} must be an ordinal type, found {type}",
       "An ordinal type has values that can be counted one by one: INTEGER, CHAR, BOOLEAN, "
       "or a range like 1..10. REAL, strings, arrays and records are not ordinal.",
       "Use an INTEGER, CHAR or BOOLEAN value (or a subrange) here."),
    _m("PASCAL", "FORVAR", "E", "FOR loop control variable must be a simple ordinal variable",
       "The variable that counts in a FOR loop must be a plain variable (not an array element or field) "
       "of an ordinal type such as INTEGER or CHAR.",
       "Declare a variable such as VAR i : INTEGER; and use it as the loop counter."),
    _m("PASCAL", "CASETYPE", "E", "CASE label does not match the type of the selector",
       "Each CASE label must be a constant of the same type as the value being tested.",
       "Use labels of the selector's type, e.g. numbers for an INTEGER selector, quoted characters for a CHAR."),
    _m("PASCAL", "DUPCASE", "E", "CASE label {label} is used more than once",
       "Each value may appear only once among the labels of a CASE statement.",
       "Remove the duplicate label or merge the two branches."),
    _m("PASCAL", "OUTOFRANGE", "E", "value {value} is out of range {low}..{high}",
       "The value is outside the range allowed by the type of the variable or array index.",
       "Use a value inside the range, or widen the range in the declaration."),
    _m("PASCAL", "BADRANGE", "E", "lower bound {low} is greater than upper bound {high}",
       "A range like 1..10 must start with the smaller value.",
       "Swap the bounds so the smaller one comes first."),
    _m("PASCAL", "CONSTEXPR", "E", "expression must be a constant",
       "Range bounds, CASE labels and CONST values must be known when the program is compiled, "
       "so they cannot use variables or function calls.",
       "Use numbers, quoted characters or names from a CONST section here."),
    _m("PASCAL", "STRLENGTH", "E", "a string of length {length} does not fit in {type}",
       "The string is longer than the character array it is assigned to.",
       "Shorten the string or make the array bigger."),
    _m("PASCAL", "READTYPE", "E", "cannot READ a value of type {type}",
       "READ and READLN can read INTEGER, REAL and CHAR values, and text into a character array.",
       "Read into an INTEGER, REAL or CHAR variable instead."),
    _m("PASCAL", "WRITETYPE", "E", "cannot WRITE a value of type {type}",
       "WRITE and WRITELN can print numbers, characters, BOOLEAN values, strings and character arrays, "
       "but not whole arrays of numbers or records.",
       "Write the elements or fields one at a time, for example with a FOR loop."),
    _m("PASCAL", "WIDTHTYPE", "E", "field width must be an INTEGER",
       'The value after ":" in WRITE says how many characters wide the output should be, so it must be a whole number.',
       "Use an INTEGER field width, for example WRITELN(x:5)."),
    _m("PASCAL", "PRECREAL", "E", 'decimal places (a second ":") can only be given for REAL values',
       'x:8:2 prints a REAL in 8 columns with 2 decimal places. Other types have no decimal places.',
       'Remove the second ":" part, or make the value REAL.'),
    _m("PASCAL", "WIDTHUSE", "E", 'field widths (":") are only allowed in WRITE and WRITELN',
       'The form value:width only makes sense when printing.',
       'Remove the ":" and the width.'),
    _m("PASCAL", "NORESULT", "W", 'function "{name}" never assigns its result',
       "A function returns its value by assigning to its own name, like Square := x * x. "
       "This function never does that, so calling it will fail.",
       "Add an assignment to the function name before its END.",
       "Add an assignment such as {name} := ... before the function's END."),
    _m("PASCAL", "FWDNOTDEF", "E", 'FORWARD routine "{name}" is never defined',
       "A FORWARD declaration promises that the full procedure or function follows later in the same block, "
       "but it never appeared.",
       "Write the full PROCEDURE or FUNCTION later in the same block, or remove the FORWARD declaration."),
    _m("PASCAL", "HEADMISMAT", "E", 'heading of "{name}" does not match its FORWARD declaration',
       "When a routine was declared FORWARD, its later definition must have the same parameters "
       "(or leave the parameter list out entirely).",
       "Make the parameters match, or write just PROCEDURE Name; for the later definition."),
    _m("PASCAL", "ATTRLEVEL", "E", "[{attr}] can only be used at the outermost level",
       "[GLOBAL] and [EXTERNAL] share names between separately compiled files, "
       "which only works for declarations at the outermost level, not inside a procedure.",
       "Move the declaration out to the program or module level."),
    _m("PASCAL", "EXTBODY", "E", 'EXTERNAL routine "{name}" cannot have a body',
       "An EXTERNAL routine is defined in another module; this file only describes its heading.",
       "End the heading with EXTERNAL; and remove the BEGIN ... END, or remove [EXTERNAL]."),
    _m("PASCAL", "FUNCTYPE", "E", "a function result must be a simple type, found {type}",
       "Functions return one simple value: INTEGER, REAL, BOOLEAN, CHAR or a subrange.",
       "Return a simple value, or use a procedure with a VAR parameter to hand back an array or record."),
    # ------------------------------------------------------------------
    # LINK: the linker
    # ------------------------------------------------------------------
    _m("LINK", "OPENIN", "F", 'error opening "{file}" as input',
       "The linker could not read an object file. Object files (.OBJ) are made by compiling a .PAS file.",
       "Compile the source first (PASCAL name), and check the spelling of the file name.",
       "Compile the source first (PASCAL {stem}), and check the spelling of the file name."),
    _m("LINK", "BADOBJ", "F", '"{file}" is not a valid object file: {reason}',
       "The file does not have the layout of an object file made by the Pascal compiler, "
       "perhaps because it was edited by hand or written by another program.",
       "Compile the source file again to make a fresh .OBJ file."),
    _m("LINK", "BADLIB", "F", 'library "{file}" is damaged: {reason}',
       "The run-time library PASRTL.OLB, which supplies WRITELN, READLN, RANDOM and friends, could not be read.",
       "Reinstall the toolchain, or regenerate the library with: python -m pascal.rtl"),
    _m("LINK", "NOFILES", "F", "no object files given",
       "LINK needs at least one object file to build a program from.",
       "Give the name of the compiled program, for example LINK HELLO."),
    _m("LINK", "UNDFSYMS", "W", "undefined symbol {symbol} referenced in module {module}",
       "The module uses a procedure, function or variable declared [EXTERNAL], "
       "but none of the object files being linked defines it as [GLOBAL].",
       "Add the object file that defines it to the LINK command (LINK MAIN, OTHER), "
       "or check that it is declared [GLOBAL] there with the same spelling.",
       "Add the object file that defines {symbol} to the LINK command (LINK {module}, OTHER), "
       "or check that it is declared [GLOBAL] there with the same spelling."),
    _m("LINK", "NOIMGFIL", "E", "image file not created",
       "Because of the errors above, the linker did not write an executable image (.EXE).",
       "Fix the problems reported above and LINK again."),
    _m("LINK", "MULDEF", "W", "symbol {symbol} is defined in both {module} and {other}",
       "Two object files both define the same [GLOBAL] name. The linker uses the first one and ignores the other.",
       "Rename one of them, or remove one object file from the LINK command."),
    _m("LINK", "NOMAIN", "E", "no main program: none of the object files is a PROGRAM",
       "An image needs exactly one PROGRAM to start from. MODULE files only contain parts for a program to use.",
       "Include the object file of the PROGRAM, for example LINK MAIN, MATHLIB."),
    _m("LINK", "MULTFR", "E", "more than one main program: {modules}",
       "An image can have only one starting point, but several of the object files are PROGRAMs.",
       "Link only one PROGRAM; turn the others into MODULEs or link them separately."),
    _m("LINK", "SYMKIND", "E", "{symbol} is a {defkind} in module {defmodule} but {module} uses it as a {usekind}",
       "The [EXTERNAL] declaration and the [GLOBAL] definition disagree about what the name is, "
       "for example a variable in one file and a procedure in the other.",
       "Make the [EXTERNAL] declaration describe the same kind of thing as the [GLOBAL] definition."),
    _m("LINK", "SIGNATURE", "E", "declaration of {symbol} in {module} does not match its definition in {defmodule}",
       "The [EXTERNAL] heading must have the same parameters and result type as the [GLOBAL] definition, "
       "otherwise the program would pass the wrong values.",
       "Copy the heading from the defining module so both match exactly.",
       "Make the heading in {module} match {defmodule}: {defsig} (found {usesig})."),
    _m("LINK", "OPENOUT", "F", 'error opening "{file}" as output',
       "The linker could not write the image (.EXE) or map (.MAP) file.",
       "Check that the directory is writable and the disk is not full."),
    # ------------------------------------------------------------------
    # PAS: the run-time system (errors while the program runs)
    # ------------------------------------------------------------------
    _m("PAS", "DIVBYZERO", "F", "division by zero",
       "The program tried to divide by zero (with /, DIV or MOD), which has no answer, so it was stopped.",
       "Check the divisor before dividing, e.g. IF count <> 0 THEN average := total DIV count."),
    _m("PAS", "INTOVF", "F", "integer overflow",
       "A calculation produced a whole number too big for an INTEGER (larger than 2147483647 "
       "or smaller than -2147483648).",
       "Use smaller numbers, or REAL variables for very large values."),
    _m("PAS", "FLTOVF", "F", "floating-point overflow",
       "A REAL calculation produced a number too large to represent.",
       "Check the calculation for runaway growth, such as multiplying in a loop that never stops."),
    _m("PAS", "ARRINDVAL", "F", "array index value {value} is out of range {low}..{high}",
       "The program used an array subscript outside the bounds given in the ARRAY declaration.",
       "Check the loop bounds and the index calculation; the index must stay between the array's bounds.",
       "The index must stay between {low} and {high}; check the loop bounds and the index calculation."),
    _m("PAS", "VALOUTRAN", "F", "value {value} is out of range {low}..{high}",
       "A value was stored in a variable whose type only allows a smaller range "
       "(for example a subrange like 1..100), or CHR/SUCC/PRED went past the end of their type.",
       "Check where the value comes from, or widen the range in the declaration.",
       "Keep the value between {low} and {high}, or widen the range in the declaration."),
    _m("PAS", "CASSELVAL", "F", "CASE selector value {value} does not match any CASE label",
       "A CASE statement was run with a value that none of its labels mention.",
       "Add a label for this value, or add an OTHERWISE part to handle all remaining values."),
    _m("PAS", "UNINITVAR", "F", "variable {name} used before it was given a value",
       "The program read a variable before anything was stored in it, so its value is undefined.",
       "Give the variable a starting value first, for example count := 0; before the loop.",
       "Give {name} a starting value first, for example {name} := 0; before it is used."),
    _m("PAS", "NOFUNCRES", "F", 'function "{name}" ended without assigning its result',
       "A function hands back its value by assigning to its own name. This call finished without doing that.",
       "Make sure every path through the function assigns to its name.",
       "Make sure every path through {name} executes an assignment like {name} := ..."),
    _m("PAS", "SQUROONEG", "F", "square root of a negative number ({value})",
       "SQRT is only defined for zero and positive numbers.",
       "Check the value before calling SQRT, or use ABS(x) if the sign does not matter."),
    _m("PAS", "LOGNONPOS", "F", "logarithm of zero or a negative number ({value})",
       "LN is only defined for numbers greater than zero.",
       "Check the value before calling LN."),
    _m("PAS", "INVSYNINT", "W", '"{text}" is not a valid INTEGER',
       "The program asked for a whole number, but what was typed is not one. "
       "Whole numbers are digits only, optionally with a sign, like 42 or -7.",
       "Type a whole number and press RETURN."),
    _m("PAS", "INVSYNREA", "W", '"{text}" is not a valid REAL number',
       "The program asked for a number, but what was typed is not one. Numbers look like 3, 3.5 or -0.25.",
       "Type a number and press RETURN."),
    _m("PAS", "PASTEOF", "F", "attempt to read past the end of the input",
       "The program wanted more input, but there is none left (the input was closed, or Ctrl-D/Ctrl-Z was pressed).",
       "Give the program all the input it asks for, or test EOF before reading."),
    _m("PAS", "NEGWIDDIG", "F", "negative field width or number of digits ({value})",
       'In WRITE(x:w) and WRITE(x:w:d), w and d must be zero or more.',
       "Use a field width of 0 or more."),
    _m("PAS", "RANDARG", "F", "RANDOM({value}): the argument must be at least 1",
       "RANDOM(n) picks a whole number from 0 to n-1, so n must be 1 or more.",
       "Pass a positive number, e.g. RANDOM(100) + 1 for a number from 1 to 100."),
    _m("PAS", "STKOVF", "F", "stack overflow: too many nested procedure calls",
       "Each call to a procedure or function uses memory until it returns. This usually means a "
       "recursive routine keeps calling itself and never reaches the case that stops it.",
       "Check that the recursive routine has a stopping case that is always reached."),
    _m("PAS", "STEPLIMIT", "F", "program stopped after {steps} instructions",
       "The program ran for longer than allowed, which usually means a loop that never ends "
       "(for example a WHILE whose condition never becomes FALSE).",
       "Check that something inside each loop changes the loop's condition."),
    _m("PAS", "CONTROLC", "F", "program interrupted by Ctrl-C",
       "You pressed Ctrl-C, which stops a running program immediately.",
       "Run the program again when you are ready; Ctrl-C is the way to stop a program that will not end."),
    _m("PAS", "NOIMAGE", "F", 'image file "{file}" not found',
       "RUN needs an executable image (.EXE), which LINK makes from compiled object files.",
       "Compile and link first: PASCAL name, then LINK name, then RUN name.",
       "Compile and link first: PASCAL {stem}, then LINK {stem}, then RUN {stem}."),
    _m("PAS", "BADIMAGE", "F", '"{file}" is not a valid image: {reason}',
       "The file does not have the layout of an image made by LINK.",
       "Link the program again to make a fresh .EXE file."),
    _m("PAS", "BUGCHECK", "F", "internal error in the p-code machine: {reason}",
       "Something went wrong inside the toolchain itself rather than in your program.",
       "Please report this, together with the program that caused it."),
    # ------------------------------------------------------------------
    # TRACE: the traceback that follows a fatal run-time error
    # ------------------------------------------------------------------
    _m("TRACE", "TRACEBACK", "F", "symbolic stack dump follows",
       "The lines below show where the program was when it stopped: the routine that failed is first, "
       "followed by the routines that called it, down to the main program.",
       "Look at the first line with a line number: that is where the error happened in your source."),
]

_BY_KEY: dict[tuple[str, str], MessageInfo] = {(m.facility, m.ident): m for m in _CATALOG}


def get_message(facility: str, ident: str) -> MessageInfo:
    try:
        return _BY_KEY[(facility.upper(), ident.upper())]
    except KeyError:
        raise KeyError(f"no message %{facility}-?-{ident}") from None


def all_messages() -> list[MessageInfo]:
    return list(_CATALOG)


def _fields(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def _fill(template: str, args: dict) -> str | None:
    if not _fields(template) <= args.keys():
        return None
    return template.format(**args)


def diag(facility: str, ident: str, *, file: str | None = None, line: int | None = None,
         column: int | None = None, end_column: int | None = None, **args) -> Diagnostic:
    """Build a Diagnostic for a catalog message, filling in its fields."""
    info = get_message(facility, ident)
    args = {k: v for k, v in args.items() if v is not None}
    text = _fill(info.template, args)
    if text is None:
        missing = _fields(info.template) - args.keys()
        raise KeyError(f"message {info.code} needs fields {sorted(missing)}")
    hint = info.hint
    if info.hint_detail:
        hint = _fill(info.hint_detail, args) or info.hint
    return Diagnostic(file=file, line=line, column=column, severity=info.severity,
                      facility=info.facility, ident=info.ident, text=text,
                      explanation=info.explanation, hint=hint, end_column=end_column)


def worst_severity(diags) -> str | None:
    order = {s: i for i, s in enumerate(SEVERITIES)}
    worst = None
    for d in diags:
        if worst is None or order[d.severity] > order[worst]:
            worst = d.severity
    return worst


def has_errors(diags) -> bool:
    return any(d.severity in ("E", "F") for d in diags)

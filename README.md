# vms-lse-pascal

A terminal editor in the style of the VAX/VMS Language-Sensitive Editor (LSE), with Pascal templates and placeholders, a COMPILE / LINK / RUN toolchain, and a guided "Guess My Number" tutorial for people new to Pascal.

Status: the Pascal toolchain is working; the editor is in progress. See [PLAN.md](PLAN.md) for the design and build order.

## Install

Python 3.11 or newer is needed. From a checkout:

```
pipx install .          # or: uv tool install .   or: pip install -e .
```

This installs the commands `pascal`, `link` and `run` (plus `paslink` and `pasrun`, in case `link` clashes with the Unix command of the same name). Without installing, use `python -m pascal PASCAL|LINK|RUN ...` from the repository root.

## The Pascal toolchain

```
$ cd examples
$ pascal HELLO              compile HELLO.PAS  -> HELLO.OBJ, HELLO.DIA
$ link HELLO                link with PASRTL   -> HELLO.EXE, HELLO.MAP
$ run HELLO
Hello, world!
```

- `pascal /LIST HELLO` also writes a listing, `HELLO.LIS`.
- `link MATHDEMO, MATHLIB` links a program with a separately compiled `MODULE`.
- `run /SEED=42 GUESS` makes `RANDOMIZE` and `RANDOM(n)` repeatable; `run /INPUT=answers.txt GUESS` reads input from a file.
- `/NOEXPLAIN` turns off the explanation and hint printed under each message.

Qualifiers can be written VMS style (`/LIST`, `/SEED=42`, or glued on as `HELLO/LIST`) or Unix style (`--list`, `--seed 42`).

Every message from the compiler, linker and run-time system comes with a plain-English explanation and a hint:

```
    12      tries := tries + 1;
            ^
%PASCAL-E-SEMIEXP, ";" expected at line 12, column 5
  Explanation: Pascal statements and declarations are separated by semicolons. The compiler found
               the start of something new before the previous one was ended with ";".
  Hint: Add ";" at the end of line 11, after ")".
```

A fatal run-time error stops the program with a traceback naming each active routine and its source line:

```
%PAS-F-DIVBYZERO, division by zero at line 10
  Explanation: The program tried to divide by zero (with /, DIV or MOD), ...
  Hint: Check the divisor before dividing, e.g. IF count <> 0 THEN average := total DIV count.
%TRACE-F-TRACEBACK, symbolic stack dump follows
module name     routine name                     line       rel PC    abs PC
AVERAGE         MEAN                               10      00000003  00000003
AVERAGE         REPORT                             15      0000000F  0000000F
AVERAGE         AVERAGE                            37      00000038  00000038
```

### Language

A teaching-sized Pascal: `PROGRAM` and `MODULE`; `CONST`, `TYPE`, `VAR`; `INTEGER`, `REAL`, `BOOLEAN`, `CHAR`, subranges, enumerations, `ARRAY` (including `PACKED ARRAY [1..n] OF CHAR` strings) and `RECORD`; procedures and functions with value and `VAR` parameters, nesting, recursion and `FORWARD`; `IF`, `CASE` (with ranges and `OTHERWISE`), `WHILE`, `REPEAT`, `FOR ... TO/DOWNTO`; `WRITE`/`WRITELN` with field widths, `READ`/`READLN`, `EOF`, `EOLN`; `ABS SQR ODD ORD CHR SUCC PRED TRUNC ROUND SQRT SIN COS ARCTAN EXP LN`, `RANDOMIZE`, `RANDOM(n)`, `HALT`; and VAX-style `[GLOBAL]` / `[EXTERNAL]` for separate compilation. Pointers, sets, files other than `INPUT`/`OUTPUT`, `WITH` and `GOTO` are left out.

### Examples

| File | Shows |
| --- | --- |
| `HELLO.PAS` | the smallest program |
| `GUESS.PAS` | the tutorial's finished game: `RANDOM`, `REPEAT`, `IF` |
| `FACTORIAL.PAS` | a recursive function |
| `PRIMES.PAS` | arrays, `VAR` parameters, a nested procedure |
| `MATHLIB.PAS` + `MATHDEMO.PAS` | a `MODULE` linked with a program |
| `AVERAGE.PAS` | a run-time error and its traceback (enter 0) |

### How it works

All files the toolchain writes are plain text, so you can open them and see what each step did.

- `pascal/lexer.py`, `parser.py`, `semantic.py`: source to a checked syntax tree.
- `pascal/codegen.py`: the tree to p-code for a stack machine (`pascal/pcode.py` lists every instruction).
- `.OBJ`: the module's p-code, a `GLOBALS` table (names it exports), an `EXTERNALS` table (names it needs, with the instructions that use them), and line-number records.
- `pascal/linker.py`: joins object modules, takes `PAS$...` routines from the run-time library `pascal/PASRTL.OLB`, and writes the `.EXE` image and a `.MAP` listing every symbol, its module and address.
- `pascal/vm.py` and `pascal/rtl.py`: the p-code machine and the run-time library.
- `pascal/messages.py`: every message with its explanation and hint.
- `pascal/api.py`: the interface the editor uses.

## Tests

```
pip install pytest
pytest
```

# vms-lse-pascal

A terminal editor in the style of the VAX/VMS Language-Sensitive Editor (LSE), with Pascal templates and placeholders, a COMPILE / LINK / RUN toolchain, and a guided "Guess My Number" tutorial for people new to Pascal.

See [PLAN.md](PLAN.md) for the design.

## Install

Python 3.11 or newer is needed. From a checkout:

```
pipx install .          # or: uv tool install .   or: pip install -e .
```

This installs `lse` (the editor) and the toolchain commands `pascal`, `link` and `run` (plus `paslink` and `pasrun`, in case `link` clashes with the Unix command of the same name). Without installing, use `python -m lse` and `python -m pascal PASCAL|LINK|RUN ...` from the repository root. On Windows, `windows-curses` is installed automatically.

## Using LSE

### Starting

```
lse                  the Guess My Number tutorial (picks up where you left off)
lse GUESS.PAS        edit a file; a new .PAS file starts as a template
lse --tutorial       the tutorial, even if you finished it before
lse --no-tutorial    the welcome screen: tutorial, new file, open file, quit
lse --keytest        see which keys your terminal lets through
lse --theme AMBER    amber (or GREEN) phosphor instead of VT220 white
lse --seed 7         make RANDOM repeatable in every RUN
```

Run `lse` in the folder where you want your program to live: the tutorial writes `GUESS.PAS` there. Once the tutorial is finished, `lse` with no file name shows a welcome screen instead. `~/.lse/state` remembers that (set `LSE_STATE_DIR` to keep it somewhere else).

### The screen

```
PROGRAM Guess(INPUT, OUTPUT);                          your program
...
[ GUESS.PAS;4 ]--[ EDIT > COMPILE > LINK > RUN ]--[ Pascal | Insert | 12/20 ]
┌[ Lesson 7 of 10: Decide: too low, too high or correct? ]────────────────┐
│ DO THIS:  [x] 1. At the end of the READLN(guess) line type ; ...        │
│           ==> 2. Type guess < secret, Tab, WRITELN, Tab, 'Too low!' ... │
│ YOU WILL SEE: Your guess? 50  Too high!  ... until Correct!             │
└─────────────────────────────────────────────────────────────────────────┘
NEXT: Type guess < secret, Tab, WRITELN, Tab, then 'Too low!' and Tab
%LSE-S-STEPDONE, step 6 done. Now step 7 of 10: Decide: ...
F1 Help  F2 Check  F4 Hint  F5 Run  F7 Compile  F8 Errors  ^L Lesson  ^Q Quit
```

- **Status line:** the file and its version, then where you are in the build cycle. A stage marked `*` is out of date (you changed the program since), and one marked `!` failed. The current stage is underlined.
- **NEXT line:** always says what to do next and which key does it, whether or not the tutorial is running.
- **Message line:** VMS-style messages (`%PASCAL-E-SEMIEXP, ...`) with a plain-English explanation and a hint. `SET MESSAGES /NOEXPLAIN` leaves the explanations out.
- **Key bar:** the keys that make sense right now. Inside a menu it shows the menu keys, and inside REVIEW the error keys. The way out (`^Q Quit` or `Esc`) is always on it.
- `LSE>` appears in the key bar's place when you type a command (Ctrl-P or F10).

### Keys

| Key | Does |
| --- | --- |
| Tab | expand the placeholder or template word at the cursor (or open its menu); otherwise go to the next placeholder |
| Shift-Tab, Ctrl-N | previous / next placeholder without expanding |
| Ctrl-K, Ctrl-Delete | erase a placeholder (an optional one takes its `;` or `,` with it) |
| F1 | explain the placeholder or word at the cursor; elsewhere, WHAT NOW and the keypad |
| F2 / F4 | tutorial: check the step / a hint (press again for more, then "show me") |
| F5 | compile, link and run |
| F7 | compile |
| F8, Shift-F8 | next / previous compiler message, in the source |
| F10, Ctrl-P | the `LSE>` command line (Tab completes commands and file names) |
| Ctrl-S | save as a new version (`GUESS.PAS;1`, `;2`, ...) |
| Ctrl-O | open a file; Enter alone goes back to the previous one |
| Ctrl-Q | quit (asks first if something is not saved) |
| Ctrl-Z, Ctrl-Y | undo, redo |
| Ctrl-F, F3 | find, find next |
| Ctrl-G | go to a line |
| Ctrl-W, Ctrl-B | other window, buffer list |
| Ctrl-L | hide or show the lesson |

If your terminal keeps a key for itself (GNOME Terminal takes F1 and F10, xfce4-terminal takes F1), press **Esc and then the digit** instead: Esc 5 = F5, Esc 0 = F10. Every key is also an `LSE>` command (`HELP KEYS` lists them), and `lse --keytest` shows which keys get through. Ctrl-S and Ctrl-Q work because LSE puts the terminal in raw mode.

### Templates and placeholders

Placeholders are the blanks in a template: `%{name}%` must be filled in, `%[name]%` is optional, and `...` after one means it can repeat. In a new file, Tab on `%{compilation_unit}%` and Enter gives the outline of a program. Type a word such as `IF`, `WHILE`, `REPEAT` or `WRITELN` and press Tab to get its template, then Tab from blank to blank. The message line explains the placeholder under the cursor, and F1 shows its full description with an example. `SHOW TOKENS` and `SHOW PLACEHOLDERS` list them all; the definitions are in `lse/languages/pascal.lse`.

### Compile, link and run

- **F7 (COMPILE)** saves the file and compiles it. Any messages go in REVIEW: F8 jumps to each one in the source, and the `REVIEW` command lists them in a window (Enter goes to one, Esc closes it). A placeholder left in the program is reported as `%PASCAL-E-PLACEHOLDER`, so F8 takes you to it too.
- **F5 (BUILD)** compiles, links and runs. The screen is handed to your program, between two banners: "Running GUESS.EXE. Type your answers and press RETURN. Ctrl-C stops the program." and "Program finished. Press RETURN to go back to LSE." If you type letters where it wants a number, the program explains and asks again. What it printed is kept in the buffer `$OUTPUT` (Ctrl-B). If the program stops with an error, F8 goes to the line.
- `LINK` writes `GUESS.MAP`, which lists every routine in the program and where it came from. Ctrl-O `GUESS.MAP` opens it read-only.
- `RUN /SEED=7 /INPUT="50\n25"` runs without the terminal, with fixed random numbers and given input.

### Help

- `HELP PASCAL` opens the Pascal help library, with topics on PROGRAM, VAR, TYPES, WRITELN, READLN, IF, LOOPS, PROCEDURES, COMPILE-LINK-RUN and more. Each topic has examples. Up/Down picks a subtopic, Enter opens it and Backspace goes back. Words can be abbreviated, VMS style: `HELP PAS LOOP WHILE`. `HELP PASCAL MESSAGES` explains every compiler, linker and run-time message.
- `WHAT NOW` (or F1 on nothing in particular) describes where you are, for example "It compiled, but it hasn't been linked since your last change", and says what to press.
- `HELP KEYS`, `HELP COMMANDS` and `HELP KEYPAD` (the VT220 keypad, labeled with today's keys).

### The tutorial

The tutorial builds `GUESS.PAS` in ten steps: an empty program, `WRITELN`, a mistake made on purpose (and F8), variables, `RANDOM` and the link map, a `REPEAT` loop with `READLN`, `IF ... ELSE IF ... ELSE`, counting tries, playing, and some challenges. Each step says exactly what to press (DO THIS) and what you will see, and ticks the actions off as you do them. It moves on by itself when the step is done.

- **F2** checks the step and says what is missing. **F4** gives a hint; press it again for the exact keys, and a third time to see the step's finished program and put it in (Ctrl-Z takes it back out).
- If something an earlier step built goes missing, the NEXT line says so. Ctrl-Z undoes the change, or F4 puts it back.
- **Ctrl-L** hides or shows the lesson. While it is hidden, the status line says `Lesson 7/10 ^L`.
- `TUTORIAL` starts or resumes the tutorial, and `TUTORIAL OFF` stops it so you can just edit. `TUTORIAL RESTART` starts over with an empty `GUESS.PAS` (the old one stays as a version), and `TUTORIAL STEP [n]` jumps to a step.
- Progress is saved in `GUESS.TUT`, next to `GUESS.PAS`.

Lessons are plain text files (`lse/lessons/*.lesson`); the format is described at the top of `lse/lesson.py`.

### Other commands

`SET THEME VT220|AMBER|GREEN`, `SET LINE_DRAWING ACS|UNICODE|ASCII` (use ASCII if boxes look like `lqqk`), `SET MESSAGES /[NO]EXPLAIN`, `TWO WINDOWS`, `ONE WINDOW`, `GOTO LINE n`, `PURGE /KEEP=n` (delete old versions), `EXIT` (save everything and quit). `HELP COMMANDS` lists them all.

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

## How the editor is built

- `lse/editor.py`: the editor core (buffers, windows, keys, messages), with no curses. `lse/screen.py` draws it with curses, and `lse/testing.py` drives it headlessly for tests.
- `lse/actions.py` and `lse/commands.py`: every command, and the `LSE>` parser with VMS-style abbreviations.
- `lse/placeholders.py`, `lse/langdef.py`, `lse/languages/pascal.lse`: the template engine and the Pascal templates.
- `lse/guidance.py`: the NEXT line, the build-cycle indicator, the key bar and WHAT NOW. `next_action(state)` is a pure function of the editor state.
- `lse/tutor.py`, `lse/lesson.py`, `lse/lessons/guess.lesson`: the tutorial.
- `lse/helplib.py`, `lse/help/pascal.hlp`: the help library, in the VMS help-file layout.
- `lse/toolchain.py`: the only place the editor talks to the toolchain (`pascal/api.py`).

## Tests

```
pip install pytest
pytest
```

The editor tests drive the real key handling through `lse.testing.EditorHarness`. They include:

- a play-through of every tutorial step, both by keystrokes and with "show me";
- a newcomer walkthrough with wrong turns, which checks the NEXT line after every key;
- a check that `next_action` gives an actionable answer for every reachable state;
- end-to-end runs of `lse` in a pseudo-terminal.

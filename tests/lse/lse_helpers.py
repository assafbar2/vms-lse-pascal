"""Shared helpers for the editor tests (importable in any pytest import mode)."""

HELLO = """PROGRAM Hello(INPUT, OUTPUT);
BEGIN
  WRITELN('Hello, world')
END.
"""


GUESS_SEED = 7     # with this seed the secret number is 32
CTRL_C = "\x03"    # a line of RUN input that stands for pressing Ctrl-C

# What a newcomer types in each tutorial step, following the lesson's DO THIS
# lines exactly (with --seed 7), and what they type into the running program.
TUTORIAL_KEYS = [
    ("welcome", "<Tab><Enter>Guess<Tab><C-k><Tab><C-k><F5>", ""),
    ("say", "<Up><End><Enter>WRITELN<Tab>'I am thinking of a number from 1 to 100.'<F5>", ""),
    ("mistake", "<C-Home><End><Backspace><F7><F8><Up><End>;<F7>", ""),
    ("variables", "<C-Home><End><Enter>VAR<Tab>secret, guess, tries<Tab><Tab><Enter>"
                  "<Tab><C-k><F7>", ""),
    ("secret", "<End><Enter>RANDOMIZE;<Enter>secret := RANDOM(100) + 1;<F5>"
               "<C-o>GUESS.MAP<Enter><C-o><Enter>", ""),
    ("ask", "<Down><End>;<Enter>REPEAT<Tab>WRITE<Tab>'Your guess? '<Tab>READLN<Tab>guess<Tab>"
            "<C-k><Tab>guess = secret<F5>", f"50\nabc\n{CTRL_C}\n"),
    ("decide", "<Up><End>;<Enter>IF<Tab>guess < secret<Tab>WRITELN<Tab>'Too low!'<Tab>"
               "<Tab><Down><Enter>guess > secret<Tab>WRITELN<Tab>'Too high!'<Tab>"
               "<Tab><Enter>WRITELN<Tab>'Correct!'<F5>", "50\n25\n32\n"),
    ("count", "<C-Home>" + "<Down>" * 5 + "<End><Enter>tries := 0;" + "<Down>" * 4
              + "<End><Enter>tries := tries + 1;<C-f>Correct!<Enter>" + "<Right>" * 8
              + " You got it in ', tries:1, ' tries.<F7>", ""),
    ("play", "<F5>", "50\n25\n37\n31\n34\n32\n"),
]


def follow_tutorial(h, upto=None):
    """Play the tutorial in ``h`` by keystrokes up to (not including) step ``upto``."""
    for step_id, keys, typed in TUTORIAL_KEYS:
        if step_id == upto:
            return h
        h.host.program_input = typed
        h.feed(keys)
    return h


def new_program(h, name="Hello"):
    """Open NEW.PAS and expand PROGRAM with a name; cursor on %[declarations]%..."""
    h.open("NEW.PAS")
    h.feed(f"<Tab><Enter>{name}<Tab>")
    return h

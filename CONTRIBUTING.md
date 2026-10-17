# Contributing

You need Python 3.11 or newer. Node 22 is only needed for the browser build.

```sh
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[test]"
```

## Running the tests

```sh
pytest                                   # everything: about 620 tests, about a minute
pytest tests/pascal                      # toolchain only
pytest tests/lse -k novice               # by name
pytest tests/lse/test_app_pty.py         # the real lse in a pseudo-terminal (skipped on Windows)
```

The browser tests build the site, serve it on port 8123 and play the tutorial:

```sh
cd web
npm ci
python3 build.py
npx playwright install chromium          # once
npx playwright test --project=chromium   # or firefox, webkit; no flag runs all three
LSE_WEB_URL=https://assafbar2.github.io/vms-lse-pascal/ npx playwright test --project=chromium
```

The last line runs the same suite against the deployed site.

CI runs `pytest` on Ubuntu, macOS and Windows with Python 3.11 and 3.12 (`.github/workflows/tests.yml`). It also builds the site and runs Playwright in all three engines (`.github/workflows/pages.yml`). Keep both green.

## Things the tests enforce

- Every compiler, linker and run-time message in `pascal/messages.py` needs an explanation and a hint.
- `pascal/PASRTL.OLB` is generated. After changing `pascal/rtl.py`, run `python -m pascal.rtl` and commit the new library.
- No edit of an example program may crash the compiler; the editor parses after every keystroke.
- Each lesson step must fit an 80x24 terminal without scrolling.
- The NEXT line must name an action for every reachable editor state.
- `TUTORIAL_KEYS` in `tests/lse/lse_helpers.py` is what a newcomer types in each tutorial step. pytest and Playwright both replay it, so update it when a lesson changes.

New editor behaviour should come with a test that drives `lse.testing.EditorHarness` with keys and checks the screen by region (`h.screen.region("message")`) rather than by row number. `EditorHarness(app=True)` adds the guidance and tutor layers, as `lse` does; `api=pascal.api` swaps the fake toolchain for the real one.

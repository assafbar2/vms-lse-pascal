// Plays the Guess My Number tutorial in a real browser, with real key events.
//
// The keystrokes come from tests/lse/lse_helpers.py (TUTORIAL_KEYS), the same
// script the Python tests use, so this follows any change to the lesson.

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { openLse as open, screen, waitForScreen } from "./lse-page.mjs";

const ROOT = fileURLToPath(new URL("../..", import.meta.url));
const PYTHON = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");

const script = JSON.parse(
  execFileSync(
    PYTHON,
    [
      "-c",
      "import json, sys; sys.path.insert(0, 'tests/lse'); import lse_helpers as h; " +
        "print(json.dumps({'seed': h.GUESS_SEED, 'ctrl_c': h.CTRL_C, 'steps': h.TUTORIAL_KEYS}))",
    ],
    { cwd: ROOT, encoding: "utf-8" },
  ),
);

const KEY_NAMES = {
  Tab: "Tab", Enter: "Enter", Up: "ArrowUp", Down: "ArrowDown", Left: "ArrowLeft",
  Right: "ArrowRight", Home: "Home", End: "End", Backspace: "Backspace", Delete: "Delete",
  PageUp: "PageUp", PageDown: "PageDown", Esc: "Escape", "S-Tab": "Shift+Tab",
};

function playwrightKey(name) {
  if (KEY_NAMES[name]) return KEY_NAMES[name];
  if (/^F\d+$/.test(name)) return name;
  if (/^S-F\d+$/.test(name)) return `Shift+${name.slice(2)}`;
  const ctrl = /^C-(.+)$/.exec(name);
  if (ctrl) return `Control+${KEY_NAMES[ctrl[1]] || ctrl[1]}`;
  throw new Error(`no Playwright key for <${name}>`);
}

// "<Tab>Guess<F5>" -> [{key: "Tab"}, {text: "Guess"}, {key: "F5"}]
function tokens(spec) {
  const out = [];
  const re = /<([A-Za-z0-9^][A-Za-z0-9_+\-^]*)>|([^<]+|<)/g;
  for (const m of spec.matchAll(re)) {
    if (m[1]) out.push({ key: m[1] });
    else out.push({ text: m[2] });
  }
  return out;
}

const openLse = (page, query = `?seed=${script.seed}&size=80x24`) => open(page, query);

// Press F5, play the program with ``typed`` (lines; Ctrl-C as script.ctrl_c), go back.
async function runProgram(page, typed, onScreen) {
  const lines = typed.split("\n").filter((l, i, all) => l !== "" || i < all.length - 1);
  const reads = await page.evaluate(() => window.lse.state.reads);
  await page.keyboard.press("F5");
  await expect.poll(() => page.evaluate(() => window.lse.state.mode)).toBe("run");
  let seen = reads;
  for (const line of lines) {
    await expect.poll(() => page.evaluate(() => window.lse.state.reads)).toBeGreaterThan(seen);
    seen = await page.evaluate(() => window.lse.state.reads);
    if (line.startsWith(script.ctrl_c)) {
      await page.keyboard.press("Control+c");
      break;
    }
    await page.keyboard.type(line);
    await page.keyboard.press("Enter");
  }
  await waitForScreen(page, "Press RETURN to go back to LSE.");
  if (onScreen) await onScreen(await screen(page));
  await page.keyboard.press("Enter");
  await expect.poll(() => page.evaluate(() => window.lse.state.mode)).toBe("edit");
}

async function playStep(page, keys, typed, onScreen) {
  for (const t of tokens(keys)) {
    if (t.text) await page.keyboard.type(t.text);
    else if (t.key === "F5") await runProgram(page, typed, onScreen);
    else await page.keyboard.press(playwrightKey(t.key));
  }
}

test("opens straight into the tutorial and plays it through to the game", async ({ page }) => {
  await openLse(page);
  const first = await screen(page);
  expect(first).toContain("Lesson 1 of 10");
  expect(first).toContain("GUESS.PAS");
  expect(await page.evaluate(() => [window.lse.term.cols, window.lse.term.rows])).toEqual([80, 24]);
  expect(await page.evaluate(() => window.lse.state.blocking)).toBe(true);

  const total = script.steps.length;
  for (const [index, [stepId, keys, typed]] of script.steps.entries()) {
    let ran = "";
    await playStep(page, keys, typed, (text) => {
      ran = text;
    });
    if (stepId === "ask") expect(ran).toContain("Program stopped");
    if (stepId === "play") expect(ran).toContain("Correct! You got it in 6 tries.");
    if (index + 1 < total) {
      await waitForScreen(page, `Lesson ${index + 2} of`);
    }
  }
  await waitForScreen(page, "You finished!");
});

test("keeps tutorial progress across a reload; Esc then 5 works as F5", async ({ page }) => {
  await openLse(page);
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await page.keyboard.type("Guess");
  for (const k of ["Tab", "Control+k", "Tab", "Control+k"]) await page.keyboard.press(k);
  await page.keyboard.press("Escape");
  await page.keyboard.press("5");
  await expect.poll(() => page.evaluate(() => window.lse.state.mode)).toBe("run");
  await waitForScreen(page, "Press RETURN to go back to LSE.");
  await page.keyboard.press("Enter");
  await waitForScreen(page, "Lesson 2 of");
  await page.waitForTimeout(1500);

  await page.reload();
  await openLse(page, `?seed=${script.seed}`);
  await waitForScreen(page, "Lesson 2 of");
  expect(await screen(page)).toContain("PROGRAM Guess(INPUT, OUTPUT);");
});

test("fits at least 80x24 in a small window and grows in a large one", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 560 });
  await openLse(page, "?size=fit");
  const small = await page.evaluate(() => [window.lse.term.cols, window.lse.term.rows]);
  expect(small[0]).toBeGreaterThanOrEqual(80);
  expect(small[1]).toBeGreaterThanOrEqual(24);

  await page.setViewportSize({ width: 1800, height: 1100 });
  await expect.poll(() => page.evaluate(() => window.lse.term.rows)).toBeGreaterThan(24);
  const large = await page.evaluate(() => [window.lse.term.cols, window.lse.term.rows]);
  expect(large[0]).toBeGreaterThan(80);
  await waitForScreen(page, "Lesson 1 of");
  await expect.poll(async () => (await screen(page)).split("\n")[large[1] - 1]).toContain("Quit");
});

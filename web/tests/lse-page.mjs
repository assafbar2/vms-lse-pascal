// Driving the LSE page from Playwright tests.

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect } from "@playwright/test";

// The first visit reloads once (to start the service worker), so a read can
// land between two pages; treat that as "not yet".
export async function read(page, fn, fallback = null) {
  try {
    return await page.evaluate(fn);
  } catch {
    return fallback;
  }
}

export const screen = (page) => read(page, () => window.lse?.text() ?? "", "");

export async function openLse(page, query) {
  await page.goto(query);
  await expect.poll(() => read(page, () => !!window.lse?.state.ready, false), { timeout: 90_000 })
    .toBe(true);
  await page.locator(".xterm-helper-textarea").focus();
}

export async function waitForScreen(page, text, timeout = 30_000) {
  await expect.poll(() => screen(page), { timeout, message: `screen shows ${JSON.stringify(text)}` })
    .toContain(text);
}

const ROOT = fileURLToPath(new URL("../..", import.meta.url));
const PYTHON = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");

// The tutorial's keystrokes: tests/lse/lse_helpers.py (TUTORIAL_KEYS), as the Python tests use.
export const script = JSON.parse(
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

// Type one step's keys; F5 runs the program with ``typed`` as its input.
export async function playStep(page, keys, typed, onScreen) {
  for (const t of tokens(keys)) {
    if (t.text) await page.keyboard.type(t.text);
    else if (t.key === "F5") await runProgram(page, typed, onScreen);
    else await page.keyboard.press(playwrightKey(t.key));
  }
}

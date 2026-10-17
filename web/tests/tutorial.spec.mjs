// Plays the Guess My Number tutorial in a real browser, with real key events.
//
// The keystrokes come from tests/lse/lse_helpers.py (TUTORIAL_KEYS), the same
// script the Python tests use, so this follows any change to the lesson.

import { expect, test } from "@playwright/test";
import { openLse as open, playStep, screen, script, waitForScreen } from "./lse-page.mjs";

const openLse = (page, query = `?seed=${script.seed}&size=80x24`) => open(page, query);

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

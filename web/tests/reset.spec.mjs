// "Start over" erases the saved files and tutorial progress and comes back at
// lesson 1, ready to use, also while LSE is open in another tab. Both it and
// a plain reload reload the page, which revalidates the cached files.

import { expect, test } from "@playwright/test";
import { openLse, playStep, read, screen, script, waitForScreen } from "./lse-page.mjs";

const START = `?seed=${script.seed}&size=80x24`;
const [, firstKeys, firstTyped] = script.steps[0];

// Mark the page, so a later check can tell the page from the one a reload brings.
const markPage = (page) => page.evaluate(() => { window.oldPage = true; });
const reloadedAndReady = (page) =>
  read(page, () => !window.oldPage && Boolean(window.lse?.state.ready), false);

test("Start over after saved progress goes back to lesson 1, in every open tab", async ({ page, context }) => {
  await openLse(page, START);
  await waitForScreen(page, "Lesson 1 of 10");
  await playStep(page, firstKeys, firstTyped);
  await waitForScreen(page, "Lesson 2 of 10");

  // A second tab reads the saved progress (and keeps the files open).
  const other = await context.newPage();
  await expect.poll(async () => {
    await openLse(other, START);
    return screen(other);
  }, { timeout: 60_000, message: "the progress is saved" }).toContain("Lesson 2 of 10");
  await markPage(other);

  await page.bringToFront();
  await markPage(page);
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#reset-btn").click();
  await expect.poll(() => reloadedAndReady(page), { timeout: 90_000, message: "LSE starts again" })
    .toBe(true);
  await waitForScreen(page, "Lesson 1 of 10");
  // GUESS.PAS is the empty template again
  expect((await screen(page)).split("\n")[0].trim()).toBe("%{compilation_unit}%");

  // The other tab started over too, instead of keeping (and saving back) the old files.
  await expect.poll(() => reloadedAndReady(other), { timeout: 90_000 }).toBe(true);
  await waitForScreen(other, "Lesson 1 of 10");
  expect((await screen(other)).split("\n")[0].trim()).toBe("%{compilation_unit}%");
  await other.close();

  // ... and LSE works: lesson 1 again, running the program, on to lesson 2.
  await page.locator(".xterm-helper-textarea").focus();
  await playStep(page, firstKeys, firstTyped);
  await waitForScreen(page, "Lesson 2 of 10");
});

test("Start over waits for a tab that keeps the files open, and says so", async ({ page, context }) => {
  await openLse(page, START);
  await playStep(page, firstKeys, firstTyped);
  await waitForScreen(page, "Lesson 2 of 10");
  // like a tab with an older version of this page, which does not let go of the files
  const holder = await context.newPage();
  await holder.goto("sw.js");
  await holder.evaluate(() => new Promise((resolve, reject) => {
    const req = indexedDB.open("/home/lse");
    req.onsuccess = () => {
      window.files = req.result;
      resolve();
    };
    req.onerror = () => reject(req.error);
  }));

  await page.bringToFront();
  await markPage(page);
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#reset-btn").click();
  await expect(page.locator("#status")).toContainText("close LSE in your other tabs", { timeout: 15_000 });
  await waitForScreen(page, "Close it to start over");
  await holder.close();
  await expect.poll(() => reloadedAndReady(page), { timeout: 90_000, message: "LSE starts again" })
    .toBe(true);
  await waitForScreen(page, "Lesson 1 of 10");
});

test("LSE starts again after each reload", async ({ page }) => {
  await openLse(page, START);
  for (let i = 0; i < 3; i += 1) {
    await markPage(page);
    await page.evaluate(() => setTimeout(() => location.reload(), 0));
    await expect.poll(() => reloadedAndReady(page), { timeout: 60_000, message: `reload ${i + 1}` })
      .toBe(true);
  }
  await waitForScreen(page, "Lesson 1 of 10");
});

test("Cancel on the Start over question keeps everything", async ({ page }) => {
  await openLse(page, START);
  await playStep(page, firstKeys, firstTyped);
  await waitForScreen(page, "Lesson 2 of 10");
  await markPage(page);
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.locator("#reset-btn").click();
  await page.waitForTimeout(500);
  expect(await page.evaluate(() => window.oldPage)).toBe(true);
  await page.keyboard.press("F4");
  await waitForScreen(page, "Hint 1 of");
  expect(await screen(page)).toContain("Lesson 2 of 10");
});

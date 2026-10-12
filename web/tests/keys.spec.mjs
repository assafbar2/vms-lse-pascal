// The key bar can be clicked, and the keys a Mac keyboard sends reach LSE.
//
// macOS keyboards are not available here, so the Mac tests report the platform
// as a Mac and send the key events Chrome and Safari on macOS produce (with
// their KeyboardEvent.keyCode), including the composition an Option-N accent
// starts.

import { expect, test } from "@playwright/test";
import { openLse, screen, waitForScreen } from "./lse-page.mjs";

const START = "?seed=7&size=80x24";

async function barItem(page, key) {
  return page.evaluate((key) => {
    const item = window.lse.barItems().find((it) => it.key === key);
    if (!item) return null;
    const r = document.querySelector(".xterm-screen").getBoundingClientRect();
    const { cols, rows } = window.lse.term;
    const middle = (item.start + item.end) / 2;
    return { x: r.left + (middle / cols) * r.width, y: r.top + ((rows - 0.5) / rows) * r.height };
  }, key);
}

async function clickBar(page, key) {
  await expect.poll(() => barItem(page, key), { message: `key bar shows ${key}` }).not.toBeNull();
  const at = await barItem(page, key);
  await page.mouse.click(at.x, at.y);
}

// The text shown (the page has Mac and non-Mac versions of it).
const shown = (page, selector) => page.locator(selector).innerText();

// Since ``mark``: what the page sent LSE.
const sentSince = (page, mark) => page.evaluate((mark) => window.lse.sent.slice(mark), mark);
const sentCount = (page) => page.evaluate(() => window.lse.sent.length);

test("clicking a key in the key bar presses it", async ({ page }) => {
  await openLse(page, START);
  await waitForScreen(page, "Lesson 1 of 10");
  expect(await shown(page, "#keys-btn")).toBe("Browser keys");
  expect(await shown(page, "#tips")).toContain("Alt-Q");
  expect(await shown(page, "#tips")).not.toContain("fn");

  const f4 = await barItem(page, "F4");
  await page.mouse.move(f4.x, f4.y);
  await expect(page.locator(".key-hover")).toBeVisible();
  await page.mouse.click(f4.x, f4.y);
  await waitForScreen(page, "Hint 1 of 3");
  expect(await page.evaluate(() => document.activeElement?.className)).toContain("xterm-helper-textarea");
  // the click did not select text
  expect(await page.evaluate(() => window.lse.term.hasSelection())).toBe(false);

  // a menu's "Esc Cancel" closes it at once, without LSE waiting for a digit
  await page.keyboard.press("Tab");
  await expect.poll(() => barItem(page, "Esc")).not.toBeNull();
  const opened = await screen(page);
  const started = Date.now();
  await clickBar(page, "Esc");
  await expect.poll(() => barItem(page, "F4")).not.toBeNull();
  expect(Date.now() - started).toBeLessThan(900);
  expect(await screen(page)).not.toEqual(opened);

  await clickBar(page, "^L");
  await waitForScreen(page, "lesson hidden");
  await page.mouse.move(5, 5);
  await expect(page.locator(".key-hover")).toBeHidden();
});

test("tapping a key in the key bar presses it", async ({ browser, browserName }) => {
  test.skip(browserName === "firefox", "Playwright has no touch emulation for Firefox");
  const context = await browser.newContext({ hasTouch: true, viewport: { width: 1024, height: 700 } });
  const page = await context.newPage();
  await openLse(page, START);
  await waitForScreen(page, "Lesson 1 of 10");
  await expect.poll(() => barItem(page, "F4")).not.toBeNull();
  const f4 = await barItem(page, "F4");
  await page.touchscreen.tap(f4.x, f4.y);
  await waitForScreen(page, "Hint 1 of 3");
  await context.close();
});

test.describe("on a Mac", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, "platform", { get: () => "MacIntel" });
      if ("userAgentData" in Navigator.prototype) {
        Object.defineProperty(Navigator.prototype, "userAgentData", {
          get: () => ({ platform: "macOS", mobile: false, brands: [] }),
        });
      }
    });
  });

  // A keydown (and keyup) as macOS Chrome and Safari report it.
  async function macKey(page, init, keyCode) {
    await page.evaluate(([init, keyCode]) => {
      const ta = document.querySelector(".xterm-helper-textarea");
      for (const type of ["keydown", "keyup"]) {
        const ev = new KeyboardEvent(type, { bubbles: true, cancelable: true, composed: true, ...init });
        Object.defineProperty(ev, "keyCode", { get: () => keyCode });
        Object.defineProperty(ev, "which", { get: () => keyCode });
        ta.dispatchEvent(ev);
      }
    }, [init, keyCode]);
  }

  test("Mac labels; Ctrl from a Hebrew input source or an input method; Option keys", async ({ page }) => {
    await openLse(page, START);
    await waitForScreen(page, "Lesson 1 of 10");
    expect(await shown(page, "#keys-btn")).toBe("Mac keys");
    expect(await shown(page, "#tips")).toContain("fn");
    expect(await shown(page, "#tips")).not.toContain("Alt");
    await page.locator("#keys-btn").click();
    expect(await shown(page, "#keys-panel")).toContain("control, not");
    expect(await shown(page, "#keys-panel")).not.toContain("Alt-W");
    await page.locator("#keys-btn").click();

    // Option-4 is F4
    await macKey(page, { key: "¢", code: "Digit4", altKey: true }, 52);
    await waitForScreen(page, "Hint 1 of 3");
    // Esc under an input method (keyCode 229), then 4: F4 again
    await macKey(page, { key: "Escape", code: "Escape" }, 229);
    await page.keyboard.press("4");
    await waitForScreen(page, "Hint 2 of 3");
    // Ctrl-L under an input method
    await macKey(page, { key: "Process", code: "KeyL", ctrlKey: true }, 229);
    await waitForScreen(page, "lesson hidden");
    await macKey(page, { key: "Process", code: "KeyL", ctrlKey: true }, 229);
    await waitForScreen(page, "lesson shown");

    // Option-W
    let mark = await sentCount(page);
    await macKey(page, { key: "∑", code: "KeyW", altKey: true }, 87);
    expect(await sentSince(page, mark)).toEqual(["\x17"]);
    await macKey(page, { key: "∑", code: "KeyW", altKey: true }, 87);

    // Ctrl-Q with a Hebrew input source: Q types "/", so keyCode is 191
    await macKey(page, { key: "/", code: "KeyQ", ctrlKey: true }, 191);
    await waitForScreen(page, "LSE has exited");
    await page.keyboard.press("Enter");
    await waitForScreen(page, "Lesson 1 of 10");

    // Option-Q
    mark = await sentCount(page);
    await macKey(page, { key: "œ", code: "KeyQ", altKey: true }, 81);
    await waitForScreen(page, "LSE has exited");
    expect(await sentSince(page, mark)).toEqual(["\x11"]);
  });

  test("Option-N moves to the next placeholder without leaving an accent behind", async ({ page }) => {
    await openLse(page, START);
    await waitForScreen(page, "Lesson 1 of 10");
    const mark = await sentCount(page);
    await macKey(page, { key: "Dead", code: "KeyN", altKey: true }, 78);
    // macOS starts the ~ accent anyway; the next key would come out as ñ or ~x
    await page.evaluate(() => {
      const ta = document.querySelector(".xterm-helper-textarea");
      ta.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true, data: "" }));
      ta.value = "˜";
      ta.dispatchEvent(new CompositionEvent("compositionupdate", { bubbles: true, data: "˜" }));
      ta.dispatchEvent(new InputEvent("input", {
        bubbles: true, data: "˜", inputType: "insertCompositionText", isComposing: true,
      }));
    });
    await page.waitForTimeout(100);
    await page.keyboard.type("x");
    await expect.poll(() => sentSince(page, mark)).toEqual(["\x0e", "x"]);
    expect(await page.evaluate(() => document.activeElement?.className)).toContain("xterm-helper-textarea");
    await expect(page.locator("#bezel")).not.toHaveClass(/unfocused/);
  });
});

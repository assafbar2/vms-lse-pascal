// Driving the LSE page from Playwright tests.

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

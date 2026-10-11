import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.LSE_WEB_PORT || 8123);
// LSE_WEB_URL=https://assafbar2.github.io/vms-lse-pascal/ tests a deployed site instead
const external = process.env.LSE_WEB_URL;
const local = `http://localhost:${port}/vms-lse-pascal/`;

export default defineConfig({
  testDir: "tests",
  timeout: 240_000,
  expect: { timeout: 30_000 },
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: external || local,
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
  },
  webServer: external
    ? undefined
    : {
        command: `node serve.mjs --port ${port}`,
        url: local,
        reuseExistingServer: !process.env.CI,
      },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], viewport: { width: 1280, height: 800 } } },
    { name: "webkit", use: { ...devices["Desktop Safari"], viewport: { width: 1280, height: 800 } } },
  ],
});

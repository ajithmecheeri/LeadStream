import { defineConfig } from "@playwright/test";

// Runs against a stack that is already up: `make up` (Docker) or `make dev` (local processes).
// First time on a laptop: `pnpm --filter @fitfirst/web exec playwright install chromium`.
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  reporter: [["list"]],
});

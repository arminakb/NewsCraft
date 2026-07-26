import { defineConfig, devices } from "@playwright/test"

const chromiumExecutablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
const playwrightPort = process.env.PLAYWRIGHT_PORT ?? "3000"
const playwrightBaseUrl = `http://localhost:${playwrightPort}`
const chromiumLaunchOptions =
  chromiumExecutablePath || process.env.PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS
    ? {
        ...(chromiumExecutablePath ? { executablePath: chromiumExecutablePath } : {}),
        ...(process.env.PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS ? { args: ["--single-process", "--disable-gpu"] } : {}),
      }
    : undefined

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  workers: 2,
  use: {
    baseURL: playwrightBaseUrl,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npm run dev -- --port ${playwrightPort}`,
    url: playwrightBaseUrl,
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: chromiumLaunchOptions,
      },
    },
  ],
})

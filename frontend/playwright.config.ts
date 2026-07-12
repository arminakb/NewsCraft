import { defineConfig, devices } from "@playwright/test"

const chromiumExecutablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
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
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
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

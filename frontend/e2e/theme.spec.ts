import { expect, test } from "@playwright/test"

import { installMockBackend } from "./support/mock-backend"

test("new users receive system theme before the page becomes interactive", async ({ page }) => {
  await installMockBackend(page)
  await page.emulateMedia({ colorScheme: "dark" })
  await page.addInitScript(() => window.localStorage.removeItem("newscraft-theme"))

  await page.goto("/", { waitUntil: "domcontentloaded" })

  await expect(page.locator("html")).toHaveClass(/dark/)
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")
  await expect(page.locator("#newscraft-theme-init")).toHaveCount(1)
})

test("explicit theme choice persists across reloads", async ({ page }) => {
  await installMockBackend(page)
  await page.emulateMedia({ colorScheme: "light" })
  await page.goto("/")
  await page.evaluate(() => window.localStorage.removeItem("newscraft-theme"))
  await page.reload()
  await expect(page.getByText("No workflow jobs yet", { exact: true })).toBeVisible()

  const toggle = page
    .getByRole("complementary", { name: "Global navigation" })
    .getByRole("button", { name: "Toggle color theme" })
  await expect(toggle).toHaveAttribute("aria-pressed", "false")
  await toggle.click()

  await expect(page.locator("html")).toHaveClass(/dark/)
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("newscraft-theme")))
    .toBe("dark")

  await page.reload()

  await expect(page.locator("html")).toHaveClass(/dark/)
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")
  await expect(toggle).toHaveAttribute("aria-pressed", "true")
})

import { expect, test } from "@playwright/test"

import { installMockBackend } from "./support/mock-backend"

test("Today clock keeps reference behavior across time, navigation, themes, and narrow desktop", async ({ page }) => {
  await installMockBackend(page)
  const hydrationMessages: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error" && /hydration/i.test(message.text())) hydrationMessages.push(message.text())
  })
  page.on("pageerror", (error) => {
    if (/hydration/i.test(error.message)) hydrationMessages.push(error.message)
  })

  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto("/")
  const clock = page.getByTestId("flip-clock")
  await expect(clock).toBeVisible()
  await expect(clock).toHaveAttribute("data-time", /^\d{2}:\d{2}:\d{2}$/)
  await expect(clock.locator(".flip-clock-digit")).toHaveCount(6)
  await expect(clock.locator(".flip-clock-separator")).toHaveCount(2)
  const digitBox = await clock.locator(".flip-clock-digit").first().boundingBox()
  expect(digitBox?.width).toBeCloseTo(40, 0)
  expect(digitBox?.height).toBeCloseTo(56, 0)

  const firstTime = await clock.getAttribute("data-time")
  await expect
    .poll(() => clock.getAttribute("data-time"), { timeout: 2500, message: "clock did not advance by one second" })
    .not.toBe(firstTime)

  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible()
  const titleBox = await page.getByRole("heading", { name: "Today", exact: true }).boundingBox()
  const clockBox = await clock.boundingBox()
  expect(titleBox).not.toBeNull()
  expect(clockBox).not.toBeNull()
  expect(clockBox!.x).toBeGreaterThanOrEqual(titleBox!.x + titleBox!.width)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)

  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme)
    await expect(clock).toBeVisible()
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
  }

  await page.reload()
  await expect(page.getByTestId("flip-clock")).toBeVisible()
  await page.goto("/feed")
  await page.goto("/")
  await expect(page.getByTestId("flip-clock")).toBeVisible()

  expect(hydrationMessages).toEqual([])
})

async function setTheme(page: import("@playwright/test").Page, theme: "light" | "dark") {
  await page.evaluate((selectedTheme) => {
    const root = document.documentElement
    root.classList.toggle("dark", selectedTheme === "dark")
    root.dataset.theme = selectedTheme
    root.style.colorScheme = selectedTheme
  }, theme)
}

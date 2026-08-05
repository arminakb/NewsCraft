import { expect, test } from "@playwright/test"

import { installMockBackend } from "./support/mock-backend"

test("opens notifications as an in-place right drawer in both themes", async ({ page }, testInfo) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/")

  const bell = page.getByRole("button", { name: "Open notifications" })
  const initialUrl = page.url()
  await bell.click()

  const drawer = page.getByRole("dialog", { name: "Your notifications" })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole("button", { name: "Close notifications" })).toBeFocused()
  await expect(page).toHaveURL(initialUrl)
  await expect(drawer.locator(".overflow-y-auto")).toBeVisible()
  await expect(drawer.getByText("No notifications yet.")).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("notifications-drawer-light.png"), fullPage: true })

  await drawer.getByRole("button", { name: "Close notifications" }).click()
  await expect(drawer).toBeHidden()
  await bell.click()
  await page.mouse.click(12, 12)
  await expect(drawer).toBeHidden()
  await bell.click()
  await page.keyboard.press("Escape")
  await expect(drawer).toBeHidden()

  await page.evaluate(() => {
    document.documentElement.classList.add("dark")
    document.documentElement.dataset.theme = "dark"
  })
  await bell.click()
  await expect(drawer).toHaveClass(/dark:bg-card|bg-card/)
  await page.screenshot({ path: testInfo.outputPath("notifications-drawer-dark.png"), fullPage: true })

  await drawer.getByRole("button", { name: "Close notifications" }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")
  const mobileNavigation = page.getByRole("navigation", { name: "Mobile newsroom navigation" })
  await mobileNavigation.getByRole("button", { name: "Open navigation" }).click()
  const mobileMenu = page.getByRole("dialog", { name: "Newsroom navigation" })
  await mobileMenu.getByRole("button", { name: "Open notifications" }).click()
  await expect(mobileMenu).toBeHidden()
  const mobileDrawer = page.getByRole("dialog", { name: "Your notifications" })
  await expect(mobileDrawer).toBeVisible()
  const drawerBox = await mobileDrawer.boundingBox()
  expect(drawerBox?.width).toBeGreaterThanOrEqual(380)
  await mobileDrawer.getByRole("button", { name: "Close notifications" }).click()
  await expect(mobileDrawer).toBeHidden()
  expect(unhandledRequests).toEqual([])
})

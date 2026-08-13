import { expect, test } from "@playwright/test"

import { installMockBackend } from "./support/mock-backend"

const EMPTY_MESSAGE = "We'll let you know when we have news for you."

test("keeps a fixed-size anchored popup across states and themes", async ({ page }, testInfo) => {
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
  await expect(drawer.locator("[data-notifications-scroll]")).toBeVisible()
  await expect(drawer.getByText("Workflow approval required")).toBeVisible()
  await expect(drawer.getByText('“AI Daily Brief” has completed and is waiting for your approval.')).toBeVisible()
  await expect(drawer.getByText("Approvals", { exact: true })).toBeVisible()
  await expect(drawer.getByText("Just now", { exact: true })).toBeVisible()
  await expect(drawer.locator("[data-unread-indicator]")).toHaveCount(1)
  await expect(drawer.getByRole("tab", { name: /^All/ })).toBeVisible()
  await expect(drawer.getByRole("tab", { name: /^Approvals/ })).toBeVisible()
  await expect(drawer.getByRole("tab", { name: /^Issues/ })).toBeVisible()
  await expect(drawer.getByRole("button", { name: "Notification settings" })).toHaveCount(0)
  await expect(drawer.getByRole("button", { name: /Clear all notifications|Mark all notifications as read/ })).toHaveCount(0)

  const rail = page.getByRole("complementary", { name: "Global navigation" })
  const railBox = await rail.boundingBox()
  const popupBox = await drawer.boundingBox()
  expectFixedPopupSize(popupBox)
  expect(popupBox?.x).toBeGreaterThanOrEqual((railBox?.x ?? 0) + (railBox?.width ?? 0))
  expect((popupBox?.x ?? 0) + (popupBox?.width ?? 0)).toBeLessThan(page.viewportSize()?.width ?? 1440)
  await expect(drawer).toHaveAttribute("data-side", "right")
  await expect.poll(async () => drawer.locator("[data-notifications-scroll]").evaluate((node) => node.scrollHeight <= node.clientHeight)).toBe(true)
  const oneNotificationSize = { height: popupBox?.height ?? 0, width: popupBox?.width ?? 0 }

  await drawer.getByRole("tab", { name: /^Issues/ }).click()
  await expect(drawer.getByText(EMPTY_MESSAGE, { exact: true })).toBeVisible()
  expectSamePopupSize(await drawer.boundingBox(), oneNotificationSize)
  await drawer.getByRole("tab", { name: /^All/ }).click()
  await expect(drawer.getByText("Workflow approval required")).toBeVisible()
  expectSamePopupSize(await drawer.boundingBox(), oneNotificationSize)
  await page.screenshot({ path: testInfo.outputPath("notifications-popup-light.png"), fullPage: true })

  await drawer.getByRole("button", { name: "Close notifications" }).click()
  await expect(drawer).toBeHidden()
  await bell.click()
  await page.mouse.click(12, 12)
  await expect(drawer).toBeHidden()
  await bell.click()
  await page.keyboard.press("Escape")
  await expect(drawer).toBeHidden()

  await page.goto("/?notifications=overflow")
  const overflowBell = page.getByRole("button", { name: "Open notifications" })
  await overflowBell.click()
  const overflowDrawer = page.getByRole("dialog", { name: "Your notifications" })
  const overflowScroll = overflowDrawer.locator("[data-notifications-scroll]")
  await expect(overflowDrawer.getByText("Temporary approval item 9")).toBeVisible()
  await expect.poll(async () => overflowScroll.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true)
  await expect.poll(async () => overflowScroll.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true)
  const overflowBox = await overflowDrawer.boundingBox()
  expectFixedPopupSize(overflowBox)
  expectSamePopupSize(overflowBox, oneNotificationSize)
  await page.screenshot({ path: testInfo.outputPath("notifications-popup-overflow-light.png"), fullPage: true })
  await overflowDrawer.getByRole("button", { name: "Close notifications" }).click()
  await expect(overflowDrawer).toBeHidden()

  await page.evaluate(() => {
    document.documentElement.classList.add("dark")
    document.documentElement.dataset.theme = "dark"
  })
  await page.getByRole("button", { name: "Open notifications" }).click()
  const darkDrawer = page.getByRole("dialog", { name: "Your notifications" })
  await expect(darkDrawer).toHaveClass(/bg-card/)
  expectFixedPopupSize(await darkDrawer.boundingBox())
  await page.screenshot({ path: testInfo.outputPath("notifications-popup-dark.png"), fullPage: true })

  await darkDrawer.getByRole("button", { name: "Close notifications" }).click()
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
  expect(drawerBox?.width).toBeLessThanOrEqual(390 - 16)
  expect(drawerBox?.height).toBeLessThanOrEqual(575)
  expect(drawerBox?.height).toBeGreaterThan(0)
  expect(drawerBox?.x).toBeGreaterThanOrEqual(8)
  expect((drawerBox?.x ?? 0) + (drawerBox?.width ?? 0)).toBeLessThanOrEqual(390 - 8)
  await expect(mobileDrawer).toHaveAttribute("data-side", "top")
  await mobileDrawer.getByRole("button", { name: "Close notifications" }).click()
  await expect(mobileDrawer).toBeHidden()
  expect(unhandledRequests).toEqual([])
})

function expectFixedPopupSize(box: { height: number; width: number } | null) {
  expect(box).not.toBeNull()
  expect(box?.width ?? 0).toBeCloseTo(450, 0)
  expect(box?.height ?? 0).toBeCloseTo(575, 0)
}

function expectSamePopupSize(box: { height: number; width: number } | null, reference: { height: number; width: number }) {
  expect(box).not.toBeNull()
  expect(box?.width ?? 0).toBeCloseTo(reference.width, 0)
  expect(box?.height ?? 0).toBeCloseTo(reference.height, 0)
}

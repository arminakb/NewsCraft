import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Page } from "@playwright/test"

import { installMockBackend } from "./support/mock-backend"

const VIEWPORTS = [
  { label: "standard desktop", width: 1440, height: 900, desktopNavigation: true },
  { label: "smaller laptop", width: 1280, height: 720, desktopNavigation: true },
  { label: "tablet portrait", width: 768, height: 1024, desktopNavigation: false },
  { label: "tablet landscape", width: 1024, height: 768, desktopNavigation: true },
  { label: "375px mobile portrait", width: 375, height: 812, desktopNavigation: false },
  { label: "mobile landscape", width: 844, height: 390, desktopNavigation: false },
] as const

const TABLET_VIEWPORTS = VIEWPORTS.filter(({ label }) => label.startsWith("tablet"))
const THEMES = ["light", "dark"] as const

test("shell stays bounded and navigable across the Phase 6 viewport matrix", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport)
    await page.goto("/")
    await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible()
    await expectNoPageOverflow(page)

    const desktopNavigation = page.getByRole("complementary", { name: "Global navigation" })
    const mobileNavigation = page.getByRole("navigation", { name: "Mobile newsroom navigation" })
    if (viewport.desktopNavigation) {
      await expect(desktopNavigation).toBeVisible()
      await expect(mobileNavigation).toBeHidden()
      await expect(desktopNavigation).toHaveJSProperty("scrollHeight", await desktopNavigation.evaluate((node) => node.clientHeight))
    } else {
      await expect(desktopNavigation).toBeHidden()
      await expect(mobileNavigation).toBeVisible()
      await expectMinimumTargetSize(mobileNavigation.locator("a, button"), 44)
    }
  }

  expect(unhandledRequests).toEqual([])
})

test("mobile navigation remains bounded, traps focus, and restores its trigger in landscape", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 844, height: 390 })
  await page.goto("/")

  const trigger = page.getByRole("button", { name: "Open navigation" })
  await trigger.click()
  const dialog = page.getByRole("dialog", { name: "Newsroom navigation" })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole("link", { name: "Today", exact: true })).toBeFocused()

  const bounds = await dialog.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds?.y ?? -1).toBeGreaterThanOrEqual(8)
  expect((bounds?.y ?? 0) + (bounds?.height ?? 0)).toBeLessThanOrEqual(390)

  const settings = dialog.getByRole("link", { name: "Settings", exact: true })
  await settings.focus()
  await page.keyboard.press("Tab")
  await expect(dialog.getByRole("button", { name: "Toggle color theme" })).toBeFocused()

  await page.keyboard.press("Escape")
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("")
  expect(unhandledRequests).toEqual([])
})

test("desktop icon controls expose keyboard tooltips and visible focus", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto("/")

  const themeToggle = page.getByRole("button", { name: "Toggle color theme" })
  await themeToggle.focus()
  await expect(page.getByRole("tooltip", { name: "Switch to dark theme" })).toBeVisible()
  await expect(themeToggle).toBeFocused()
  expect(await themeToggle.evaluate((node) => node.matches(":focus-visible"))).toBe(true)
  expect(await themeToggle.evaluate((node) => getComputedStyle(node).outlineWidth)).toBe("2px")

  const settings = page.getByRole("link", { name: "Settings", exact: true })
  await settings.focus()
  await expect(page.getByRole("tooltip", { name: "Settings" })).toBeVisible()
  expect(await settings.evaluate((node) => node.matches(":focus-visible"))).toBe(true)
  expect(unhandledRequests).toEqual([])
})

test("reduced motion and 200% text sizing preserve usable mobile content", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto("/")
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%"
  })

  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Mobile newsroom navigation" })).toBeVisible()
  await expectNoPageOverflow(page)

  const menu = page.getByRole("button", { name: "Open navigation" })
  const transitionDuration = await menu.evaluate((node) => getComputedStyle(node).transitionDuration)
  expect(parseCssSeconds(transitionDuration)).toBeLessThanOrEqual(0.001)
  expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true)
  expect(unhandledRequests).toEqual([])
})

for (const viewport of TABLET_VIEWPORTS) {
  for (const theme of THEMES) {
    test(`${viewport.label} ${theme} shell has no serious or critical axe violations`, async ({ page }) => {
      const unhandledRequests = await installMockBackend(page)
      await page.setViewportSize(viewport)
      await page.goto("/")
      await setTheme(page, theme)
      await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible()
      await expectNoPageOverflow(page)
      await expectNoSeriousAxeViolations(page)
      expect(unhandledRequests).toEqual([])
    })
  }
}

async function expectMinimumTargetSize(locator: ReturnType<Page["locator"]>, minimum: number) {
  const undersized = await locator.evaluateAll((nodes, min) => nodes
    .filter((node) => {
      const element = node as HTMLElement
      const style = getComputedStyle(element)
      if (style.visibility === "hidden" || style.display === "none") return false
      const bounds = element.getBoundingClientRect()
      return bounds.width < min || bounds.height < min
    })
    .map((node) => {
      const element = node as HTMLElement
      const bounds = element.getBoundingClientRect()
      return {
        label: element.getAttribute("aria-label") ?? element.textContent?.trim(),
        width: bounds.width,
        height: bounds.height,
      }
    }), minimum)
  expect(undersized).toEqual([])
}

async function expectNoPageOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() =>
    document.documentElement.scrollWidth > document.documentElement.clientWidth
    || document.body.scrollWidth > window.innerWidth
  )).toBe(false)
}

async function expectNoSeriousAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze()
  const violations = results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      targets: violation.nodes.flatMap((node) => node.target),
    }))
  expect(violations).toEqual([])
}

async function setTheme(page: Page, theme: (typeof THEMES)[number]) {
  await page.evaluate((selectedTheme) => {
    window.localStorage.setItem("newscraft-theme", selectedTheme)
    const root = document.documentElement
    root.classList.toggle("dark", selectedTheme === "dark")
    root.dataset.theme = selectedTheme
    root.style.colorScheme = selectedTheme
  }, theme)
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
}

function parseCssSeconds(value: string) {
  return Math.max(...value.split(",").map((duration) => {
    const trimmed = duration.trim()
    return trimmed.endsWith("ms")
      ? Number.parseFloat(trimmed) / 1000
      : Number.parseFloat(trimmed)
  }))
}

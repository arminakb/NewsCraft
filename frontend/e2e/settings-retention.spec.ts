import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Page } from "@playwright/test"

import { installMockBackend } from "./support/mock-backend"

const shortcuts = [
  ["Editorial profiles", "editorial-profiles"],
  ["LLM providers", "llm-providers"],
  ["Codex", "codex-connection"],
  ["Telegram", "telegram-destinations"],
  ["Prompts", "prompt-governance"],
  ["Retention", "retention"],
] as const

test("Settings shortcuts scroll smoothly and move focus without duplicate animations", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await captureScrollIntoView(page)
  await page.emulateMedia({ reducedMotion: "no-preference" })
  await page.goto("/settings/content")

  const navigation = page.getByRole("navigation", { name: "Settings sections" })
  await expect(navigation.getByRole("link")).toHaveCount(shortcuts.length)

  for (const [label, id] of shortcuts) {
    const shortcut = navigation.getByRole("link", { name: label, exact: true })
    await expect(shortcut).toHaveAttribute("href", `#${id}`)
    expect((await shortcut.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    await shortcut.click()
    await expect(page.locator(`#${id}`)).toBeFocused()
    await expect(page).toHaveURL(new RegExp(`#${id}$`))
    expect(await lastScrollBehavior(page)).toBe("smooth")
  }

  const retentionShortcut = navigation.getByRole("link", { name: "Retention", exact: true })
  await expect(retentionShortcut.locator("svg")).toHaveCount(1)
  await navigation.getByRole("link", { name: "Prompts", exact: true }).click()
  const beforeRepeat = await scrollCallCount(page)
  await retentionShortcut.evaluate((element) => {
    const link = element as HTMLElement
    link.click()
    link.click()
  })
  expect(await scrollCallCount(page)).toBe(beforeRepeat + 1)
  expect(unhandledRequests).toEqual([])
})

test("old Retention route redirects, restores section focus, and respects reduced motion", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await captureScrollIntoView(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto("/settings/retention")

  await expect(page).toHaveURL(/\/settings\/content#retention$/)
  await expect(page.getByRole("heading", { name: "Retention", exact: true })).toBeAttached()
  await expect(page.locator("#retention")).toBeFocused()
  expect(await lastScrollBehavior(page)).toBe("auto")
  expect(await page.evaluate(() =>
    document.documentElement.scrollWidth <= document.documentElement.clientWidth
    && document.body.scrollWidth <= window.innerWidth
  )).toBe(true)
  expect(unhandledRequests).toEqual([])
})

for (const viewport of [
  { label: "mobile", width: 375, height: 812 },
  { label: "tablet", width: 768, height: 1024 },
  { label: "desktop", width: 1440, height: 900 },
] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`integrated Retention stays accessible in ${viewport.label} ${theme} mode`, async ({ page }) => {
      const unhandledRequests = await installMockBackend(page)
      await page.setViewportSize(viewport)
      await page.goto("/settings/content")
      await setTheme(page, theme)

      await expect(page.getByRole("heading", { name: "Retention", exact: true })).toBeAttached()
      await expect(page.getByLabel("Raw payload retention days")).toBeAttached()
      expect(await page.evaluate(() =>
        document.documentElement.scrollWidth <= document.documentElement.clientWidth
        && document.body.scrollWidth <= window.innerWidth
      )).toBe(true)

      const results = await new AxeBuilder({ page }).analyze()
      expect(results.violations
        .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
        .map((violation) => violation.id)).toEqual([])
      expect(unhandledRequests).toEqual([])
    })
  }
}

async function captureScrollIntoView(page: Page) {
  await page.addInitScript(() => {
    const calls: ScrollIntoViewOptions[] = []
    Object.defineProperty(window, "__settingsScrollCalls", {
      configurable: true,
      value: calls,
    })
    Element.prototype.scrollIntoView = function scrollIntoView(options?: boolean | ScrollIntoViewOptions) {
      if (typeof options === "object") calls.push(options)
    }
  })
}

async function lastScrollBehavior(page: Page) {
  return page.evaluate(() => {
    const calls = (window as unknown as Window & {
      __settingsScrollCalls: ScrollIntoViewOptions[]
    }).__settingsScrollCalls
    return calls.at(-1)?.behavior
  })
}

async function scrollCallCount(page: Page) {
  return page.evaluate(() =>
    (window as unknown as Window & {
      __settingsScrollCalls: ScrollIntoViewOptions[]
    }).__settingsScrollCalls.length
  )
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((selectedTheme) => {
    window.localStorage.setItem("newscraft-theme", selectedTheme)
    const root = document.documentElement
    root.classList.toggle("dark", selectedTheme === "dark")
    root.dataset.theme = selectedTheme
    root.style.colorScheme = selectedTheme
  }, theme)
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
}

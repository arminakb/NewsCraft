import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Page } from "@playwright/test"

import { installMockBackend } from "./support/mock-backend"

const categories = [
  ["LLM Providers", "llm-providers"],
  ["Codex", "codex"],
  ["Telegram", "telegram"],
  ["Date & Time", "date-time"],
  ["Retention", "retention"],
  ["Prompts", "prompts"],
] as const

const llmProvider = {
  id: "44444444-4444-4444-8444-444444444444",
  name: "Newsroom model",
  protocol: "openai_compatible",
  base_url: "https://llm.example/v1",
  default_model: "openai/gpt-5-mini",
  enabled: true,
  configured: true,
  settings: {
    timeout_seconds: 60,
    max_input_tokens: 60_000,
    max_output_tokens: 12_000,
    pricing: { input_usd_per_million: "0", output_usd_per_million: "0" },
    attribution_headers: { http_referer: null, app_title: "NewsCraft" },
  },
  health_status: "healthy",
  generation_capability: "ready",
  research_capability: "unavailable",
  generation_ready: true,
  research_ready: false,
  failure_code: "research_budget_missing",
  last_checked_at: "2026-07-23T08:00:00Z",
  ownership: "operator_managed",
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

test("sidebar gear opens route-backed Settings and category history stays navigable", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/")

  const settingsTrigger = page.getByRole("link", { name: "Settings", exact: true })
  await settingsTrigger.click()

  await expect(page).toHaveURL(/\/settings\?section=llm-providers$/)
  const dialog = page.getByRole("dialog", { name: "Settings" })
  await expect(dialog).toBeVisible()
  const navigation = dialog.getByRole("navigation", { name: "Settings categories" })
  await expect(navigation.getByRole("button")).toHaveCount(categories.length)
  await expect(navigation.getByRole("button", { name: "LLM Providers" }))
    .toHaveAttribute("aria-current", "page")

  for (const [label, section] of categories) {
    const button = navigation.getByRole("button", { name: label, exact: true })
    expect((await button.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    await expect(button.locator("svg")).toHaveCount(1)
    await button.click()
    await expect(page).toHaveURL(new RegExp(`/settings\\?section=${section}$`))
    await expect(dialog.getByRole("heading", { name: label, exact: true }).first()).toBeVisible()
  }

  await navigation.getByRole("button", { name: "LLM Providers" }).click()
  await expect(page).toHaveURL(/section=llm-providers$/)
  await navigation.getByRole("button", { name: "Telegram" }).click()
  await expect(page).toHaveURL(/section=telegram$/)
  await page.goBack()
  await expect(page).toHaveURL(/section=llm-providers$/)
  await expect(navigation.getByRole("button", { name: "LLM Providers" }))
    .toHaveAttribute("aria-current", "page")
  await page.goForward()
  await expect(page).toHaveURL(/section=telegram$/)

  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  for (let index = 0; index < 14; index += 1) await page.keyboard.press("Tab")
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe("hidden")

  await dialog.getByRole("button", { name: "Close Settings" }).first().click()
  await expect(page).toHaveURL(/\/$/)
  await expect(dialog).not.toBeVisible()
  await expect(settingsTrigger).toBeFocused()
  expect(unhandledRequests).toEqual([])
})

test("LLM provider card stays compact with stable primary and overflow actions", async ({
  page,
}, testInfo) => {
  const unhandledRequests = await installMockBackend(page)
  await page.route("**/api/backend/llm-providers", async (route) => {
    await route.fulfill({
      body: JSON.stringify([llmProvider]),
      contentType: "application/json",
      status: 200,
    })
  })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto("/settings?section=llm-providers")

  const card = page.getByTestId("llm-provider-card")
  await expect(card).toBeVisible()
  await expect(card.getByText(llmProvider.default_model)).toBeVisible()
  await expect(card.getByText("Generation", { exact: true })).toBeVisible()
  await expect(card.getByText("Research", { exact: true })).toBeVisible()
  await expect(card.getByText("API key", { exact: true })).toBeVisible()
  await expect(card.getByText("Last checked", { exact: true })).toBeVisible()
  expect((await card.boundingBox())?.height).toBeLessThan(220)

  const primaryActions = card.getByRole("group", {
    name: `Primary actions for ${llmProvider.name}`,
  })
  await expect(primaryActions.getByRole("button")).toHaveCount(3)
  const desktopActionBoxes = await primaryActions.getByRole("button").evaluateAll((buttons) =>
    buttons.map((button) => {
      const bounds = button.getBoundingClientRect()
      return { left: bounds.left, right: bounds.right, top: bounds.top }
    })
  )
  expect(new Set(desktopActionBoxes.map(({ top }) => Math.round(top))).size).toBe(1)
  for (let index = 1; index < desktopActionBoxes.length; index += 1) {
    expect(desktopActionBoxes[index].left).toBeGreaterThan(desktopActionBoxes[index - 1].right)
  }

  await card.getByRole("button", { name: `More actions for ${llmProvider.name}` }).click()
  await expect(page.getByRole("menuitem", { name: "Rotate key" })).toBeVisible()
  await expect(page.getByRole("menuitem", { name: "Dependencies" })).toBeVisible()
  await expect(page.getByRole("menuitem", { name: "Delete provider" })).toBeVisible()
  await page.keyboard.press("Escape")
  const lightAccessibility = await new AxeBuilder({ page })
    .include('[data-testid="llm-provider-card"]')
    .analyze()
  expect(lightAccessibility.violations.filter(({ impact }) =>
    impact === "critical" || impact === "serious"
  )).toEqual([])
  await page.screenshot({
    path: testInfo.outputPath("llm-providers-desktop.png"),
  })

  await page.setViewportSize({ width: 375, height: 812 })
  const settings = page.getByRole("dialog", { name: "Settings" })
  await settings.getByRole("button", { name: "LLM Providers" }).click()
  await expect(card).toBeVisible()
  const mobileCard = await card.boundingBox()
  expect(mobileCard?.x).toBeGreaterThanOrEqual(0)
  expect((mobileCard?.x ?? 0) + (mobileCard?.width ?? 0)).toBeLessThanOrEqual(375)
  for (const button of await primaryActions.getByRole("button").all()) {
    expect((await button.boundingBox())?.height).toBeGreaterThanOrEqual(44)
  }
  expect((await card.getByRole("button", {
    name: `More actions for ${llmProvider.name}`,
  }).boundingBox())?.height).toBeGreaterThanOrEqual(44)
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  const darkAccessibility = await new AxeBuilder({ page })
    .include('[data-testid="llm-provider-card"]')
    .analyze()
  expect(darkAccessibility.violations.filter(({ impact }) =>
    impact === "critical" || impact === "serious"
  )).toEqual([])
  await page.screenshot({
    path: testInfo.outputPath("llm-providers-mobile.png"),
  })

  expect(unhandledRequests).toEqual([])
})

test("close button and Escape return to opener and restore Settings trigger focus", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto("/")
  const settingsTrigger = page.getByRole("link", { name: "Settings", exact: true })

  await settingsTrigger.click()
  await page.getByRole("dialog", { name: "Settings" })
    .getByRole("button", { name: "Close Settings" })
    .first()
    .click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole("dialog", { name: "Settings" })).not.toBeVisible()
  await expect(settingsTrigger).toBeFocused()
  await expect.poll(() =>
    page.evaluate(() => getComputedStyle(document.documentElement).overflow)
  ).not.toBe("hidden")

  await settingsTrigger.click()
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole("dialog", { name: "Settings" })).not.toBeVisible()
  await expect(settingsTrigger).toBeFocused()
  await expect.poll(() =>
    page.evaluate(() => getComputedStyle(document.documentElement).overflow)
  ).not.toBe("hidden")
  expect(unhandledRequests).toEqual([])
})

test("direct links, refresh, invalid values, legacy routes, and Back/Forward preserve sections", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 1280, height: 720 })

  await page.goto("/settings?section=retention")
  await expect(page.getByRole("heading", { name: "Retention", exact: true }).first()).toBeVisible()
  await page.reload()
  await expect(page).toHaveURL(/section=retention$/)
  await expect(page.getByLabel("Raw payload retention days")).toBeVisible()

  await page.goto("/settings?section=not-real")
  await expect(page).toHaveURL(/section=llm-providers$/)
  await expect(page.getByRole("heading", { name: "LLM Providers", exact: true })).toBeVisible()

  await page.goto("/settings/retention")
  await expect(page).toHaveURL(/\/settings\?section=retention$/)
  await page.goto("/calendar")
  await expect(page).toHaveURL(/\/settings\?section=date-time$/)
  await page.goto("/settings/content#telegram-destinations")
  await expect(page).toHaveURL(/\/settings\?section=telegram$/)

  const directDialog = page.getByRole("dialog", { name: "Settings" })
  await directDialog.getByRole("button", { name: "Close Settings" }).first().click()
  await expect(page).toHaveURL(/\/$/)
  await expect(directDialog).not.toBeVisible()
  expect(unhandledRequests).toEqual([])
})

test("unsaved changes block backdrop dismissal and guard category changes", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto("/settings?section=date-time")

  const dialog = page.getByRole("dialog", { name: "Settings" })
  const timezone = dialog.getByRole("combobox", { name: "Application timezone" })
  await timezone.fill("Mars/Olympus")
  await timezone.blur()
  await expect(dialog.getByRole("alert").filter({ hasText: "valid IANA timezone" })).toBeVisible()

  await page.mouse.click(2, 2)
  await expect(dialog).toBeVisible()

  page.once("dialog", async (confirmation) => {
    expect(confirmation.message()).toBe("Discard unsaved settings changes?")
    await confirmation.dismiss()
  })
  await dialog.getByRole("button", { name: "Retention" }).click()
  await expect(page).toHaveURL(/section=date-time$/)

  page.once("dialog", async (confirmation) => confirmation.accept())
  await dialog.getByRole("button", { name: "Retention" }).click()
  await expect(page).toHaveURL(/section=retention$/)
  expect(unhandledRequests).toEqual([])
})

test("mobile Settings opens category-first, then full-screen content with Back", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")
  await page.getByRole("button", { name: "Open navigation" }).click()
  await page.getByRole("dialog", { name: "Newsroom navigation" })
    .getByRole("link", { name: "Settings", exact: true })
    .click()

  const dialog = page.getByRole("dialog", { name: "Settings" })
  await expect(dialog.getByRole("navigation", { name: "Settings categories" })).toBeVisible()
  const bounds = await dialog.boundingBox()
  expect(bounds?.width).toBe(390)
  expect(bounds?.height).toBe(844)

  await dialog.getByRole("button", { name: "Retention" }).click()
  await expect(dialog.getByRole("button", { name: "Back to Settings categories" })).toBeVisible()
  await expect(dialog.getByLabel("Raw payload retention days")).toBeVisible()
  await dialog.getByRole("button", { name: "Back to Settings categories" }).click()
  await expect(dialog.getByRole("navigation", { name: "Settings categories" })).toBeVisible()

  expect(await page.evaluate(() =>
    document.documentElement.scrollWidth <= document.documentElement.clientWidth
    && document.body.scrollWidth <= window.innerWidth
  )).toBe(true)
  expect(unhandledRequests).toEqual([])
})

test("Date & Time validates, saves, refreshes, and updates newsroom clock", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto("/")
  await page.getByRole("link", { name: "Settings", exact: true }).click()
  await page.getByRole("dialog", { name: "Settings" })
    .getByRole("button", { name: "Date & Time" })
    .click()

  const timezone = page.getByRole("combobox", { name: "Application timezone" })
  await timezone.fill("Europe/London")
  await page.getByRole("button", { name: "Save timezone" }).click()
  await expect(page.getByRole("status").filter({ hasText: "Timezone saved as Europe/London" })).toBeVisible()
  await expect(page.locator('[role="timer"]')).toHaveAttribute("aria-label", /in London/)

  await page.reload()
  await expect(page).toHaveURL(/section=date-time$/)
  await expect(page.getByRole("combobox", { name: "Application timezone" })).toHaveValue("Europe/London")
  expect(unhandledRequests).toEqual([])
})

test("desktop category rail and content panel scroll independently", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.setViewportSize({ width: 1440, height: 460 })
  await page.goto("/settings?section=retention")

  const navigation = page.getByRole("navigation", { name: "Settings categories" })
  const content = page.getByTestId("settings-content-panel")
  await expect(content.getByLabel("Raw payload retention days")).toBeVisible()
  await content.evaluate((element) => { element.scrollTop = 240 })

  expect(await content.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  expect(await navigation.evaluate((element) => element.scrollTop)).toBe(0)
  expect(await content.evaluate((element) => getComputedStyle(element).overflowY)).toBe("auto")
  expect(await navigation.evaluate((element) => getComputedStyle(element).overflowY)).toBe("auto")
  expect(unhandledRequests).toEqual([])
})

for (const viewport of [
  { label: "mobile", width: 390, height: 844 },
  { label: "desktop", width: 1440, height: 900 },
] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`Settings modal has no serious axe violations in ${viewport.label} ${theme} mode`, async ({ page }) => {
      const unhandledRequests = await installMockBackend(page)
      await page.setViewportSize(viewport)
      await page.goto("/settings?section=retention")
      await setTheme(page, theme)
      const dialog = page.getByRole("dialog", { name: "Settings" })
      if (viewport.width < 700) {
        await dialog.getByRole("button", { name: "Retention" }).click()
      }
      await expect(dialog.getByLabel("Raw payload retention days")).toBeVisible()

      const results = await new AxeBuilder({ page }).include('[data-testid="settings-modal"]').analyze()
      expect(results.violations
        .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
        .map((violation) => violation.id)).toEqual([])
      expect(unhandledRequests).toEqual([])
    })
  }
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

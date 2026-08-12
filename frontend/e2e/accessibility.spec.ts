import AxeBuilder from "@axe-core/playwright"
import { expect, test } from "@playwright/test"

import type { components } from "../lib/api/generated"
import { installMockBackend } from "./support/mock-backend"

const ROUTES = [
  { path: "/", name: "Today", heading: "Today", readyText: "No articles collected yet" },
  { path: "/automations", name: "Automations", heading: null, readyText: "No workflows yet" },
  { path: "/operations", name: "Operations Center", heading: "Operations Center", readyText: "Database connectivity is available" },
] as const

const VIEWPORTS = [
  { label: "desktop", width: 1440, height: 1000 },
  { label: "mobile", width: 390, height: 844 },
] as const

const THEMES = ["light", "dark"] as const

const DIAGNOSTICS_STATUS_FIXTURE = {
  generated_at: "2026-07-13T08:00:00Z",
  global_paused: false,
  dry_run: true,
  components: Object.fromEntries(
    (["healthy", "degraded", "down", "unknown"] as const).map((status, index) => [
      `component-${status}`,
      {
        status,
        observed_at: index === 3 ? null : "2026-07-13T07:59:00Z",
        last_success_at: index === 0 ? "2026-07-13T07:58:00Z" : null,
        message: `${status} component state`,
        action_url: status === "healthy" ? null : "/diagnostics",
      },
    ]),
  ),
  queue_counts: {},
  attention: [
    {
      id: "attention-error",
      severity: "error",
      kind: "generation",
      title: "Generation requires review",
      occurred_at: "2026-07-13T07:59:00Z",
      action_url: "/jobs?status=needs_review",
    },
    {
      id: "attention-warning",
      severity: "warning",
      kind: "job",
      title: "Queue is approaching its limit",
      occurred_at: "2026-07-13T07:58:00Z",
      action_url: "/jobs?status=queued",
    },
  ],
  outbound_proxy: {
    mode: "direct",
    scheme: null,
    bypass_rule_count: 0,
    last_connectivity_status: "not_checked",
    configuration_error_code: null,
  },
} satisfies components["schemas"]["OperationsSnapshotOut"]

const HEALTH_STATUS_FIXTURE = {
  generated_at: "2026-07-13T08:00:00Z",
  state: "unavailable",
  state_definitions: {},
  dependencies: Object.fromEntries(
    (["healthy", "stale", "unavailable", "unknown"] as const).map((state, index) => [
      `dependency-${state}`,
      {
        state,
        code: `dependency_${state}`,
        observed_at: "2026-07-13T08:00:00Z",
        latency_ms: index,
        message: `${state} dependency state`,
        runbook_url: "/docs/operations/readiness-and-health",
      },
    ]),
  ),
  components: {},
  queues: [],
  recoveries: [],
  alerts: [],
  metrics: {},
  outbound_proxy: DIAGNOSTICS_STATUS_FIXTURE.outbound_proxy,
} satisfies components["schemas"]["OperationalHealthSnapshot"]

for (const viewport of VIEWPORTS) {
  for (const theme of THEMES) {
    test.describe(`${viewport.label} ${theme} accessibility`, () => {
      for (const route of ROUTES) {
        test(`${route.name} has no serious or critical axe violations`, async ({ page }) => {
          const unhandledRequests = await installMockBackend(page)
          await page.setViewportSize(viewport)
          await page.goto(route.path)
          await setTheme(page, theme)

          if (route.heading) await expect(page.getByRole("heading", { name: route.heading, exact: true }).first()).toBeVisible()
          else await expect(page.getByRole("heading", { name: route.name, exact: true })).toHaveCount(0)
          await expect(page.getByText(route.readyText, { exact: true }).first()).toBeVisible()
          expect(unhandledRequests, `Unhandled backend requests on ${route.path}`).toEqual([])

          const results = await new AxeBuilder({ page }).analyze()
          const violations = results.violations
            .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
            .map((violation) => ({
              id: violation.id,
              impact: violation.impact,
              help: violation.help,
              targets: violation.nodes.flatMap((node) => node.target),
            }))

          expect(violations).toEqual([])
        })
      }

      test("Diagnostics status palettes have no serious or critical axe violations", async ({ page }) => {
        const unhandledRequests = await installMockBackend(page, {
          operations: DIAGNOSTICS_STATUS_FIXTURE,
          operationalHealth: HEALTH_STATUS_FIXTURE,
        })
        await page.setViewportSize(viewport)
        await page.goto("/operations?view=diagnostics")
        await setTheme(page, theme)
        for (const status of ["Healthy", "Stale", "Unavailable", "Unknown"]) {
          await expect(page.getByText(status, { exact: true }).first()).toBeVisible()
        }
        expect(unhandledRequests).toEqual([])
        await expectNoSeriousAxeViolations(page)
      })

      test("Diagnostics loading state has no serious or critical axe violations", async ({ page }) => {
        await installMockBackend(page, { operationsDelayMs: 10_000 })
        await page.setViewportSize(viewport)
        await page.goto("/operations?view=diagnostics")
        await setTheme(page, theme)
        await expect(page.getByRole("status", { name: "Loading operational diagnostics" })).toBeVisible()
        await expectNoSeriousAxeViolations(page)
      })

      test("Diagnostics API-error state has no serious or critical axe violations", async ({ page }) => {
        await installMockBackend(page, { operationsFailure: true })
        await page.setViewportSize(viewport)
        await page.goto("/operations?view=diagnostics")
        await setTheme(page, theme)
        await expect(page.getByRole("alert")).toBeVisible()
        await expectNoSeriousAxeViolations(page)
      })
    })
  }
}

async function setTheme(page: import("@playwright/test").Page, theme: (typeof THEMES)[number]) {
  await page.evaluate((selectedTheme) => {
    window.localStorage.setItem("newscraft-theme", selectedTheme)
    const root = document.documentElement
    root.classList.toggle("dark", selectedTheme === "dark")
    root.dataset.theme = selectedTheme
    root.style.colorScheme = selectedTheme
  }, theme)
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
}

async function expectNoSeriousAxeViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).analyze()
  const violations = results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      targets: violation.nodes.flatMap((node) => node.target),
    }))
  expect(violations).toEqual([])
}

test("headerless Automations state stays compact on narrow and landscape screens", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/automations")

  for (const viewport of [
    { width: 375, height: 667 },
    { width: 844, height: 390 },
  ]) {
    await page.setViewportSize(viewport)
    await expect(page.locator("[data-slot='page-header']")).toHaveCount(0)
    await expect(page.getByText("Build, validate, and operate versioned newsroom workflows.", { exact: true })).toHaveCount(0)
    await expect(page.getByRole("link", { name: "Telegram routes" })).toHaveCount(0)
    await expect(page.getByRole("link", { name: "New workflow" })).toHaveCount(0)
    await expect(page.getByRole("button", { name: "Create new workflow" })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)

    const tabs = await page.getByRole("tablist", { name: "Automation views" }).boundingBox()
    const emptyState = await page.locator("[data-slot='empty-state']").boundingBox()
    expect(tabs).not.toBeNull()
    expect(emptyState).not.toBeNull()
    expect(emptyState!.y - (tabs!.y + tabs!.height)).toBeLessThanOrEqual(20)
  }

  expect(unhandledRequests).toEqual([])
})

test("responsive shell switches at 900px and exposes one skip target", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)

  await page.setViewportSize({ width: 899, height: 844 })
  await page.goto("/")
  await expect(page.getByText("No articles collected yet", { exact: true })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Mobile newsroom navigation" })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Mobile newsroom navigation" }).getByRole("button", { name: "Open navigation" })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Newsroom navigation", exact: true })).toBeHidden()

  const skipLink = page.getByRole("link", { name: "Skip to content" })
  const main = page.getByRole("main")
  await expect(skipLink).toHaveAttribute("href", "#main-content")
  await expect(main).toHaveCount(1)
  await expect(main).toHaveAttribute("id", "main-content")
  await expect(main).toHaveAttribute("tabindex", "-1")
  await page.evaluate(() => {
    document.body.tabIndex = -1
    document.body.focus()
    document.body.removeAttribute("tabindex")
  })
  await page.keyboard.press("Tab")
  await expect(skipLink).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(main).toBeFocused()

  await page.setViewportSize({ width: 900, height: 844 })
  await expect(page.getByRole("navigation", { name: "Newsroom navigation", exact: true })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Mobile newsroom navigation" })).toBeHidden()
  expect(unhandledRequests, "Unhandled backend requests in responsive shell test").toEqual([])
})

test("direct navigation stays bounded across mobile, tablet, landscape, and short desktop", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await page.goto("/")
  await expect(page.getByText("No articles collected yet", { exact: true })).toBeVisible()

  for (const viewport of [
    { width: 375, height: 667 },
    { width: 768, height: 1024 },
    { width: 844, height: 390 },
  ]) {
    await page.setViewportSize(viewport)
    const mobileNavigation = page.getByRole("navigation", { name: "Mobile newsroom navigation" })
    await expect(mobileNavigation).toBeVisible()
    const menu = mobileNavigation.getByRole("button", { name: "Open navigation" })
    await expect(menu).toBeVisible()
    await menu.click()
    const panel = page.getByRole("dialog", { name: "Newsroom navigation" })
    await expect(panel.getByRole("link", { name: "Settings" })).toBeVisible()
    await panel.getByRole("button", { name: "Close navigation panel" }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  }

  await page.setViewportSize({ width: 900, height: 560 })
  await expect(page.getByRole("complementary", { name: "Global navigation" })).toBeHidden()
  await expect(page.getByRole("navigation", { name: "Mobile newsroom navigation" })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  expect(unhandledRequests, "Unhandled backend requests in navigation boundary test").toEqual([])
})

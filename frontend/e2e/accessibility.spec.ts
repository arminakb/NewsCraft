import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Page, type Route } from "@playwright/test"

const ROUTES = [
  { path: "/", name: "Today", readyText: "No workflow jobs yet" },
  { path: "/automations", name: "Telegram automations", readyText: "No Telegram automations yet" },
  { path: "/drafts", name: "Drafts", readyText: "No durable generation requests yet." },
  { path: "/calendar", name: "Publication calendar", readyText: "No publication events in this calendar window." },
  { path: "/diagnostics", name: "Diagnostics", readyText: "System checks" },
] as const

const VIEWPORTS = [
  { label: "desktop", width: 1440, height: 1000 },
  { label: "mobile", width: 390, height: 844 },
] as const

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.label} accessibility`, () => {
    for (const route of ROUTES) {
      test(`${route.name} has no serious or critical axe violations`, async ({ page }) => {
        const unhandledRequests = await installOfflineBackend(page)
        await page.setViewportSize(viewport)
        await page.goto(route.path)

        await expect(page.getByRole("heading", { name: route.name, exact: true }).first()).toBeVisible()
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
  })
}

test("responsive shell switches at 900px and exposes one skip target", async ({ page }) => {
  const unhandledRequests = await installOfflineBackend(page)

  await page.setViewportSize({ width: 899, height: 844 })
  await page.goto("/")
  await expect(page.getByText("No workflow jobs yet", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Newsroom navigation", exact: true })).toBeHidden()

  const skipLink = page.getByRole("link", { name: "Skip to content" })
  const main = page.getByRole("main")
  await expect(skipLink).toHaveAttribute("href", "#main-content")
  await expect(main).toHaveCount(1)
  await expect(main).toHaveAttribute("id", "main-content")
  await expect(main).toHaveAttribute("tabindex", "-1")
  await page.keyboard.press("Tab")
  await expect(skipLink).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(main).toBeFocused()

  await page.setViewportSize({ width: 900, height: 844 })
  await expect(page.getByRole("navigation", { name: "Newsroom navigation", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeHidden()
  expect(unhandledRequests, "Unhandled backend requests in responsive shell test").toEqual([])
})

async function installOfflineBackend(
  page: Page,
): Promise<string[]> {
  const unhandledRequests: string[] = []

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api\/backend/, "")
    const method = request.method()

    if (method === "GET" && path === "/automation-control") {
      await fulfillJson(route, {
        global_pause: false,
        dry_run: true,
        pause_reason: null,
        paused_at: null,
        updated_at: "2026-07-13T08:00:00Z",
      })
      return
    }
    if (method === "GET" && path === "/jobs/summary") {
      await fulfillJson(route, { queued: 0, running: 0, attention: 0, succeeded_today: 0 })
      return
    }
    if (method === "GET" && path === "/jobs") {
      await fulfillJson(route, { items: [] })
      return
    }
    if (method === "GET" && path === "/telegram/drafts") {
      await fulfillJson(route, [])
      return
    }
    if (method === "GET" && path === "/telegram/automations") {
      await fulfillJson(route, [])
      return
    }
    if (method === "GET" && path === "/telegram/automations/options") {
      await fulfillJson(route, {
        sources: [],
        destinations: [],
        brand_profiles: [],
        prompt_template_versions: [],
        ai_provider_profiles: [],
      })
      return
    }
    if (method === "GET" && path === "/content-pack-requests") {
      await fulfillJson(route, [])
      return
    }
    if (method === "GET" && path === "/calendar") {
      await fulfillJson(route, { items: [], timezone: url.searchParams.get("timezone") ?? "Asia/Tehran" })
      return
    }
    if (method === "GET" && path === "/diagnostics") {
      await fulfillJson(route, {
        status: "ok",
        checks: { api: "ok", database: "ok", storage: "ok" },
        source_health: { healthy: 0, partial: 0, failed: 0, unknown: 0 },
        problem_sources: [],
      })
      return
    }

    const requestLabel = `${method} ${path}${url.search}`
    unhandledRequests.push(requestLabel)
    await fulfillJson(route, { detail: `Unhandled deterministic test request: ${requestLabel}` }, 501)
  })

  return unhandledRequests
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

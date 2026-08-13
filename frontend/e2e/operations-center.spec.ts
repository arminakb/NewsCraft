import { expect, test, type Page, type Route } from "@playwright/test"

import { fulfillMockJson } from "./support/mock-backend"

const failedId = "11111111-1111-4111-8111-111111111111"
const queuedId = "22222222-2222-4222-8222-222222222222"

test("operator filters jobs, inspects safe failures, retries, cancels, and runs diagnostics", async ({ page }) => {
  test.slow()
  const requests = await installOperationsBackend(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/operations")

  await expect(page.getByRole("heading", { name: "Operations Center" })).toBeVisible()
  await expect(page.getByRole("region", { name: "Operational status summary" })).toContainText("Unavailable")
  await expect(page.getByText("Provider capability is unavailable", { exact: true }).first()).toBeVisible()

  await page.getByRole("link", { name: "Jobs", exact: true }).click()
  await page.getByLabel("Filter jobs by status").selectOption("attention")
  await expect(page).toHaveURL(/\/operations\?.*view=jobs.*status=attention|\/operations\?.*status=attention.*view=jobs/)
  await expect(page.getByText("Provider is temporarily unavailable", { exact: true }).first()).toBeVisible()

  await page.getByRole("button", { name: "View Generation Run job details" }).click()
  const failedDialog = page.getByRole("dialog", { name: "Job details" })
  await expect(failedDialog).toContainText("provider_unavailable")
  await expect(failedDialog).toContainText("Provider is temporarily unavailable")
  await expect(failedDialog).not.toContainText("Bearer secret-value")
  await expect(failedDialog).not.toContainText("raw provider response")
  page.once("dialog", (dialog) => dialog.accept())
  await failedDialog.getByRole("button", { name: "Retry job" }).click()
  await expect.poll(() => requests.filter((request) => request === `POST /jobs/${failedId}/retry`).length).toBe(1)
  await expect(page.getByText("Retry requested", { exact: true }).first()).toBeVisible()
  await failedDialog.getByRole("button", { name: "Close job details" }).click()
  await expect(failedDialog).toBeHidden()

  await page.getByLabel("Filter jobs by status").selectOption("queued")
  await page.getByRole("button", { name: "View Telegram Publish job details" }).click()
  const queuedDialog = page.getByRole("dialog", { name: "Job details" })
  await expect(queuedDialog.getByRole("button", { name: "Cancel job" })).toBeVisible()
  page.once("dialog", (dialog) => dialog.accept())
  await queuedDialog.getByRole("button", { name: "Cancel job" }).click()
  await expect.poll(() => requests.filter((request) => request === `POST /jobs/${queuedId}/cancel`).length).toBe(1)
  await expect(page.getByText("Job cancelled", { exact: true }).first()).toBeVisible()
  await queuedDialog.getByRole("button", { name: "Close job details" }).click()

  await page.getByRole("link", { name: "Diagnostics", exact: true }).click()
  await expect(page.getByRole("heading", { name: "System checks" })).toBeVisible()
  const checksBefore = requests.filter((request) => request === "GET /operations/health").length
  await page.getByRole("button", { name: "Run diagnostics" }).click()
  await expect.poll(() => requests.filter((request) => request === "GET /operations/health").length).toBeGreaterThan(checksBefore)
  await expect(page.getByText("Provider capability is unavailable", { exact: true })).toBeVisible()

  expect(requests.filter((request) => request.includes("/operations/health")).length).toBeGreaterThan(1)
})

test("legacy routes preserve state and Operations Center stays responsive in both themes", async ({ page }, testInfo) => {
  test.slow()
  await installOperationsBackend(page)

  await page.goto(`/jobs?status=attention&job=${failedId}`)
  await expect(page).toHaveURL(new RegExp(`/operations\\?.*view=jobs.*status=attention.*job=${failedId}|/operations\\?.*view=jobs.*job=${failedId}.*status=attention`))
  await expect(page.getByRole("dialog", { name: "Job details" })).toBeVisible()
  await page.getByRole("dialog", { name: "Job details" }).getByRole("button", { name: "Close job details" }).click()

  await page.goto("/diagnostics")
  await expect(page).toHaveURL(/\/operations\?view=diagnostics/)
  await expect(page.getByRole("heading", { name: "System checks" })).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/operations?view=jobs")
  await expect(page.getByRole("heading", { name: "Operations Center" })).toBeVisible()
  await expect(page.getByRole("list", { name: "Jobs" })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await page.getByRole("list", { name: "Jobs" }).getByRole("listitem").filter({ hasText: "failed" }).getByRole("button", { name: "View Generation Run job details" }).click()
  const dialog = page.getByRole("dialog", { name: "Job details" })
  await expect(dialog).toBeVisible()
  const bounds = await dialog.boundingBox()
  expect(bounds?.width ?? 1000).toBeLessThanOrEqual(390)
  await dialog.getByRole("button", { name: "Close job details" }).click()

  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((selectedTheme) => {
      document.documentElement.classList.toggle("dark", selectedTheme === "dark")
      window.localStorage.setItem("newscraft-theme", selectedTheme)
    }, theme)

    for (const viewport of [
      { width: 1440, height: 900, capture: true },
      { width: 1024, height: 768, capture: true },
      { width: 768, height: 900, capture: true },
      { width: 390, height: 844, capture: true },
      { width: 375, height: 667, capture: false },
      { width: 844, height: 390, capture: false },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto("/operations")
      await expect(page.getByRole("heading", { name: "Operations Center" })).toBeVisible()
      await expect(page.getByRole("region", { name: "Operational status summary" })).toContainText("Unavailable")
      await expect(page.getByText(/^Last successful refresh /)).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
      if (viewport.width < 900) {
        const undersized = await page.locator("main a, main button, main select").evaluateAll((nodes) => nodes
          .filter((node) => {
            const bounds = node.getBoundingClientRect()
            const style = getComputedStyle(node)
            return bounds.width > 0 && bounds.height > 0 && style.display !== "none" && style.visibility !== "hidden" && (bounds.width < 44 || bounds.height < 44)
          })
          .map((node) => ({ label: node.getAttribute("aria-label") ?? node.textContent?.trim(), bounds: node.getBoundingClientRect().toJSON() })))
        expect(undersized).toEqual([])
      }
      if (viewport.capture) await page.screenshot({ path: testInfo.outputPath(`operations-center-${theme}-${viewport.width}.png`), fullPage: true })
    }
  }
})

async function installOperationsBackend(page: Page) {
  const requests: string[] = []
  const jobs = [
    job({
      id: failedId,
      status: "failed",
      error_class: "retryable",
      error_code: "provider_unavailable",
      error_message: "Provider is temporarily unavailable",
    }),
    job({ id: queuedId, job_type: "telegram.publish", status: "queued" }),
    job({ id: "33333333-3333-4333-8333-333333333333", status: "running" }),
    job({ id: "44444444-4444-4444-8444-444444444444", status: "succeeded", finished_at: "2026-07-13T08:01:00Z", progress: 100 }),
  ]

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace("/api/backend", "")
    const method = request.method()
    requests.push(`${method} ${path}`)

    if (path === "/operator-settings/date-time") return json(route, { timezone: "Asia/Tehran", updated_at: "2026-07-13T08:00:00Z" })
    if (path === "/automation-control") return json(route, { global_pause: false, dry_run: false, pause_reason: null, paused_at: null, updated_at: "2026-07-13T08:00:00Z" })
    if (path === "/jobs/summary") return json(route, { queued: 1, running: 1, attention: 1, succeeded_today: 1 })
    if (path === "/jobs" && method === "GET") return json(route, { items: jobs })
    if (path === `/jobs/${failedId}` && method === "GET") return json(route, detail(jobs[0]))
    if (path === `/jobs/${queuedId}` && method === "GET") return json(route, detail(jobs[1]))
    if (path === `/jobs/${failedId}/retry` && method === "POST") return json(route, { ...jobs[0], status: "queued", error_class: null, error_code: null, error_message: null })
    if (path === `/jobs/${queuedId}/cancel` && method === "POST") return json(route, { ...jobs[1], status: "cancelled" })
    if (path === "/operations/diagnostics") return json(route, diagnosticsFixture())
    if (path === "/operations/health") return json(route, healthFixture())
    return route.fulfill({ status: 501, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled ${method} ${path}` }) })
  })
  return requests
}

function detail(value: ReturnType<typeof job>) {
  return {
    ...value,
    payload: { authorization: "Bearer secret-value" },
    result: { provider_response: "raw provider response" },
    events: [{ id: "55555555-5555-4555-8555-555555555555", event_type: value.status === "failed" ? "job.failed" : "job.queued", actor: "worker-internal", event_data: { raw: "hidden" }, created_at: value.updated_at }],
  }
}

function diagnosticsFixture() {
  return {
    generated_at: "2026-07-13T08:02:00Z",
    global_paused: false,
    dry_run: false,
    components: {},
    queue_counts: { queued: 1, running: 1, succeeded: 1, failed: 1, needs_review: 0, cancelled: 0 },
    attention: [{ id: failedId, severity: "error", kind: "job", title: "Provider capability is unavailable", occurred_at: "2026-07-13T08:01:00Z", action_url: `/jobs?status=attention&job=${failedId}` }],
    outbound_proxy: { mode: "direct", scheme: null, bypass_rule_count: 0, last_connectivity_status: "not_checked", configuration_error_code: null },
  }
}

function healthFixture() {
  return {
    generated_at: "2026-07-13T08:02:00Z",
    state: "unavailable",
    state_definitions: {},
    dependencies: {
      database: { state: "healthy", code: "database_connected", observed_at: "2026-07-13T08:02:00Z", latency_ms: 12, message: "Database connectivity is available", runbook_url: "/docs/operations/readiness-and-health" },
      "capability:generation": { state: "unavailable", code: "capability_unavailable", observed_at: "2026-07-13T08:02:00Z", latency_ms: 0, message: "Provider capability is unavailable", runbook_url: "/docs/operations/readiness-and-health" },
    },
    components: {
      "worker-source-generation": { component_id: "worker-source-generation", component_type: "worker", state: "healthy", code: "heartbeat_fresh", observed_at: "2026-07-13T08:01:55Z", last_success_at: "2026-07-13T08:01:55Z", heartbeat_age_seconds: 5, last_success_age_seconds: 5, capabilities: ["generation"], activity: "idle", active_work_type: null, active_work_age_seconds: null, process_started_at: "2026-07-13T07:00:00Z", restart_state: "stable", restart_count_window: 0, restart_window_seconds: 3600, last_restart_at: null, message: "Worker heartbeat is fresh", runbook_url: "/docs/operations/readiness-and-health" },
    },
    queues: [],
    recoveries: [],
    alerts: [{ code: "capability_unavailable", state: "unavailable", scope: "dependency:capability:generation", message: "Provider capability is unavailable", runbook_url: "/docs/operations/readiness-and-health" }],
    metrics: {},
    outbound_proxy: { mode: "direct", scheme: null, bypass_rule_count: 0, last_connectivity_status: "not_checked", configuration_error_code: null },
  }
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: failedId,
    job_type: "generation.run",
    status: "queued",
    origin: "manual",
    priority: 0,
    pause_sensitive: false,
    scheduled_for: "2026-07-13T08:00:00Z",
    attempt_count: 1,
    max_attempts: 3,
    progress: 30,
    progress_message: "Working",
    error_class: null,
    error_code: null,
    error_message: null,
    started_at: "2026-07-13T08:00:15Z",
    finished_at: null,
    created_at: "2026-07-13T08:00:00Z",
    updated_at: "2026-07-13T08:01:00Z",
    ...overrides,
  }
}

async function json(route: Route, body: unknown, status = 200) {
  await fulfillMockJson(route, body, status)
}

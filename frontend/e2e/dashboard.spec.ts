import { expect, test, type Page, type Route } from "@playwright/test"

import { fulfillMockJson } from "./support/mock-backend"

const failedJob = backendJob({
  id: "22222222-2222-4222-8222-222222222222",
  status: "failed",
  error_class: "retryable",
  error_code: "source_timeout",
  error_message: "Source request timed out",
  progress: 35,
  progress_message: "Waiting for source response",
})
const runningJob = backendJob({ status: "running", progress: 45, progress_message: "Fetching sources" })
const succeededJob = backendJob({
  id: "33333333-3333-4333-8333-333333333333",
  status: "succeeded",
  progress: 100,
  progress_message: "Complete",
  finished_at: "2026-07-12T08:02:00Z",
})

test.describe("NewsCraft command center", () => {
  test("desktop Today and mobile Operations Center use fixed live workflow truth", async ({ page }) => {
    const unhandledRequests = await installApiRoutes(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto("/")

    await expect(page.getByRole("heading", { name: "Today" })).toBeVisible()
    await expect(page.getByText("Automation paused")).toBeVisible()
    await expect(page.getByRole("button", { name: "Resume automations" })).toBeVisible()
    await expect(page.locator("[data-summary=queued]")).toHaveText("3")
    await expect(page.locator("[data-summary=running]")).toHaveText("1")
    await expect(page.locator("[data-summary=attention]")).toHaveText("1")
    await expect(page.locator("[data-summary=succeeded]")).toHaveText("4")
    const priority = page.getByRole("region", { name: "Highest-priority decision" })
    await expect(priority.getByText("Resolve failed workflow", { exact: true })).toBeVisible()
    await expect(priority.getByRole("link", { name: "Inspect and retry" })).toBeVisible()

    const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    expect(hasHorizontalOverflow).toBe(false)

    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto("/")

    const navigation = page.getByRole("navigation", { name: "Mobile newsroom navigation" })
    await expect(navigation).toBeVisible()
    await navigation.getByRole("button", { name: "Open navigation" }).click()
    const operationsLink = page.getByRole("dialog", { name: "Newsroom navigation" }).getByRole("link", { name: "Operations Center" })
    await expect(operationsLink).toHaveAttribute("href", "/operations")
    await page.goto("/operations")
    await expect(page.getByRole("heading", { name: "Operations Center" })).toBeVisible()

    await page.getByRole("button", { name: "View Ingest Collect job details" }).first().click()
    const detail = page.getByRole("dialog", { name: "Job details" })
    await expect(detail).toBeVisible()
    await expect(detail.getByRole("button", { name: "Retry job" })).toBeVisible()
    expect(unhandledRequests).toEqual([])
  })
})

async function installApiRoutes(page: Page) {
  const unhandledRequests: string[] = []
  await page.route("**/api/backend/automation-control", async (route) => {
    await fulfillJson(route, {
      global_pause: true,
      dry_run: false,
      pause_reason: "Paused for deterministic verification",
      paused_at: "2026-07-12T08:00:00Z",
      updated_at: "2026-07-12T08:00:00Z",
    })
  })
  await page.route("**/api/backend/jobs**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace("/api/backend", "")
    if (path === "/jobs/summary") {
      await fulfillJson(route, { queued: 3, running: 1, attention: 1, succeeded_today: 4 })
      return
    }
    if (path === `/jobs/${failedJob.id}`) {
      await fulfillJson(route, {
        ...failedJob,
        payload: { source_ids: ["source-1"], authorization: "[REDACTED]" },
        result: {},
        events: [
          {
            id: "44444444-4444-4444-8444-444444444444",
            event_type: "job.failed",
            actor: "worker-1",
            event_data: { error_code: "source_timeout" },
            created_at: "2026-07-12T08:02:00Z",
          },
        ],
      })
      return
    }
    if (path.startsWith("/jobs/") && route.request().method() === "POST") {
      await fulfillJson(route, { ...failedJob, status: "queued", error_class: null, error_code: null, error_message: null })
      return
    }
    if (path !== "/jobs") {
      const requestLabel = `${route.request().method()} ${path}${url.search}`
      unhandledRequests.push(requestLabel)
      await route.fulfill({
        status: 501,
        contentType: "application/json",
        body: JSON.stringify({ detail: `Unhandled deterministic test request: ${requestLabel}` }),
      })
      return
    }

    const statuses = url.searchParams.getAll("status")
    const items = statuses.includes("running")
      ? [runningJob]
      : statuses.includes("failed") || statuses.includes("needs_review")
        ? [failedJob]
        : statuses.includes("succeeded")
          ? [succeededJob]
          : [failedJob, runningJob, succeededJob]
    await fulfillJson(route, { items })
  })
  await page.route("**/api/backend/operations/diagnostics", async (route) => {
    await fulfillJson(route, {
      generated_at: "2026-07-12T08:03:00Z",
      global_paused: true,
      dry_run: false,
      components: {},
      queue_counts: { queued: 3, running: 1, failed: 1, needs_review: 0, succeeded: 4, cancelled: 0 },
      attention: [],
      outbound_proxy: { mode: "direct", scheme: null, bypass_rule_count: 0, last_connectivity_status: "not_checked", configuration_error_code: null },
    })
  })
  await page.route("**/api/backend/operations/health", async (route) => {
    await fulfillJson(route, {
      generated_at: "2026-07-12T08:03:00Z",
      state: "healthy",
      state_definitions: {},
      dependencies: {},
      components: {},
      queues: [],
      recoveries: [],
      alerts: [],
      metrics: {},
      outbound_proxy: { mode: "direct", scheme: null, bypass_rule_count: 0, last_connectivity_status: "not_checked", configuration_error_code: null },
    })
  })
  return unhandledRequests
}

async function fulfillJson(route: Route, body: unknown) {
  await fulfillMockJson(route, body)
}

function backendJob(overrides: Record<string, unknown> = {}) {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    job_type: "ingest.collect",
    status: "queued",
    origin: "manual",
    priority: 0,
    pause_sensitive: false,
    scheduled_for: "2026-07-12T08:00:00Z",
    attempt_count: 1,
    max_attempts: 3,
    progress: 0,
    progress_message: null,
    error_class: null,
    error_code: null,
    error_message: null,
    started_at: null,
    finished_at: null,
    created_at: "2026-07-12T08:00:00Z",
    updated_at: "2026-07-12T08:00:00Z",
    ...overrides,
  }
}

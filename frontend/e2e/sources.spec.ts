import AxeBuilder from "@axe-core/playwright"
import { expect, test } from "@playwright/test"

import { fulfillMockJson, installMockBackend } from "./support/mock-backend"
import type { components } from "../lib/api/generated"

type SourceRecord = components["schemas"]["SourceOut"]

const sources = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    platform: "rss",
    name: "TechCrunch",
    source_group: "technology",
    active: true,
    feed_url: "https://techcrunch.com/feed/",
    homepage_url: "https://techcrunch.com",
    telegram_username: null,
    language_hint: "en",
    fetch_interval_minutes: 30,
    health_status: "healthy",
    last_fetch_at: "2026-07-27T08:00:00Z",
    last_success_at: "2026-07-27T08:00:00Z",
    last_failure_at: null,
    failure_count: 0,
    last_parse_count: 128,
    last_suitable_count: 42,
    last_media_count: 76,
    created_at: "2026-07-20T08:00:00Z",
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    platform: "telegram_public",
    name: "DW Persian",
    source_group: "world",
    active: true,
    feed_url: null,
    homepage_url: null,
    telegram_username: "dw_farsi",
    language_hint: "fa",
    fetch_interval_minutes: 30,
    health_status: "degraded",
    last_fetch_at: "2026-07-27T07:45:00Z",
    last_success_at: "2026-07-27T07:45:00Z",
    last_failure_at: "2026-07-27T07:30:00Z",
    failure_count: 2,
    last_parse_count: 67,
    last_suitable_count: 18,
    last_media_count: 44,
    created_at: "2026-07-21T08:00:00Z",
  },
] satisfies SourceRecord[]

test("Sources tabs stay responsive and filter rows", async ({ page }) => {
  const pageErrors: Error[] = []
  page.on("pageerror", (error) => pageErrors.push(error))
  const unhandledRequests = await installMockBackend(page)
  await installSourcesApi(page, sources)
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto("/sources")

  await expect(page.getByRole("button", { name: "Run ingest" })).toHaveCount(0)
  await expect(page.getByRole("columnheader", { name: /news|new/i })).toHaveCount(0)
  await page.getByRole("tab", { name: /rss 1/i }).click()
  await expect(page.getByRole("row", { name: /techcrunch/i })).toBeVisible()
  await expect(page.getByRole("row", { name: /dw persian/i })).toHaveCount(0)

  await page.getByRole("tab", { name: /telegram 1/i }).click()
  await expect(page.getByRole("row", { name: /dw persian/i })).toBeVisible()
  await expect(page.getByRole("row", { name: /techcrunch/i })).toHaveCount(0)

  await page.getByRole("tab", { name: /all 2/i }).click()
  await page.getByRole("button", { name: "Add source" }).click()
  const addDialog = page.getByRole("dialog", { name: "Add source" })
  await addDialog.getByLabel("Name").fill("Example Wire")
  await addDialog.getByLabel("Feed URL").fill("https://example.com/feed.xml")
  await addDialog.getByRole("button", { name: "Add source" }).click()
  await expect(page.getByRole("row", { name: /example wire/i })).toBeVisible()
  await page.reload()
  await expect(page.getByRole("row", { name: /example wire/i })).toBeVisible()

  await page.getByRole("button", { name: "Delete Example Wire" }).click()
  const deleteDialog = page.getByRole("dialog", { name: "Delete source?" })
  await deleteDialog.getByRole("button", { name: "Delete source" }).click()
  await expect(page.getByRole("row", { name: /example wire/i })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole("row", { name: /example wire/i })).toHaveCount(0)

  await expect(page.getByRole("button", { name: /open techcrunch details/i })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /show techcrunch source details/i })).toHaveCount(0)

  const sourceRow = page.getByRole("row", { name: /dw persian/i })
  await sourceRow.click()
  await expect(page.getByRole("region", { name: /source details/i })).toHaveCount(0)
  await sourceRow.dblclick()
  await expect(page.getByRole("region", { name: /source details/i })).toBeVisible()
  await expect(page.getByRole("heading", { name: "DW Persian" })).toBeVisible()
  await page.getByRole("button", { name: /close source details/i }).click()
  await expect(page.getByRole("region", { name: /source details/i })).toHaveCount(0)

  const healthAction = page.getByRole("button", { name: /check techcrunch health, currently healthy/i })
  await healthAction.dispatchEvent("dblclick", { detail: 2 })
  await expect(page.getByRole("region", { name: /source details/i })).toHaveCount(0)
  await healthAction.click()
  await expect(page.getByText(/last checked/i).first()).toBeVisible()
  const healthNotice = page.locator('[data-slot="alert"]').filter({ hasText: "Health check complete" })
  await expect(healthNotice).toContainText("Source is healthy.")
  const healthNoticeBox = await healthNotice.boundingBox()
  expect(healthNoticeBox).not.toBeNull()
  expect(healthNoticeBox!.width).toBeLessThan(320)

  const tableFits = await page.locator('[data-slot="table-container"]').evaluate(
    (element) => element.scrollWidth <= element.clientWidth,
  )
  expect(tableFits).toBe(true)
  await expectNoSeriousAxeViolations(page)
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await expectNoSeriousAxeViolations(page)
  expect(unhandledRequests).toEqual([])
  expect(pageErrors).toEqual([])
})

test("Sources management stays inside narrow portrait and landscape viewports", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)
  await installSourcesApi(page, sources)
  await page.emulateMedia({ reducedMotion: "reduce" })

  for (const viewport of [
    { width: 375, height: 812 },
    { width: 844, height: 390 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto("/sources")
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "20px"
    })
    await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible()
    const pageFits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    expect(pageFits).toBe(true)

    await page.getByRole("button", { name: /check techcrunch health, currently healthy/i }).click()
    const healthNotice = page.locator('[data-slot="alert"]').filter({ hasText: "Health check complete" })
    await expect(healthNotice).toContainText("Source is healthy.")
    const healthNoticeBox = await healthNotice.boundingBox()
    expect(healthNoticeBox).not.toBeNull()
    expect(healthNoticeBox!.x).toBeGreaterThanOrEqual(16)
    expect(healthNoticeBox!.width).toBeLessThan(320)

    await page.getByRole("button", { name: "Add source" }).click()
    await expect(page.getByRole("dialog", { name: "Add source" })).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(page.getByRole("dialog", { name: "Add source" })).toHaveCount(0)
  }
  expect(unhandledRequests).toEqual([])
})

async function installSourcesApi(
  page: import("@playwright/test").Page,
  initialSources: SourceRecord[],
) {
  let records = initialSources.map((source) => ({ ...source }))
  let createdCount = 0

  await page.route("**/api/backend/sources/*/health-check", async (route) => {
    const parts = new URL(route.request().url()).pathname.split("/")
    const sourceId = decodeURIComponent(parts.at(-2) ?? "")
    const checkedAt = "2026-07-27T08:30:00Z"
    records = records.map((source) => source.id === sourceId ? {
      ...source,
      health_status: "healthy",
      last_fetch_at: checkedAt,
      last_error_message: null,
    } : source)
    await fulfillMockJson(route, {
      source_id: sourceId,
      health_status: "healthy",
      is_checking: false,
      last_checked_at: checkedAt,
      failure_reason: null,
    })
  })

  await page.route("**/api/backend/sources/*", async (route) => {
    const sourceId = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-1) ?? "")
    const source = records.find((item) => item.id === sourceId)
    if (route.request().method() === "DELETE") {
      records = records.filter((item) => item.id !== sourceId)
      await route.fulfill({ status: 204, body: "" })
      return
    }
    await fulfillMockJson(route, source ?? records[0])
  })

  await page.route("**/api/backend/sources", async (route) => {
    if (route.request().method() === "POST") {
      const input = route.request().postDataJSON() as {
        platform: "rss" | "telegram_public"
        name: string
        url: string
        source_group: string
        language_hint: string
        fetch_interval_minutes: number
      }
      createdCount += 1
      const created: SourceRecord = {
        id: `33333333-3333-4333-8333-${String(createdCount).padStart(12, "0")}`,
        platform: input.platform,
        name: input.name,
        source_group: input.source_group,
        active: true,
        feed_url: input.platform === "rss" ? input.url : null,
        homepage_url: null,
        telegram_username: input.platform === "telegram_public" ? input.url.split("/").at(-1) ?? null : null,
        language_hint: input.language_hint,
        fetch_interval_minutes: input.fetch_interval_minutes,
        health_status: "unknown",
        last_fetch_at: null,
        last_success_at: null,
        last_failure_at: null,
        failure_count: 0,
        last_parse_count: 0,
        last_suitable_count: 0,
        last_media_count: 0,
        created_at: "2026-07-27T08:15:00Z",
      }
      records = [created, ...records]
      await fulfillMockJson(route, created, 201)
      return
    }
    await fulfillMockJson(route, records)
  })
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

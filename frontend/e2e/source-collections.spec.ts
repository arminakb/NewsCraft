import { expect, test } from "@playwright/test"

import { fulfillMockJson, installMockBackend } from "./support/mock-backend"
import type { components } from "../lib/api/generated"

type SourceRecord = components["schemas"]["SourceOut"]

const sources: SourceRecord[] = [
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
    icon_status: "pending",
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
    health_status: "healthy",
    icon_status: "pending",
    last_fetch_at: "2026-07-27T08:00:00Z",
    last_success_at: "2026-07-27T08:00:00Z",
    last_failure_at: null,
    failure_count: 0,
    last_parse_count: 67,
    last_suitable_count: 18,
    last_media_count: 44,
    created_at: "2026-07-21T08:00:00Z",
  },
]

const collectionId = "44444444-4444-4444-8444-444444444444"
const runId = "55555555-5555-4555-8555-555555555555"
const jobId = "66666666-6666-4666-8666-666666666666"

test("operators can manage one Source Collection and start scoped ingestion", async ({ page }) => {
  await installMockBackend(page)
  await page.route("**/api/backend/sources/search**", async (route) => {
    const url = new URL(route.request().url())
    const requestedLimit = Number(url.searchParams.get("limit") ?? "50")
    const limit = Number.isInteger(requestedLimit) ? Math.min(Math.max(requestedLimit, 1), 100) : 50
    const requestedOffset = Number(url.searchParams.get("offset") ?? "0")
    const offset = Number.isInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0
    await fulfillMockJson(route, {
      items: sources.slice(offset, offset + limit),
      total: sources.length,
      limit,
      offset,
      has_more: offset + limit < sources.length,
    })
  })
  await page.route("**/api/backend/source-collections/unassigned/sources**", async (route) => {
    const url = new URL(route.request().url())
    const limit = Number(url.searchParams.get("limit") ?? "50")
    await fulfillMockJson(route, {
      items: sources.slice(0, limit),
      total: sources.length,
      limit,
      offset: 0,
      has_more: false,
    })
  })

  let memberIds = [sources[0].id]
  let activeRun = false
  const collection = () => ({
    id: collectionId,
    name: "Morning News",
    description: "Editorial morning run",
    source_count: memberIds.length,
    maximum_sources: 100,
    created_at: "2026-08-06T08:00:00Z",
    updated_at: "2026-08-06T08:00:00Z",
    active_ingest_run_id: activeRun ? runId : null,
    active_ingest_status: activeRun ? "running" : null,
    active_ingest_source_count: activeRun ? memberIds.length : null,
    active_ingest_processed_count: activeRun ? memberIds.length : null,
    active_ingest_success_count: activeRun ? memberIds.length : null,
    active_ingest_failure_count: activeRun ? 0 : null,
  })

  await page.route("**/api/backend/source-collections**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^\/api\/backend/, "")
    const method = route.request().method()
    if (method === "GET" && path === "/source-collections") {
      await fulfillMockJson(route, [collection()])
      return
    }
    if (method === "GET" && path === `/source-collections/${collectionId}/sources`) {
      const members = sources.filter((source) => memberIds.includes(source.id))
      await fulfillMockJson(route, {
        items: members,
        total: members.length,
        limit: Number(url.searchParams.get("limit") ?? "25"),
        offset: Number(url.searchParams.get("offset") ?? "0"),
        has_more: false,
      })
      return
    }
    if (method === "POST" && path === `/source-collections/${collectionId}/sources`) {
      const body = route.request().postDataJSON() as { source_ids: string[] }
      memberIds = [...new Set([...memberIds, ...body.source_ids])]
      await fulfillMockJson(route, {
        collection_id: collectionId,
        added_source_ids: body.source_ids,
        removed_source_ids: [],
        already_member_source_ids: [],
        missing_source_ids: [],
        source_count: memberIds.length,
        maximum_sources: 100,
      })
      return
    }
    if (method === "POST" && path === `/source-collections/${collectionId}/ingest`) {
      activeRun = true
      await fulfillMockJson(route, {
        job_id: jobId,
        run_id: runId,
        source_collection_id: collectionId,
        source_collection_name: "Morning News",
        source_count: memberIds.length,
        status: "queued",
        deduplicated: false,
      }, 202)
      return
    }
    if (method === "GET" && path === `/source-collections/${collectionId}/runs/${runId}`) {
      await fulfillMockJson(route, {
        id: runId,
        source_collection_id: collectionId,
        source_collection_name_at_start: "Morning News",
        source_count: memberIds.length,
        processed_count: memberIds.length,
        success_count: memberIds.length,
        failure_count: 0,
        started_at: "2026-08-06T08:05:00Z",
        completed_at: "2026-08-06T08:06:00Z",
        status: "succeeded",
        trigger: "source_collection_manual",
        stats: { checked: memberIds.length, failed: 0 },
        error: null,
        sources: [],
      })
      return
    }
    await route.fallback()
  })

  await page.goto("/sources")
  await page.getByRole("button", { name: /Morning News/ }).click()
  await page.getByRole("button", { name: "Manage sources" }).click()

  const manager = page.getByRole("dialog", { name: /Manage sources/ })
  await expect(manager).toBeVisible()
  await manager.getByRole("checkbox", { name: "Select DW Persian" }).check()
  await manager.getByRole("button", { name: /Add selected \(1\)/ }).click()
  await expect(manager.getByText(/Changes are applied immediately/)).toBeVisible()
  await manager.getByRole("button", { name: "Done" }).click()

  await page.getByRole("button", { name: "Start ingestion" }).click()
  const ingestDialog = page.getByRole("dialog", { name: "Start ingestion" })
  await expect(ingestDialog.getByRole("button", { name: "Start ingestion" })).toBeDisabled()
  await ingestDialog.getByLabel("Source Collection").selectOption(collectionId)
  await expect(ingestDialog.getByRole("button", { name: "Start ingestion" })).toBeEnabled()
  await ingestDialog.getByRole("button", { name: "Start ingestion" }).click()

  await expect(page.getByText("Ingestion progress", { exact: true })).toBeVisible()
  await expect(page.getByText(/2 of 2 sources/)).toBeVisible()
})

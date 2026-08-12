import { expect, test } from "@playwright/test"

import { fulfillMockJson, installMockBackend } from "./support/mock-backend"
import type { components } from "../lib/api/generated"

type SourceRecord = components["schemas"]["SourceOut"]
type SourceCollectionRecord = components["schemas"]["SourceCollectionOut"]

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
  const sourceQueries: string[] = []
  await page.route("**/api/backend/sources/search**", async (route) => {
    const url = new URL(route.request().url())
    sourceQueries.push(url.search)
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
  const historyRequests: Array<{ limit: number; offset: number }> = []
  const historyRuns = Array.from({ length: 101 }, (_, index) => ({
    id: `00000000-0000-4000-8000-${String(101 - index).padStart(12, "0")}`,
    source_collection_id: collectionId,
    source_collection_name_at_start: "Morning News",
    source_count: 10,
    processed_count: 10,
    success_count: index === 2 ? 0 : 7,
    failure_count: index === 2 ? 10 : 3,
    skipped_count: 0,
    started_at: new Date(Date.UTC(2026, 7, 12, 10, 0) - index * 60_000).toISOString(),
    completed_at: new Date(Date.UTC(2026, 7, 12, 10, 1) - index * 60_000).toISOString(),
    status: index === 2 ? "failed" : "partial",
    trigger: index % 2 ? "source_collection_manual" : "source_collection_continuous",
    mode: index % 2 ? "once" : "continuous",
    continuous_subscription_id: index % 2 ? null : "77777777-7777-4777-8777-777777777777",
    continuous_cycle_number: index % 2 ? null : 101 - index,
    stats: {},
    error: null,
    sources: [],
  }))
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
    if (method === "GET" && path === `/source-collections/${collectionId}/runs`) {
      const limit = Number(url.searchParams.get("limit") ?? "25")
      const offset = Number(url.searchParams.get("offset") ?? "0")
      historyRequests.push({ limit, offset })
      await fulfillMockJson(route, {
        items: historyRuns.slice(offset, offset + limit),
        total: historyRuns.length,
        limit,
        offset,
        has_more: offset + limit < historyRuns.length,
      })
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

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/sources?view=compact")
  const collectionNavigation = page.getByRole("complementary", { name: "Source Collections" })
  await expect(collectionNavigation).toBeVisible()
  await expect(collectionNavigation.getByRole("button", { name: /All Sources/ })).toHaveAttribute("aria-current", "page")
  await expect(collectionNavigation.getByRole("button", { name: "Manage Morning News" })).toHaveCount(0)
  const morningNewsRow = collectionNavigation.getByRole("button", { name: /^Morning News / })
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((selectedTheme) => {
      window.localStorage.setItem("newscraft-theme", selectedTheme)
      document.documentElement.dataset.theme = selectedTheme
      document.documentElement.classList.toggle("dark", selectedTheme === "dark")
    }, theme)
    await morningNewsRow.click({ button: "right" })
    const themedMenu = page.getByRole("menu", { name: "Manage Morning News" })
    await expect(themedMenu).toBeVisible()
    expect(await themedMenu.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)")
    await page.keyboard.press("Escape")
  }
  await collectionNavigation.getByRole("button", { name: /^Morning News / }).click()
  await expect(page).toHaveURL(`/sources?view=compact&source_collection_id=${collectionId}`)
  await expect(collectionNavigation.getByRole("button", { name: /^Morning News / })).toHaveAttribute("aria-current", "page")
  await expect.poll(() => sourceQueries.some((query) => query.includes(`collection_id=${collectionId}`))).toBe(true)
  await collectionNavigation.getByRole("button", { name: /Unassigned/ }).click()
  await expect(page).toHaveURL("/sources?view=compact&unassigned=true")
  await expect(collectionNavigation.getByRole("button", { name: /Unassigned/ })).toHaveAttribute("aria-current", "page")
  await page.goBack()
  await expect(page).toHaveURL(`/sources?view=compact&source_collection_id=${collectionId}`)
  await expect(collectionNavigation.getByRole("button", { name: /^Morning News / })).toHaveAttribute("aria-current", "page")
  expect(await collectionNavigation.evaluate((element) => {
    const style = getComputedStyle(element)
    return { position: style.position, overflowY: style.overflowY }
  })).toEqual({ position: "sticky", overflowY: "auto" })

  const recentHistory = page.getByRole("region", { name: "Recent ingestion history" })
  await expect(recentHistory.getByRole("listitem")).toHaveCount(3)
  await expect(recentHistory.getByText("Continuous · Cycle #101")).toBeVisible()
  await expect(recentHistory.getByText("7 succeeded").first()).toBeVisible()
  await expect(recentHistory.getByText("10 failed")).toBeVisible()
  expect(historyRequests[0]).toEqual({ limit: 3, offset: 0 })

  await recentHistory.getByRole("button", { name: "View history" }).click()
  const historyDialog = page.getByRole("dialog", { name: "Ingestion history · Morning News" })
  await expect(historyDialog.getByRole("listitem")).toHaveCount(25)
  expect(historyRequests).toContainEqual({ limit: 25, offset: 0 })
  await historyDialog.getByRole("button", { name: "Next" }).click()
  await expect(historyDialog.getByText("26–50 of 101 runs")).toBeVisible()
  await expect(historyDialog.getByRole("listitem")).toHaveCount(25)
  expect(historyRequests).toContainEqual({ limit: 25, offset: 25 })
  await historyDialog.getByRole("button", { name: "Close" }).click()
  await expect(historyDialog).not.toBeVisible()
  await expect(recentHistory.getByRole("listitem")).toHaveCount(3)

  await morningNewsRow.click({ button: "right" })
  await page.getByRole("menu", { name: "Manage Morning News" }).getByRole("menuitem", { name: "Manage sources" }).click()

  const manager = page.getByRole("dialog", { name: /Manage sources/ })
  await expect(manager).toBeVisible()
  await manager.getByRole("checkbox", { name: "Select DW Persian" }).check()
  await manager.getByRole("button", { name: /Add selected \(1\)/ }).click()
  await expect(manager.getByText(/Changes are applied immediately/)).toBeVisible()
  await manager.getByRole("button", { name: "Done" }).click()

  await expect(page.getByRole("button", { name: "Start ingestion" })).toHaveCount(1)
  const sourceHealthControls = page.getByRole("button", { name: "Check all source health" }).locator("..")
  await expect(sourceHealthControls.getByRole("button", { name: "Start ingestion" })).toBeVisible()
  await sourceHealthControls.getByRole("button", { name: "Start ingestion" }).click()
  const ingestDialog = page.getByRole("dialog", { name: "Start ingestion" })
  await expect(ingestDialog.getByRole("button", { name: "Start ingestion" })).toBeDisabled()
  await ingestDialog.getByLabel("Source Collection").selectOption(collectionId)
  await expect(ingestDialog.getByRole("button", { name: "Start ingestion" })).toBeEnabled()
  await ingestDialog.getByRole("button", { name: "Start ingestion" }).click()

  await expect(page.getByText("Ingestion progress", { exact: true })).toBeVisible()
  await expect(page.getByText(/2 of 2 sources/)).toBeVisible()
})

test("Source Collection navigation stays bounded with dozens of collections", async ({ page }) => {
  await installMockBackend(page)
  let collections: SourceCollectionRecord[] = Array.from({ length: 48 }, (_, index) => ({
    id: `88888888-8888-4888-8888-${String(index + 1).padStart(12, "0")}`,
    name: `Desk ${String(index + 1).padStart(2, "0")}`,
    description: `Editorial desk ${index + 1}`,
    source_count: index % 11,
    maximum_sources: 100,
    created_at: "2026-08-06T08:00:00Z",
    updated_at: "2026-08-06T08:00:00Z",
    active_ingest_run_id: null,
    active_ingest_status: null,
    active_ingest_source_count: null,
    active_ingest_processed_count: null,
    active_ingest_success_count: null,
    active_ingest_failure_count: null,
  }))
  await page.route("**/api/backend/source-collections**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^\/api\/backend/, "")
    if (route.request().method() === "GET" && path === "/source-collections") {
      await fulfillMockJson(route, collections)
      return
    }
    if (route.request().method() === "POST" && path === "/source-collections") {
      const body = route.request().postDataJSON() as { name: string; description: string | null }
      const created = {
        ...collections[0],
        id: "99999999-9999-4999-8999-999999999999",
        name: body.name,
        description: body.description,
        source_count: 0,
      }
      collections = [created, ...collections]
      await fulfillMockJson(route, created, 201)
      return
    }
    const collectionPath = path.match(/^\/source-collections\/([^/]+)$/)
    if (route.request().method() === "PATCH" && collectionPath) {
      const body = route.request().postDataJSON() as { name?: string; description?: string | null }
      const collection = collections.find((item) => item.id === collectionPath[1])!
      Object.assign(collection, body)
      await fulfillMockJson(route, collection)
      return
    }
    if (route.request().method() === "DELETE" && collectionPath) {
      collections = collections.filter((item) => item.id !== collectionPath[1])
      await route.fulfill({ status: 204, body: "" })
      return
    }
    if (route.request().method() === "GET" && /\/source-collections\/[^/]+\/runs$/.test(path)) {
      await fulfillMockJson(route, { items: [], total: 0, limit: 3, offset: 0, has_more: false })
      return
    }
    await route.fallback()
  })
  await page.route("**/api/backend/source-collections/unassigned/sources**", async (route) => {
    await fulfillMockJson(route, { items: [], total: 0, limit: 1, offset: 0, has_more: false })
  })
  await page.route("**/api/backend/sources/search**", async (route) => {
    const url = new URL(route.request().url())
    const limit = Number(url.searchParams.get("limit") ?? "50")
    await fulfillMockJson(route, { items: [], total: 0, limit, offset: 0, has_more: false })
  })

  await page.setViewportSize({ width: 1440, height: 800 })
  await page.goto("/sources")
  const navigation = page.getByRole("complementary", { name: "Source Collections" })
  await expect(navigation.getByRole("button", { name: /^Desk 48 / })).toBeAttached()
  expect(await navigation.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }))).toEqual(expect.objectContaining({ clientHeight: expect.any(Number), scrollHeight: expect.any(Number) }))
  expect(await navigation.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true)
  const bounds = await navigation.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.height).toBeLessThanOrEqual(768)
  await navigation.getByRole("button", { name: /^Desk 48 / }).scrollIntoViewIfNeeded()
  await navigation.getByRole("button", { name: /^Desk 48 / }).click()
  await expect(page).toHaveURL(new RegExp(`source_collection_id=${collections.at(-1)!.id}`))
  await expect(navigation.getByRole("button", { name: /^Desk 48 / })).toHaveAttribute("aria-current", "page")

  await page.setViewportSize({ width: 375, height: 812 })
  await expect(navigation.getByRole("button", { name: /All Sources/ })).toBeAttached()
  expect(await navigation.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

  await page.setViewportSize({ width: 812, height: 375 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

  await navigation.getByRole("button", { name: "Create new Source Collection" }).click()
  const createDialog = page.getByRole("dialog", { name: "New Source Collection" })
  await createDialog.getByLabel("Name").fill("Visual Desk")
  await createDialog.getByLabel("Description").fill("Created from the compact collection rail")
  await createDialog.getByRole("button", { name: "Create collection" }).click()
  await expect(page).toHaveURL(/source_collection_id=99999999-9999-4999-8999-999999999999/)
  await expect(navigation.getByRole("button", { name: /^Visual Desk / })).toHaveAttribute("aria-current", "page")

  const visualDeskRow = navigation.getByRole("button", { name: /^Visual Desk / })
  await visualDeskRow.click({ button: "right" })
  let contextMenu = page.getByRole("menu", { name: "Manage Visual Desk" })
  await expect(contextMenu.getByRole("menuitem", { name: "Rename" })).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(contextMenu).toBeHidden()
  await expect(visualDeskRow).toBeFocused()

  await page.keyboard.press("Shift+F10")
  contextMenu = page.getByRole("menu", { name: "Manage Visual Desk" })
  await contextMenu.getByRole("menuitem", { name: "Rename" }).click()
  const renameDialog = page.getByRole("dialog", { name: "Edit Source Collection" })
  await expect(renameDialog.getByLabel("Name")).toBeFocused()
  await renameDialog.getByRole("button", { name: "Cancel" }).click()
  await expect(visualDeskRow).toBeFocused()

  await page.keyboard.press("ContextMenu")
  contextMenu = page.getByRole("menu", { name: "Manage Visual Desk" })
  await page.getByRole("heading", { name: "Sources" }).click()
  await expect(contextMenu).toBeHidden()
  await expect(navigation.getByRole("button", { name: /All Sources/ })).not.toHaveAttribute("aria-current")
  await expect(visualDeskRow).toHaveAttribute("aria-current", "page")

  await visualDeskRow.click({ button: "right" })
  await page.getByRole("menuitem", { name: "Edit details" }).click()
  const editDialog = page.getByRole("dialog", { name: "Edit Source Collection" })
  await editDialog.getByLabel("Name").fill("Visual Desk Updated")
  await editDialog.getByRole("button", { name: "Save changes" }).click()
  await expect(navigation.getByRole("button", { name: /^Visual Desk Updated / })).toBeVisible()

  const updatedRow = navigation.getByRole("button", { name: /^Visual Desk Updated / })
  await updatedRow.click({ button: "right" })
  await page.getByRole("menuitem", { name: "Delete" }).click()
  const deleteDialog = page.getByRole("dialog", { name: "Delete Source Collection?" })
  await deleteDialog.getByRole("button", { name: "Cancel" }).click()
  await expect(updatedRow).toBeVisible()
  await updatedRow.click({ button: "right" })
  await page.getByRole("menuitem", { name: "Delete" }).click()
  await deleteDialog.getByRole("button", { name: "Delete collection" }).click()
  await expect(navigation.getByRole("button", { name: /^Visual Desk Updated / })).toHaveCount(0)
  await expect(navigation.getByRole("button", { name: /All Sources/ })).toHaveAttribute("aria-current", "page")
})

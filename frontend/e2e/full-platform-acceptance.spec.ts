import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Locator, type Page, type Route } from "@playwright/test"

import { fulfillMockJson } from "./support/mock-backend"

type Platform = "telegram" | "instagram" | "x" | "blog"

const platforms = ["telegram", "instagram", "x", "blog"] as const
const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
] as const

const ids = {
  story: "30000000-0000-4000-8000-000000000001",
  storyRevision: "30000000-0000-4000-8000-000000000002",
  evidence: "30000000-0000-4000-8000-000000000003",
  contentPack: "30000000-0000-4000-8000-000000000004",
  brand: "30000000-0000-4000-8000-000000000005",
  provider: "30000000-0000-4000-8000-000000000006",
  source: "30000000-0000-4000-8000-000000000007",
  destination: "30000000-0000-4000-8000-000000000008",
  route: "30000000-0000-4000-8000-000000000009",
  canonicalTemplate: "30000000-0000-4000-8000-000000000010",
  telegramTemplate: "30000000-0000-4000-8000-000000000011",
  canonicalPrompt: "30000000-0000-4000-8000-000000000012",
  telegramPrompt: "30000000-0000-4000-8000-000000000013",
  intakeJob: "30000000-0000-4000-8000-000000000014",
  researchJob: "30000000-0000-4000-8000-000000000015",
  researchRun: "30000000-0000-4000-8000-000000000016",
  deepResearchRun: "30000000-0000-4000-8000-000000000017",
  routeJob: "30000000-0000-4000-8000-000000000018",
  failedJob: "30000000-0000-4000-8000-000000000019",
  failedJobEvent: "30000000-0000-4000-8000-000000000020",
  exportJob: "30000000-0000-4000-8000-000000000021",
  manualPlan: "30000000-0000-4000-8000-000000000022",
  publishJob: "30000000-0000-4000-8000-000000000023",
  publication: "30000000-0000-4000-8000-000000000024",
  workflowJob: "30000000-0000-4000-8000-000000000025",
  variants: {
    telegram: "31000000-0000-4000-8000-000000000001",
    instagram: "31000000-0000-4000-8000-000000000002",
    x: "31000000-0000-4000-8000-000000000003",
    blog: "31000000-0000-4000-8000-000000000004",
  },
  revisions: {
    telegram: "32000000-0000-4000-8000-000000000001",
    instagram: "32000000-0000-4000-8000-000000000002",
    x: "32000000-0000-4000-8000-000000000003",
    blog: "32000000-0000-4000-8000-000000000004",
  },
  childRevision: "32000000-0000-4000-8000-000000000005",
  attempts: {
    telegram: "33000000-0000-4000-8000-000000000001",
    instagram: "33000000-0000-4000-8000-000000000002",
    x: "33000000-0000-4000-8000-000000000003",
    blog: "33000000-0000-4000-8000-000000000004",
  },
  prompts: {
    telegram: "34000000-0000-4000-8000-000000000001",
    instagram: "34000000-0000-4000-8000-000000000002",
    x: "34000000-0000-4000-8000-000000000003",
    blog: "34000000-0000-4000-8000-000000000004",
  },
} as const

const now = "2026-07-13T08:00:00Z"
const evidenceUrl = "https://example.com/fa/reports/today"
const scheduledFor = "2026-07-20T10:30:00Z"

type BackendState = {
  approved: Set<string>
  childCreated: boolean
  controlPaused: boolean
  controlRequests: Array<Record<string, unknown>>
  copyReady: boolean
  dryRunRequests: Array<Record<string, unknown>>
  emptyCalendar: boolean
  emptyInbox: boolean
  exportPolls: number
  exportRequest: Record<string, unknown> | null
  intakeRequests: Array<Record<string, unknown>>
  reconciliation: boolean
  reconciliationRequest: Record<string, unknown> | null
  reconciliationResolved: boolean
  researchRequests: Array<Record<string, unknown>>
  retryRequested: boolean
  routeCreated: boolean
  routeName: string
  routePaused: boolean
  routeRequest: Record<string, unknown> | null
  routeResearchMode: "off" | "manual" | "auto_if_incomplete"
  routePublishingPolicy: "review_required" | "auto_publish"
  telegramEditBody: string
  telegramEditRequest: Record<string, unknown> | null
  unhandled: string[]
}

type BackendOptions = {
  allApproved?: boolean
  emptyCalendar?: boolean
  emptyInbox?: boolean
  reconciliation?: boolean
}

for (const viewport of viewports) {
  test(`complete newsroom flow ${viewport.width} uses Persian RTL and operational truth`, async ({ page }) => {
    const backend = await installAcceptanceBackend(page)
    await page.setViewportSize(viewport)

    await page.goto("/")
    await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible()
    await expect(page.getByRole("region", { name: "Telegram publication outcomes" })).toBeVisible()

    await page.goto("/inbox")
    const persianStory = page.getByText("گزارش امروز", { exact: true }).first()
    await expect(persianStory).toBeVisible()
    await expect(persianStory).toHaveAttribute("dir", "rtl")
    await expect(persianStory).toHaveAttribute("lang", "fa")

    await page.goto(`/review/${ids.revisions.telegram}`)
    const telegramMessage = page.getByLabel("Telegram message").first()
    await expect(telegramMessage).toHaveAttribute("dir", "rtl")
    await expect(telegramMessage).toContainText("گزارش امروز")
    await page.getByRole("button", { name: "Approve revision", exact: true }).click()
    await expect(page.getByRole("status").filter({ hasText: "Revision approved" }).first()).toBeVisible()
    expect(backend.approved).toContain(ids.revisions.telegram)

    await page.goto("/calendar")
    await expect(page.getByRole("heading", { name: "Publication calendar", exact: true })).toBeVisible()
    await page.getByRole("button", { name: "Chronological list view" }).click()
    await expect(page.getByText("گزارش امروز", { exact: true }).first()).toHaveAttribute("dir", "auto")

    await page.goto("/diagnostics")
    await expect(page.getByRole("heading", { name: "Diagnostics", exact: true })).toBeVisible()
    await expect(page.getByText(/Source\/generation worker last observed/)).toBeVisible()
    await expect(page.getByText(/Publishing worker last observed/)).toBeVisible()
    await expect(page.getByText(/Scheduler last observed/)).toBeVisible()
    await expectNoHorizontalOverflow(page)
    expect(backend.unhandled).toEqual([])
  })
}

test("review-first route preserves manual research, dry-run review, and durable history", async ({ page }) => {
  const backend = await installAcceptanceBackend(page)
  await page.setViewportSize(viewports[0])
  await page.goto("/automations/new")

  await fillRouteIdentity(page, "مسیر بررسی خبر")
  await page.getByLabel("Research mode").selectOption("manual")
  await expect(page.getByLabel("Publishing policy")).toHaveValue("review_required")
  await page.getByRole("button", { name: "Create and activate" }).click()

  await expect(page).toHaveURL(new RegExp(`/automations/${ids.route}$`))
  await expect(page.getByRole("heading", { name: "مسیر بررسی خبر" })).toBeVisible()
  expect(backend.routeRequest).toMatchObject({
    research_mode: "manual",
    publishing_policy: "review_required",
    confirm_auto_publish: false,
  })
  await expect(page.getByText("Manual", { exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "Research more" })).toBeVisible()

  await page.getByLabel("Source message ID (optional)").fill("91")
  await page.getByRole("button", { name: "Run dry run" }).click()
  await expect(page.getByRole("status", { name: "Latest route action" })).toContainText("Dry run queued")
  expect(backend.dryRunRequests).toEqual([{ source_message_id: 91 }])

  await page.getByRole("link", { name: "Open durable route history" }).click()
  await expect(page.getByRole("heading", { name: "Automation history" })).toBeVisible()
  await expect(page.getByText("مسیر بررسی خبر فعال شد", { exact: true })).toHaveAttribute("dir", "auto")
  await expectNoHorizontalOverflow(page)
  expect(backend.unhandled).toEqual([])
})

test("automatic route requires explicit confirmation and exposes auto research outcome", async ({ page }) => {
  const backend = await installAcceptanceBackend(page)
  await page.setViewportSize(viewports[0])
  await page.goto("/automations/new")

  await fillRouteIdentity(page, "مسیر خودکار خبر")
  await page.getByLabel("Research mode").selectOption("auto_if_incomplete")
  await page.getByLabel("Publishing policy").selectOption("auto_publish")
  const create = page.getByRole("button", { name: "Create and activate" })
  await expect(create).toBeDisabled()
  await page.getByRole("checkbox", { name: "Confirm automatic publishing" }).check()
  await expect(create).toBeEnabled()
  await create.click()

  await expect(page).toHaveURL(new RegExp(`/automations/${ids.route}$`))
  expect(backend.routeRequest).toMatchObject({
    research_mode: "auto_if_incomplete",
    publishing_policy: "auto_publish",
    confirm_auto_publish: true,
    content_filters: { research_provider_profile_id: ids.provider },
  })
  await expect(page.getByText("Auto If Incomplete", { exact: true })).toBeVisible()
  await expect(page.getByText(/Research succeeded/)).toBeVisible()
  await expect(page.getByText("Fake acceptance provider · fake", { exact: true })).toBeVisible()
  expect(backend.unhandled).toEqual([])
})

test("manual URL and text intake support standard and deep research without credentials", async ({ page }) => {
  const backend = await installAcceptanceBackend(page)
  await page.setViewportSize(viewports[0])
  await page.goto("/inbox")

  await page.getByRole("button", { name: "Add story" }).click()
  await page.getByLabel("Story URL").fill(evidenceUrl)
  await page.getByLabel("Story title (optional)").fill("گزارش ورودی URL")
  await page.getByRole("dialog", { name: "Add story manually" }).getByRole("button", { name: "Add story" }).click()
  await expect(page.getByText("Intake queued", { exact: false })).toBeVisible()

  await page.getByRole("button", { name: "Add story" }).click()
  await page.getByRole("tab", { name: "Text" }).click()
  await page.getByLabel("Story title", { exact: true }).fill("گزارش ورودی متن")
  await page.getByLabel("Source label").fill("میز خبر")
  await page.getByLabel("Story text").fill("این متن فارسیِ تأییدشده برای ورود دستی و نگهداری شواهد کافی است.")
  await page.getByRole("dialog", { name: "Add story manually" }).getByRole("button", { name: "Add story" }).click()

  expect(backend.intakeRequests).toEqual([
    { kind: "url", url: evidenceUrl, title: "گزارش ورودی URL" },
    {
      kind: "text",
      title: "گزارش ورودی متن",
      text: "این متن فارسیِ تأییدشده برای ورود دستی و نگهداری شواهد کافی است.",
      source_label: "میز خبر",
      source_url: null,
    },
  ])

  await page.getByRole("button", { name: "Research more" }).first().click()
  const research = page.getByRole("dialog", { name: "Research story" })
  await research.getByLabel("Research note (optional)").fill("شواهد رسمی را بررسی کن")
  await research.getByRole("button", { name: "Research more" }).click()
  await expect(research.getByText("Research completed")).toBeVisible()
  await research.getByRole("button", { name: "Deep research" }).click()
  await expect.poll(() => backend.researchRequests.length).toBe(2)
  expect(backend.researchRequests).toEqual([
    { mode: "manual", depth: "standard", provider_profile_id: ids.provider, query_hint: "شواهد رسمی را بررسی کن" },
    { mode: "manual", depth: "deep", provider_profile_id: ids.provider, query_hint: "شواهد رسمی را بررسی کن" },
  ])
  expect(backend.unhandled).toEqual([])
})

test("global pause overrides work and a retryable failure returns to the durable queue", async ({ page }) => {
  const backend = await installAcceptanceBackend(page)
  await page.setViewportSize(viewports[0])
  await page.goto("/")

  await page.getByRole("button", { name: "Pause automations" }).click()
  await expect(page.getByRole("button", { name: "Resume automations" })).toBeVisible()
  await expect(page.getByRole("status", { name: "Latest control outcome" })).toContainText("Automation paused")
  await page.getByRole("button", { name: "Resume automations" }).click()
  await expect(page.getByRole("button", { name: "Pause automations" })).toBeVisible()
  expect(backend.controlRequests).toEqual([
    { global_pause: true, pause_reason: "Paused from Newsroom" },
    { global_pause: false },
  ])

  await page.goto("/jobs")
  await page.getByRole("button", { name: new RegExp(`View research\\.execute job ${ids.failedJob}`) }).click()
  const detail = page.getByRole("dialog", { name: "Job details" })
  await expect(detail).toContainText("Source request timed out")
  await detail.getByRole("button", { name: "Retry job" }).click()
  await expect(page.getByText("Retry requested", { exact: true }).first()).toBeVisible()
  expect(backend.retryRequested).toBe(true)
  expect(backend.unhandled).toEqual([])
})

test("ambiguous Telegram publication blocks blind retry and requires exact reconciliation", async ({ page }) => {
  const backend = await installAcceptanceBackend(page, { reconciliation: true })
  await page.setViewportSize(viewports[0])
  await page.goto("/")

  const panel = page.getByRole("region", { name: "Telegram reconciliation for @newscraft" })
  await expect(panel).toContainText("Automatic retry is blocked")
  await expect(panel.getByRole("button", { name: /retry/i })).toHaveCount(0)
  await expect(panel.getByText("telegram:album:0", { exact: true })).toBeVisible()
  await panel.getByRole("button", { name: "Confirm published" }).click()
  const remoteIds = panel.getByLabel("Verified remote message IDs")
  await remoteIds.fill("501, bad, 502")
  await expect(panel.getByRole("alert")).toContainText("positive, unique integers")
  await remoteIds.fill("501, 502")
  await panel.getByLabel("Telegram permalink (optional)").fill("https://t.me/newscraft/501")
  await panel.getByLabel("Verification note").fill("Verified against Telegram album receipt")
  await panel.getByRole("button", { name: "Confirm published messages" }).click()

  await expect.poll(() => backend.reconciliationResolved).toBe(true)
  expect(backend.reconciliationRequest).toEqual({
    outcome: "published",
    remote_message_ids: [501, 502],
    permalink: "https://t.me/newscraft/501",
    operator_note: "Verified against Telegram album receipt",
  })
  await expect(page.getByRole("region", { name: "Telegram reconciliation for @newscraft" })).toHaveCount(0)
  expect(backend.unhandled).toEqual([])
})

test("all exact copy actions and export formats stay bound to the four approved revisions", async ({ page }) => {
  const backend = await installAcceptanceBackend(page, { allApproved: true })
  await installClipboardCapture(page)
  await page.setViewportSize(viewports[0])
  await page.goto(`/drafts/${ids.contentPack}`)

  const actionsByPlatform = [
    { tab: "Telegram", actions: ["Copy Telegram formatted message"] },
    { tab: "Instagram", actions: ["Copy Instagram caption and hashtags"] },
    { tab: "X", actions: ["Copy full X thread", "Copy X post 1", "Copy X post 2"] },
    { tab: "Blog", actions: ["Copy Blog Markdown", "Copy Blog HTML"] },
  ] as const
  for (const item of actionsByPlatform) {
    await page.getByRole("tab", { name: item.tab, exact: true }).click()
    for (const action of item.actions) {
      await page.getByRole("button", { name: action }).click()
      await expect(page.getByRole("status").filter({ hasText: /^Copied/ })).toBeVisible()
    }
  }
  const copied = await page.evaluate(() => (window as typeof window & { __acceptanceCopies: string[] }).__acceptanceCopies)
  expect(copied).toHaveLength(7)
  expect(copied.some((value) => value.includes("گزارش امروز"))).toBe(true)

  for (const format of ["JSON", "HTML", "ZIP"] as const) await page.getByLabel(format, { exact: true }).check()
  await page.getByLabel("Include media").check()
  await page.getByRole("button", { name: "Export package" }).click()
  await expect(page.getByRole("status", { name: "Export status" })).toContainText("Export ready")
  expect(backend.exportPolls).toBeGreaterThan(0)
  expect(backend.exportRequest).toEqual({
    content_pack_id: ids.contentPack,
    revision_ids: platforms.map((platform) => ids.revisions[platform]),
    formats: ["json", "markdown", "html", "zip"],
    include_media: true,
  })
  await expect(page.getByLabel("Export downloads").getByRole("link")).toHaveCount(14)
  expect(backend.unhandled).toEqual([])
})

test("mobile navigation reaches the complete newsroom without horizontal overflow", async ({ page }) => {
  const backend = await installAcceptanceBackend(page)
  await page.setViewportSize(viewports[1])
  await page.goto("/")

  await page.getByRole("button", { name: "Open navigation" }).click()
  const navigation = page.getByRole("dialog", { name: "Newsroom navigation" })
  await expect(navigation).toBeVisible()
  await navigation.getByRole("link", { name: "Inbox", exact: true }).click()
  await expect(page).toHaveURL(/\/inbox$/)
  await expect(page.getByRole("heading", { name: "Editorial Inbox" })).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.getByRole("button", { name: "Open navigation" }).click()
  await page.getByRole("dialog", { name: "Newsroom navigation" }).getByRole("link", { name: "Diagnostics", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Diagnostics" })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  expect(backend.unhandled).toEqual([])
})

test("keyboard-only editor creates and approves an immutable Persian revision", async ({ page }) => {
  const backend = await installAcceptanceBackend(page)
  await page.setViewportSize(viewports[0])
  await page.goto(`/drafts/${ids.contentPack}`)
  await expect(page.getByRole("heading", { name: "Multi-platform editorial studio" })).toBeVisible()

  const message = page.getByLabel("Telegram message")
  await tabTo(page, message)
  await page.keyboard.press("Control+A")
  await page.keyboard.insertText("نسخه ویرایش‌شده با شواهد دقیق")
  const save = page.getByRole("button", { name: "Save new revision" })
  await tabTo(page, save)
  await page.keyboard.press("Enter")
  await expect.poll(() => backend.childCreated).toBe(true)
  await expect(page.getByText(new RegExp(`Loaded revision ${ids.childRevision}`))).toBeVisible()
  expect(backend.telegramEditRequest).toMatchObject({
    base_revision_id: ids.revisions.telegram,
    base_content_hash: "1".repeat(64),
    content: { body: "نسخه ویرایش‌شده با شواهد دقیق", parse_mode: "HTML" },
    edit_note: "Operator edit",
  })

  const approve = page.getByRole("button", { name: "Approve revision", exact: true })
  await tabTo(page, approve)
  await page.keyboard.press("Enter")
  await expect(page.getByRole("status").filter({ hasText: "Revision approved" }).first()).toBeVisible()
  expect(backend.approved).toContain(ids.childRevision)
  expect(backend.unhandled).toEqual([])
})

for (const viewport of viewports) {
  test(`${viewport.name} critical paths have no serious or critical axe violations`, async ({ page }) => {
    const backend = await installAcceptanceBackend(page, { allApproved: true })
    await page.setViewportSize(viewport)
    for (const route of ["/", "/inbox", "/automations", "/drafts", `/drafts/${ids.contentPack}`, "/calendar", "/diagnostics", "/settings/retention"]) {
      await page.goto(route)
      await expect(page.getByRole("main")).toBeVisible()
      const results = await new AxeBuilder({ page }).analyze()
      const violations = results.violations
        .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
        .map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          targets: violation.nodes.flatMap((node) => node.target),
        }))
      expect(violations, `Accessibility violations on ${route} at ${viewport.width}px`).toEqual([])
    }
    expect(backend.unhandled).toEqual([])
  })
}

async function fillRouteIdentity(page: Page, name: string) {
  await page.getByLabel("Automation name").fill(name)
  await page.getByLabel("Source name").fill("منبع خبر")
  await page.getByLabel("Source channel").fill("source_newsroom")
  await page.getByLabel("Destination name").fill("اتاق خبر")
  await page.getByLabel("Destination target").fill("@newscraft")
  await page.getByLabel("Bot token environment variable").fill("TELEGRAM_BOT_TOKEN")
}

async function installClipboardCapture(page: Page) {
  await page.addInitScript(() => {
    const copies: string[] = []
    Object.defineProperty(window, "__acceptanceCopies", { configurable: true, value: copies })
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (value: string) => { copies.push(value) } },
    })
  })
}

async function tabTo(page: Page, target: Locator) {
  for (let index = 0; index < 120; index += 1) {
    if (await target.evaluate((element) => element === document.activeElement)) return
    await page.keyboard.press("Tab")
  }
  await expect(target).toBeFocused()
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() =>
    document.documentElement.scrollWidth > document.documentElement.clientWidth
    || document.body.scrollWidth > window.innerWidth
  )).toBe(false)
}

async function installAcceptanceBackend(page: Page, options: BackendOptions = {}): Promise<BackendState> {
  const state: BackendState = {
    approved: new Set(options.allApproved ? platforms.map((platform) => ids.revisions[platform]) : []),
    childCreated: false,
    controlPaused: false,
    controlRequests: [],
    copyReady: false,
    dryRunRequests: [],
    emptyCalendar: Boolean(options.emptyCalendar),
    emptyInbox: Boolean(options.emptyInbox),
    exportPolls: 0,
    exportRequest: null,
    intakeRequests: [],
    reconciliation: Boolean(options.reconciliation),
    reconciliationRequest: null,
    reconciliationResolved: false,
    researchRequests: [],
    retryRequested: false,
    routeCreated: true,
    routeName: "مسیر بررسی خبر",
    routePaused: false,
    routeRequest: null,
    routeResearchMode: "manual",
    routePublishingPolicy: "review_required",
    telegramEditBody: "گزارش امروز با شواهد تأییدشده آماده انتشار است.",
    telegramEditRequest: null,
    unhandled: [],
  }

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api\/backend/, "")
    const method = request.method()
    const body = method === "POST" || method === "PATCH" || method === "PUT"
      ? request.postDataJSON() as Record<string, unknown>
      : null

    if (path === "/automation-control") {
      if (method === "PATCH" && body) {
        state.controlRequests.push(body)
        if (typeof body.global_pause === "boolean") state.controlPaused = body.global_pause
      }
      return json(route, automationControlWire(state))
    }
    if (path === "/jobs/summary" && method === "GET") {
      return json(route, { queued: state.retryRequested ? 1 : 0, running: 0, attention: state.retryRequested ? 0 : 1, succeeded_today: 1 })
    }
    if (path === `/jobs/${ids.failedJob}` && method === "GET") return json(route, failedJobWire(state, true))
    if (path === `/jobs/${ids.failedJob}/retry` && method === "POST") {
      state.retryRequested = true
      return json(route, failedJobWire(state))
    }
    if (path === "/jobs" && method === "GET") {
      const statuses = url.searchParams.getAll("status")
      const includeFailed = !state.retryRequested && (!statuses.length || statuses.includes("failed") || statuses.includes("needs_review"))
      const includeRetried = state.retryRequested && (!statuses.length || statuses.includes("queued"))
      return json(route, { items: [...(includeFailed ? [failedJobWire(state)] : []), ...(includeRetried ? [failedJobWire(state)] : [])] })
    }

    if (path === "/stories" && method === "GET") return json(route, { items: state.emptyInbox ? [] : [storySummaryWire()], next_cursor: null })
    if (path === `/stories/${ids.story}` && method === "GET") return json(route, storySummaryWire())
    if (path === `/stories/${ids.story}/evidence` && method === "GET") return json(route, [evidenceWire()])
    if (path === "/stories/manual" && method === "POST" && body) {
      state.intakeRequests.push(body)
      return json(route, accepted(ids.intakeJob), 202)
    }
    if (path === `/stories/${ids.story}/research-runs` && method === "POST" && body) {
      state.researchRequests.push(body)
      return json(route, {
        disposition: "enqueued",
        run_id: state.researchRequests.length > 1 ? ids.deepResearchRun : ids.researchRun,
        job_id: ids.researchJob,
        completeness: storySummaryWire().completeness,
      }, 202)
    }
    if (path === `/stories/${ids.story}/research-runs` && method === "GET") {
      if (state.routeResearchMode === "auto_if_incomplete" && !state.researchRequests.length) {
        return json(route, { items: [researchRunWire("auto_if_incomplete", ids.researchRun)] })
      }
      if (!state.researchRequests.length) return json(route, { items: [] })
      const runId = state.researchRequests.length > 1 ? ids.deepResearchRun : ids.researchRun
      return json(route, { items: [researchRunWire("manual", runId)] })
    }
    if (path === "/ai-provider-profiles" && method === "GET") return json(route, [providerWire()])
    if (path === "/brand-profiles" && method === "GET") return json(route, [{ id: ids.brand, name: "اتاق خبر فارسی", is_default: true }])
    if (path === "/prompt-templates" && method === "GET") return json(route, [
      { id: ids.canonicalTemplate, purpose_key: "canonical_story" },
      { id: ids.telegramTemplate, purpose_key: "telegram_pack" },
    ])
    if (path === `/prompt-templates/${ids.canonicalTemplate}/versions` && method === "GET") {
      return json(route, [{ id: ids.canonicalPrompt, version: 1, checksum_sha256: "c".repeat(64), is_active: true }])
    }
    if (path === `/prompt-templates/${ids.telegramTemplate}/versions` && method === "GET") {
      return json(route, [{ id: ids.telegramPrompt, version: 1, checksum_sha256: "d".repeat(64), is_active: true }])
    }

    if (path === `/content-packs/${ids.contentPack}` && method === "GET") return json(route, contentPackWire(state))
    if (path === "/content-pack-requests" && method === "GET") return json(route, [])
    for (const platform of platforms) {
      if (path === `/platform-variants/${ids.variants[platform]}/revisions` && method === "GET") {
        const rows = platform === "telegram" && state.childCreated
          ? [revisionWire("telegram", state, ids.childRevision), revisionWire("telegram", state)]
          : [revisionWire(platform, state)]
        return json(route, rows)
      }
    }
    if (path === `/platform-variants/${ids.variants.telegram}/revisions` && method === "POST" && body) {
      state.childCreated = true
      state.telegramEditRequest = body
      const content = body.content as Record<string, unknown>
      state.telegramEditBody = String(content.body)
      return json(route, revisionWire("telegram", state, ids.childRevision), 201)
    }
    if (path.startsWith("/platform-variant-revisions/") && path.endsWith("/approve") && method === "POST") {
      const revisionId = path.split("/")[2]!
      state.approved.add(revisionId)
      return json(route, revisionForId(revisionId, state))
    }
    if (path.startsWith("/platform-variant-revisions/") && path.endsWith("/rendered-html") && method === "GET") {
      return json(route, {
        revision_id: ids.revisions.blog,
        content_hash: hashFor("blog"),
        platform: "blog",
        html: "<article dir=\"rtl\"><h1>گزارش امروز</h1></article>",
      })
    }
    if (path.startsWith("/platform-variant-revisions/") && method === "GET") {
      return json(route, revisionForId(path.split("/")[2]!, state))
    }
    if (path === `/content-packs/${ids.contentPack}/exports` && method === "POST" && body) {
      state.exportRequest = body
      return json(route, accepted(ids.exportJob), 202)
    }
    if (path === `/exports/${ids.exportJob}` && method === "GET") {
      state.exportPolls += 1
      return json(route, exportOutcomeWire())
    }

    if (path === "/telegram/automations/options" && method === "GET") return json(route, automationOptionsWire())
    if (path === "/telegram/sources" && method === "POST") return json(route, sourceWire(), 201)
    if (path === "/telegram/destinations" && method === "POST") {
      return json(route, { destination: destinationWire(), job: accepted(ids.routeJob) }, 202)
    }
    if (path === "/telegram/destinations" && method === "GET") return json(route, [destinationWire()])
    if (path === "/telegram/automations" && method === "POST" && body) {
      state.routeCreated = true
      state.routeRequest = body
      state.routeName = String(body.name)
      state.routeResearchMode = body.research_mode as BackendState["routeResearchMode"]
      state.routePublishingPolicy = body.publishing_policy as BackendState["routePublishingPolicy"]
      return json(route, routeWire(state), 201)
    }
    if (path === "/telegram/automations" && method === "GET") return json(route, state.routeCreated ? [routeWire(state)] : [])
    if (path === `/telegram/automations/${ids.route}/activate` && method === "POST") {
      return json(route, { route: routeWire(state), job: accepted(ids.routeJob) }, 202)
    }
    if (path === `/telegram/automations/${ids.route}/pause` && method === "POST") {
      state.routePaused = true
      return json(route, routeWire(state))
    }
    if (path === `/telegram/automations/${ids.route}/resume` && method === "POST") {
      state.routePaused = false
      return json(route, routeWire(state))
    }
    if (path === `/telegram/automations/${ids.route}/dry-run` && method === "POST" && body) {
      state.dryRunRequests.push(body)
      return json(route, { route: routeWire(state), job: accepted(ids.routeJob) }, 202)
    }
    if (path === `/telegram/automations/${ids.route}/backfill` && method === "POST") {
      return json(route, { route: routeWire(state), job: accepted(ids.routeJob) }, 202)
    }
    if (path === `/telegram/automations/${ids.route}/dispatches` && method === "GET") {
      return json(route, state.routeResearchMode === "auto_if_incomplete" ? [dispatchWire()] : [])
    }
    if (path === `/telegram/automations/${ids.route}` && method === "GET") return json(route, routeWire(state))
    if (path === "/telegram/drafts" && method === "GET") {
      return json(route, state.reconciliation ? [] : [telegramDraftWire(state)])
    }
    if (path.startsWith("/telegram/drafts/") && method === "GET") {
      return json(route, telegramDraftWire(state, path.split("/")[3]!))
    }

    if (path === "/telegram/reconciliation" && method === "GET") {
      return json(route, state.reconciliation && !state.reconciliationResolved ? [reconciliationCaseWire()] : [])
    }
    if (path === `/telegram/publish-jobs/${ids.publishJob}/reconcile` && method === "POST" && body) {
      state.reconciliationRequest = body
      state.reconciliationResolved = true
      return json(route, publicationWire())
    }

    if (path === "/calendar" && method === "GET") {
      const calendar = calendarWire(url.searchParams.get("timezone") ?? "Asia/Tehran")
      return json(route, state.emptyCalendar ? { ...calendar, items: [] } : calendar)
    }
    if (path === "/operations/diagnostics" && method === "GET") return json(route, diagnosticsWire(state))
    if (path === "/operations/history" && method === "GET") return json(route, historyWire(state))
    if (path === "/operations/retention-policy" && method === "GET") return json(route, retentionPolicyWire())
    if (path.startsWith(`/platform-variant-revisions/${ids.revisions.instagram}/manual-publication-plan`) && method === "GET") {
      return json(route, { detail: "No manual publication plan exists" }, 404)
    }

    const label = `${method} ${path}${url.search}`
    state.unhandled.push(label)
    return json(route, { detail: `Unhandled deterministic acceptance request: ${label}` }, 501)
  })

  return state
}

async function json(route: Route, body: unknown, status = 200) {
  await fulfillMockJson(route, body, status)
}

function accepted(jobId: string) {
  return { job_id: jobId, status: "queued", deduplicated: false }
}

function automationControlWire(state: BackendState) {
  return {
    global_pause: state.controlPaused,
    dry_run: false,
    pause_reason: state.controlPaused ? "Paused from Newsroom" : null,
    paused_at: state.controlPaused ? "2026-07-13T08:05:00Z" : null,
    updated_at: "2026-07-13T08:05:00Z",
  }
}

function failedJobWire(state: BackendState, detail = false) {
  const base = {
    id: ids.failedJob,
    job_type: "research.execute",
    status: state.retryRequested ? "queued" : "failed",
    origin: state.retryRequested ? "retry" : "automation",
    priority: 0,
    pause_sensitive: true,
    scheduled_for: now,
    attempt_count: state.retryRequested ? 2 : 1,
    max_attempts: 3,
    progress: state.retryRequested ? 0 : 35,
    progress_message: state.retryRequested ? "Queued for retry" : "Waiting for source response",
    error_class: state.retryRequested ? null : "retryable",
    error_code: state.retryRequested ? null : "source_timeout",
    error_message: state.retryRequested ? null : "Source request timed out",
    started_at: state.retryRequested ? null : now,
    finished_at: state.retryRequested ? null : "2026-07-13T08:02:00Z",
    created_at: now,
    updated_at: "2026-07-13T08:02:00Z",
  }
  return detail ? {
    ...base,
    payload: { story_id: ids.story, authorization: "[REDACTED]" },
    result: {},
    events: [{ id: ids.failedJobEvent, event_type: "job.failed", actor: "worker-source-generation", event_data: { error_code: "source_timeout" }, created_at: "2026-07-13T08:02:00Z" }],
  } : base
}

function storySummaryWire() {
  return {
    id: ids.story,
    title: "گزارش امروز",
    status: "inbox",
    primary_language: "fa",
    evidence_count: 1,
    latest_evidence_at: now,
    completeness: { complete: false, score: 60, reasons: ["یک منبع تکمیلی لازم است"] },
    evidence_set_hash: "a".repeat(64),
    created_at: now,
    updated_at: now,
  }
}

function evidenceWire() {
  return {
    id: ids.evidence,
    evidence_key: "report:today",
    title: "گزارش رسمی امروز",
    content_text: "متن منبع فارسی با جزئیات تأییدشده برای تهیه بسته خبری امروز.",
    content_sha256: "b".repeat(64),
    source_url: evidenceUrl,
    authors: ["میز پژوهش"],
    published_at: "2026-07-13T07:00:00Z",
    captured_at: now,
  }
}

function researchRunWire(requestedMode: "manual" | "auto_if_incomplete", runId: string) {
  return {
    id: runId,
    story_id: ids.story,
    requested_mode: requestedMode,
    status: "succeeded",
    provider: { id: ids.provider, name: "Fake acceptance provider", provider_type: "fake" },
    budget: { max_queries: 4, max_pages: 8, max_elapsed_seconds: 120 },
    requested_model: "fake-research-v1",
    resolved_model: "fake-research-v1",
    evidence_set_hash: "a".repeat(64),
    completeness: { complete: true, score: 100, reasons: [] },
    attempts: [{ id: ids.researchJob, attempt_number: 1, status: "succeeded", error_message: null }],
    sources: [{ id: ids.evidence, url: evidenceUrl, title: "گزارش رسمی امروز", content_sha256: "b".repeat(64), published_at: "2026-07-13T07:00:00Z" }],
    result_revision_id: ids.storyRevision,
  }
}

function providerWire() {
  return {
    id: ids.provider,
    name: "Fake acceptance provider",
    provider_type: "fake",
    default_model: "fake-newsroom-v1",
    settings: {},
    enabled: true,
    configured: true,
    capabilities: { generation: true, research: true },
    unavailability_codes: [],
  }
}

function contentPackWire(state: BackendState) {
  const variants = platforms.map((platform) => {
    const revisionId = platform === "telegram" && state.childCreated ? ids.childRevision : ids.revisions[platform]
    return { id: ids.variants[platform], platform, current_revision: revisionWire(platform, state, revisionId) }
  })
  const approved = variants.every((variant) => state.approved.has(variant.current_revision.id))
  return {
    id: ids.contentPack,
    story_id: ids.story,
    story_revision_id: ids.storyRevision,
    brand_profile_id: ids.brand,
    status: approved ? "approved" : "pending_review",
    created_at: now,
    updated_at: now,
    variants,
  }
}

function revisionForId(revisionId: string, state: BackendState) {
  if (revisionId === ids.childRevision) return revisionWire("telegram", state, revisionId)
  const platform = platforms.find((candidate) => ids.revisions[candidate] === revisionId)
  if (!platform) throw new Error(`Unknown deterministic revision ${revisionId}`)
  return revisionWire(platform, state)
}

function revisionWire(platform: Platform, state: BackendState, revisionId: string = ids.revisions[platform]) {
  const isChild = revisionId === ids.childRevision
  const content = contentWire(platform, state, isChild)
  return {
    id: revisionId,
    platform,
    platform_variant_id: ids.variants[platform],
    content_pack_id: ids.contentPack,
    story_id: ids.story,
    parent_revision_id: isChild ? ids.revisions.telegram : null,
    generation_attempt_id: ids.attempts[platform],
    revision_number: isChild ? 2 : 1,
    content,
    content_hash: isChild ? "5".repeat(64) : hashFor(platform),
    evidence_map: [citationWire()],
    manual_checklist: platform === "telegram" ? [] : content.manual_checklist,
    validation_results: [{ gate: `${platform}_schema`, ok: true, reason: null }],
    validation_issues: [],
    media_plan: [],
    source_media: [],
    approval_state: state.approved.has(revisionId) ? "approved" : "pending_review",
    approval_note: state.approved.has(revisionId) ? "Accepted in deterministic browser flow" : null,
    approved_at: state.approved.has(revisionId) ? "2026-07-13T09:00:00Z" : null,
    created_by: isChild ? "operator" : "generation",
    origin: isChild ? "operator" : "generation",
    provider_profile: { id: ids.provider, name: "Fake acceptance provider", provider_type: "fake" },
    resolved_model: "fake-newsroom-v1",
    prompt_version: { id: ids.prompts[platform], version: 1, output_schema_version: `${platform}_pack.v1`, checksum_sha256: hashFor(platform) },
    created_at: now,
  }
}

function contentWire(platform: Platform, state: BackendState, child: boolean): Record<string, any> {
  if (platform === "telegram") return {
    body: child ? state.telegramEditBody : "گزارش امروز با شواهد تأییدشده آماده انتشار است.",
    parse_mode: "HTML",
    buttons: [{ text: "مشاهده منبع", url: evidenceUrl }],
    source_item_id: null,
    source_url: evidenceUrl,
    media_policy: "preserve",
    media_asset_ids: [],
    direction: "rtl",
    dry_run: false,
  }
  if (platform === "instagram") return {
    hook: "گزارش امروز؛ جزئیات تأییدشده",
    caption: "این کپشن بر پایه گزارش رسمی و شواهد ذخیره‌شده تهیه شده است.",
    cta: "منبع کامل را بخوانید",
    hashtags: ["#خبر", "#گزارش_امروز"],
    alt_text: "کارت خلاصه گزارش تأییدشده امروز",
    carousel: [{ order: 1, headline: "گزارش امروز", body: "جزئیات تأییدشده", media: mediaAssignment("slide") }],
    citations: [citationWire()],
    manual_checklist: ["Verify Instagram copy and carousel"],
  }
  if (platform === "x") return {
    mode: "thread",
    posts: [
      { order: 1, text: "گزارش امروز بر پایه شواهد رسمی تهیه شد.", media: [], citations: [citationWire()] },
      { order: 2, text: "برای جزئیات، منبع کامل را بخوانید.", media: [], citations: [citationWire()] },
    ],
    link_strategy: "last_post",
    manual_checklist: ["Verify X thread order and links"],
  }
  return {
    title: "گزارش امروز",
    slug: "today-report",
    excerpt: "جزئیات تأییدشده گزارش امروز.",
    body_markdown: "# گزارش امروز\n\nمتن مقاله بر پایه منبع رسمی تهیه شده است.",
    headings: ["گزارش امروز", "چرا مهم است"],
    citations: [citationWire()],
    tags: ["خبر", "گزارش"],
    seo_description: "گزارش امروز با جزئیات و منبع تأییدشده.",
    hero_media: mediaAssignment("hero"),
    canonical_sources: [evidenceUrl],
    manual_checklist: ["Verify Blog article and canonical source"],
  }
}

function citationWire() {
  return {
    evidence_snapshot_id: ids.evidence,
    evidence_key: "report:today",
    source_url: evidenceUrl,
    locator: "chars:0-42",
    excerpt_sha256: "a".repeat(64),
  }
}

function mediaAssignment(role: "slide" | "hero") {
  return { media_asset_id: null, role, order: 1, alt_text: "تصویر گزارش امروز", manual_brief: "Use verified newsroom art", image_prompt: null }
}

function hashFor(platform: Platform) {
  return ({ telegram: "1", instagram: "2", x: "3", blog: "4" } as const)[platform].repeat(64)
}

function automationOptionsWire() {
  return {
    sources: [{ id: ids.source, name: "منبع خبر", access_mode: "public_html" }],
    destinations: [{ id: ids.destination, name: "اتاق خبر", health_status: "healthy", allow_auto_publish: true }],
    brand_profiles: [{ id: ids.brand, name: "اتاق خبر فارسی" }],
    prompt_template_versions: [{ id: ids.telegramPrompt, version: 1 }],
    ai_provider_profiles: [{
      id: ids.provider,
      name: "Fake acceptance provider",
      provider_type: "fake",
      default_model: "fake-newsroom-v1",
      configured: true,
      capabilities: { generation: true, research: true },
      unavailability_codes: [],
    }],
  }
}

function sourceWire() {
  return { id: ids.source, name: "منبع خبر", channel_ref: "source_newsroom", access_mode: "public_html", language_hint: "fa", configured: true }
}

function destinationWire() {
  return { id: ids.destination, name: "اتاق خبر", target_ref: "@newscraft", enabled: true, health_status: "healthy", configured: true, settings: { allow_auto_publish: true } }
}

function routeWire(state: BackendState) {
  return {
    id: ids.route,
    name: state.routeName,
    source_id: ids.source,
    destination_id: ids.destination,
    brand_profile_id: ids.brand,
    prompt_template_version_id: ids.telegramPrompt,
    ai_provider_profile_id: ids.provider,
    access_mode: "public_html",
    research_mode: state.routeResearchMode,
    content_filters: {
      include_terms: [], exclude_terms: [], min_text_characters: 1, require_media: false,
      ...(state.routeResearchMode === "off" ? {} : { research_provider_profile_id: ids.provider }),
    },
    media_policy: "preserve",
    attribution_policy: "preserve",
    custom_footer: null,
    publishing_policy: state.routePublishingPolicy,
    poll_interval_seconds: 300,
    quiet_hours: {},
    retry_policy: { max_attempts: 3, base_delay_seconds: 30, max_delay_seconds: 1800 },
    cursor_state: { status: "active", activation_message_id: 90, last_message_id: 91, recent_fingerprints: {} },
    enabled: true,
    paused_at: state.routePaused ? "2026-07-13T08:10:00Z" : null,
    last_polled_at: "2026-07-13T08:00:00Z",
    next_poll_at: "2026-07-13T08:05:00Z",
    created_at: now,
    updated_at: now,
  }
}

function dispatchWire() {
  return {
    id: "35000000-0000-4000-8000-000000000001",
    route_id: ids.route,
    source_item_id: ids.source,
    story_id: ids.story,
    story_revision_id: ids.storyRevision,
    source_key: "message:91",
    source_fingerprint: "f".repeat(64),
    source_message_ids: [91],
    dispatch_kind: "live",
    status: "review_required",
    generation_run_id: ids.researchRun,
    variant_revision_id: ids.revisions.telegram,
    publish_job_id: null,
    error_code: null,
    error_message: null,
    created_at: now,
    updated_at: now,
  }
}

function telegramDraftWire(state: BackendState, requestedId?: string) {
  const revisionId = requestedId === ids.childRevision || state.childCreated ? ids.childRevision : ids.revisions.telegram
  const revision = revisionWire("telegram", state, revisionId)
  return {
    id: revision.id,
    platform_variant_id: revision.platform_variant_id,
    parent_revision_id: revision.parent_revision_id,
    generation_attempt_id: revision.generation_attempt_id,
    revision_number: revision.revision_number,
    content: revision.content,
    content_hash: revision.content_hash,
    evidence_map: revision.evidence_map,
    evidence: [{ evidence_snapshot_id: ids.evidence, evidence_key: "report:today", source_url: evidenceUrl, content_text: evidenceWire().content_text, content_sha256: evidenceWire().content_sha256 }],
    media: [],
    validation_results: revision.validation_results,
    approval_state: revision.approval_state,
    approval_note: revision.approval_note,
    approved_at: revision.approved_at,
    created_by: revision.created_by,
    created_at: revision.created_at,
    route_id: ids.route,
    dispatch_id: dispatchWire().id,
    publish_job_id: null,
    publish_status: null,
    publication: null,
  }
}

function reconciliationCaseWire() {
  return {
    publish_job_id: ids.publishJob,
    status: "pending",
    publish_status: "reconciliation_required",
    workflow_job_id: ids.workflowJob,
    platform_variant_revision_id: ids.revisions.telegram,
    destination: { id: ids.destination, name: "اتاق خبر", target_ref: "@newscraft" },
    operations: [{
      operation_index: 0,
      operation_key: "telegram:album:0",
      method: "sendMediaGroup",
      request_hash: "f".repeat(64),
      status: "ambiguous",
      attempt_count: 1,
      remote_message_ids: [],
      sent_at: "2026-07-13T08:01:00Z",
    }],
    ambiguous_operation_key: "telegram:album:0",
    ambiguous_at: "2026-07-13T08:01:30Z",
    ambiguity_reason: "Connection closed after Telegram accepted the media group.",
  }
}

function publicationWire() {
  return {
    id: ids.publication,
    publish_job_id: ids.publishJob,
    destination_id: ids.destination,
    platform_variant_revision_id: ids.revisions.telegram,
    remote_message_ids: [501, 502],
    permalink: "https://t.me/newscraft/501",
    payload_hash: "e".repeat(64),
    published_at: "2026-07-13T08:03:00Z",
    reconciliation_status: "confirmed",
  }
}

function calendarWire(timezone: string) {
  return {
    items: [{
      id: `manual:${ids.manualPlan}`,
      kind: "manual_publication",
      platform: "instagram",
      revision_id: ids.revisions.instagram,
      title: "گزارش امروز",
      starts_at: scheduledFor,
      status: "ready",
      action_url: `/review/${ids.revisions.instagram}`,
    }],
    timezone,
  }
}

function diagnosticsWire(state: BackendState) {
  return {
    generated_at: "2026-07-13T08:06:00Z",
    global_paused: state.controlPaused,
    dry_run: false,
    components: {
      "worker-source-generation": { status: "healthy", observed_at: "2026-07-13T08:05:30Z", last_success_at: "2026-07-13T08:05:00Z", message: "Source collection and generation heartbeat persisted.", action_url: "/jobs" },
      "worker-publishing": { status: "healthy", observed_at: "2026-07-13T08:05:20Z", last_success_at: "2026-07-13T08:04:50Z", message: "Publishing heartbeat persisted.", action_url: "/jobs" },
      scheduler: { status: "healthy", observed_at: "2026-07-13T08:05:10Z", last_success_at: "2026-07-13T08:04:40Z", message: "Scheduler heartbeat persisted.", action_url: "/automations" },
    },
    queue_counts: { queued: state.retryRequested ? 1 : 0, failed: state.retryRequested ? 0 : 1 },
    outbound_proxy: {
      mode: "direct",
      scheme: null,
      bypass_rule_count: 0,
      last_connectivity_status: "ok",
      configuration_error_code: null,
    },
    attention: [{ id: ids.failedJob, severity: "warning", kind: "job", title: "پژوهش نیازمند بررسی است", occurred_at: "2026-07-13T08:02:00Z", action_url: "/jobs" }],
  }
}

function historyWire(state: BackendState) {
  return {
    items: [{
      id: "history:route:activated",
      occurred_at: "2026-07-13T08:00:00Z",
      category: "collection",
      status: "succeeded",
      title: `${state.routeName} فعال شد`,
      summary: "Cursor initialized after the persisted activation request.",
      job_id: ids.routeJob,
      subject_url: `/automations/${ids.route}`,
      sanitized_metadata: { last_message_id: 91, secret_ref: "[REDACTED]" },
    }],
    next_cursor: null,
  }
}

function retentionPolicyWire() {
  return {
    id: "global",
    raw_payload_days: 30,
    completed_job_days: 90,
    attempt_metadata_days: 90,
    export_artifact_days: 14,
    unreferenced_media_days: 30,
    created_at: now,
    updated_at: now,
  }
}

function exportOutcomeWire() {
  const formats = [
    { kind: "json", extension: "json", bytes: 128 },
    { kind: "markdown", extension: "md", bytes: 256 },
    { kind: "html", extension: "html", bytes: 384 },
  ] as const
  const files = platforms.flatMap((platform) => formats.map((format) => ({
    file_name: `${platform}/${ids.revisions[platform]}/content.${format.extension}`,
    sha256: hashFor(platform),
    byte_length: format.bytes,
    kind: format.kind,
    platform,
    revision_id: ids.revisions[platform],
    media_asset_id: null,
  })))
  const downloads = [
    `/exports/${ids.exportJob}/download/manifest.json`,
    `/exports/${ids.exportJob}/download/bundle.zip`,
    ...files.map((file) => `/exports/${ids.exportJob}/download/${file.file_name}`),
  ]
  return {
    export_id: ids.exportJob,
    status: "succeeded",
    finished_at: "2026-07-13T09:05:00Z",
    artifact: {
      export_id: ids.exportJob,
      content_pack_id: ids.contentPack,
      state: "complete",
      manifest_file: "manifest.json",
      manifest_sha256: "d".repeat(64),
      archive_file: "bundle.zip",
      archive_sha256: "e".repeat(64),
      manifest: {
        schema_version: "newscraft-export-v1",
        content_pack_id: ids.contentPack,
        story_revision_id: ids.storyRevision,
        created_at: now,
        variants: platforms.map((platform) => ({
          platform,
          platform_variant_id: ids.variants[platform],
          revision_id: ids.revisions[platform],
          content_hash: hashFor(platform),
          approval_state: "approved",
          evidence_urls: [evidenceUrl],
        })),
        files,
      },
    },
    downloads,
    error_code: null,
    error_message: null,
  }
}

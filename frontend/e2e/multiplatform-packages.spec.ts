import { expect, test, type Page, type Route } from "@playwright/test"

import { fulfillMockJson } from "./support/mock-backend"

type Platform = "telegram" | "instagram" | "x" | "blog"

const ids = {
  contentPack: "20000000-0000-4000-8000-000000000001",
  story: "20000000-0000-4000-8000-000000000002",
  storyRevision: "20000000-0000-4000-8000-000000000003",
  brand: "20000000-0000-4000-8000-000000000004",
  evidence: "20000000-0000-4000-8000-000000000005",
  media: "20000000-0000-4000-8000-000000000006",
  provider: "20000000-0000-4000-8000-000000000007",
  telegramTemplate: "20000000-0000-4000-8000-000000000008",
  telegramPrompt: "20000000-0000-4000-8000-000000000009",
  exportJob: "20000000-0000-4000-8000-000000000010",
  manualPlan: "20000000-0000-4000-8000-000000000011",
  variants: {
    telegram: "21000000-0000-4000-8000-000000000001",
    instagram: "21000000-0000-4000-8000-000000000002",
    x: "21000000-0000-4000-8000-000000000003",
    blog: "21000000-0000-4000-8000-000000000004",
  },
  revisions: {
    telegram: "22000000-0000-4000-8000-000000000001",
    instagram: "22000000-0000-4000-8000-000000000002",
    x: "22000000-0000-4000-8000-000000000003",
    blog: "22000000-0000-4000-8000-000000000004",
  },
  attempts: {
    telegram: "23000000-0000-4000-8000-000000000001",
    instagram: "23000000-0000-4000-8000-000000000002",
    x: "23000000-0000-4000-8000-000000000003",
    blog: "23000000-0000-4000-8000-000000000004",
  },
  prompts: {
    telegram: "24000000-0000-4000-8000-000000000001",
    instagram: "24000000-0000-4000-8000-000000000002",
    x: "24000000-0000-4000-8000-000000000003",
    blog: "24000000-0000-4000-8000-000000000004",
  },
} as const

const platforms = ["telegram", "instagram", "x", "blog"] as const
const now = "2026-07-13T08:00:00Z"
const scheduledFor = "2026-07-20T10:30:00.000Z"
const completedAt = "2026-07-20T10:45:00Z"
const evidenceUrl = "https://example.com/reports/agent-release"
const publicationUrl = "https://instagram.com/p/agent-release"
const expectedExportMatrix = [
  { fileName: `telegram/${ids.revisions.telegram}/content.json`, kind: "json", platform: "telegram", revisionId: ids.revisions.telegram },
  { fileName: `telegram/${ids.revisions.telegram}/content.md`, kind: "markdown", platform: "telegram", revisionId: ids.revisions.telegram },
  { fileName: `telegram/${ids.revisions.telegram}/content.html`, kind: "html", platform: "telegram", revisionId: ids.revisions.telegram },
  { fileName: `instagram/${ids.revisions.instagram}/content.json`, kind: "json", platform: "instagram", revisionId: ids.revisions.instagram },
  { fileName: `instagram/${ids.revisions.instagram}/content.md`, kind: "markdown", platform: "instagram", revisionId: ids.revisions.instagram },
  { fileName: `instagram/${ids.revisions.instagram}/content.html`, kind: "html", platform: "instagram", revisionId: ids.revisions.instagram },
  { fileName: `x/${ids.revisions.x}/content.json`, kind: "json", platform: "x", revisionId: ids.revisions.x },
  { fileName: `x/${ids.revisions.x}/content.md`, kind: "markdown", platform: "x", revisionId: ids.revisions.x },
  { fileName: `x/${ids.revisions.x}/content.html`, kind: "html", platform: "x", revisionId: ids.revisions.x },
  { fileName: `blog/${ids.revisions.blog}/content.json`, kind: "json", platform: "blog", revisionId: ids.revisions.blog },
  { fileName: `blog/${ids.revisions.blog}/content.md`, kind: "markdown", platform: "blog", revisionId: ids.revisions.blog },
  { fileName: `blog/${ids.revisions.blog}/content.html`, kind: "html", platform: "blog", revisionId: ids.revisions.blog },
] as const

for (const viewport of [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
] as const) {
  test(`${viewport.name} exports and manually completes one exact four-platform package`, async ({ page }) => {
    test.setTimeout(60_000)
    const backend = await installMultiplatformBackend(page)
    await page.setViewportSize(viewport)

    await page.goto(`/drafts/${ids.contentPack}`)
    await expect(page.getByRole("heading", { name: "Multi-platform editorial studio" })).toBeVisible()

    for (const [tabName, previewName] of [
      ["Telegram", "Telegram preview"],
      ["Instagram", "Instagram preview"],
      ["X", "X thread preview"],
      ["Blog", "Blog preview"],
    ] as const) {
      await page.getByRole("tab", { name: tabName, exact: true }).click()
      const preview = page.getByRole("region", { name: previewName })
      await expect(preview).toBeVisible()
      await expect(preview).toContainText("Approximation only")
      await expectNoHorizontalOverflow(page)
    }

    for (const format of ["JSON", "HTML", "ZIP"] as const) await page.getByLabel(format, { exact: true }).check()
    await page.getByRole("button", { name: "Export package" }).click()
    await expect(page.getByRole("status", { name: "Export status" })).toContainText("Export ready")
    expect(backend.exportPolls).toBeGreaterThan(0)
    expect(backend.requests.export).toEqual({
      content_pack_id: ids.contentPack,
      revision_ids: platforms.map((platform) => ids.revisions[platform]),
      formats: ["json", "markdown", "html", "zip"],
      include_media: false,
    })
    expect(backend.exportFileMatrix).toEqual(expectedExportMatrix)
    const downloadRoot = `/api/backend/exports/${ids.exportJob}/download`
    const expectedDownloads = [
      `${downloadRoot}/manifest.json`,
      `${downloadRoot}/bundle.zip`,
      ...expectedExportMatrix.map((item) => `${downloadRoot}/${item.fileName}`),
    ]
    const downloadLinks = page.getByLabel("Export downloads").getByRole("link")
    await expect(downloadLinks).toHaveCount(expectedDownloads.length)
    expect(await downloadLinks.evaluateAll((links) => links.map((link) => link.getAttribute("href")))).toEqual(expectedDownloads)
    for (const fileName of [
      expectedExportMatrix[0].fileName,
      expectedExportMatrix[4].fileName,
      expectedExportMatrix[8].fileName,
      expectedExportMatrix[9].fileName,
    ]) await expect(page.locator(`a[href="${downloadRoot}/${fileName}"]`)).toBeVisible()

    await page.getByRole("tab", { name: "Instagram", exact: true }).click()
    await page.getByRole("link", { name: "Preview, schedule, or publish approved revision" }).click()
    await expect(page).toHaveURL(new RegExp(`/review/${ids.revisions.instagram}$`))
    await expect(page.getByRole("region", { name: "Manual publication handoff" })).toBeVisible()
    await page.getByLabel("Scheduled time (UTC)").fill("2026-07-20T10:30")
    await page.getByLabel("Display timezone").selectOption("Asia/Tehran")
    await page.getByRole("button", { name: "Create manual publication plan" }).click()
    await expect(page.getByText("Manual publication plan created")).toBeVisible()
    expect(backend.requests.createPlan).toEqual({
      revision_id: ids.revisions.instagram,
      scheduled_for: scheduledFor,
      display_timezone: "Asia/Tehran",
    })

    for (const label of [
      "Copy reviewed",
      "Citations verified",
      "Media and alt text ready",
      "Platform requirements rechecked",
    ]) await page.getByRole("checkbox", { name: label }).check()
    await expect(page.getByText("Status: Ready to publish")).toBeVisible()
    expect(backend.checkedItems).toEqual([
      "copy_reviewed",
      "citations_verified",
      "media_and_alt_text_ready",
      "platform_requirements_rechecked",
    ])

    await page.getByLabel("Publication URL").fill(publicationUrl)
    await page.getByLabel("Operator note (optional)").fill("Verified against the approved Instagram revision")
    await page.getByRole("button", { name: "Mark as published" }).click()
    await expect(page.getByText("Manual publication recorded")).toBeVisible()
    await expect(page.getByRole("region", { name: "Manual publication completion evidence" }).getByRole("link", { name: "Open recorded publication" })).toHaveAttribute("href", publicationUrl)
    expect(backend.requests.markPublished).toEqual({
      external_url: publicationUrl,
      note: "Verified against the approved Instagram revision",
    })

    await navigateToCalendar(page, viewport.name === "mobile")
    await expect(page.getByRole("heading", { name: "Publication calendar" })).toBeVisible()
    await page.getByRole("button", { name: "Chronological list view" }).click()
    const event = page.getByRole("article").filter({ hasText: "Instagram: Agent release" })
    await expect(event).toContainText("manual published")
    await expect(event.getByRole("link", { name: new RegExp(`Open Instagram event: Agent release.*${ids.manualPlan}`) })).toHaveAttribute(
      "href",
      `/review/${ids.revisions.instagram}`,
    )
    await expectNoHorizontalOverflow(page)
  })
}

type BackendState = {
  exportPolls: number
  exportFileMatrix: Array<{ fileName: string; kind: string; platform: string; revisionId: string }>
  checkedItems: string[]
  planCreated: boolean
  planPublished: boolean
  checklist: Record<string, boolean>
  requests: Record<string, unknown>
}

async function installMultiplatformBackend(page: Page): Promise<BackendState> {
  const state: BackendState = {
    exportPolls: 0,
    exportFileMatrix: [],
    checkedItems: [],
    planCreated: false,
    planPublished: false,
    checklist: {
      copy_reviewed: false,
      citations_verified: false,
      media_and_alt_text_ready: false,
      platform_requirements_rechecked: false,
    },
    requests: {},
  }

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace("/api/backend", "")
    const method = request.method()
    const body = method === "POST" || method === "PATCH" ? request.postDataJSON() : undefined

    if (path === "/automation-control") return json(route, { global_pause: false, dry_run: false, pause_reason: null, paused_at: null, updated_at: now })
    if (path === "/jobs/summary") return json(route, { queued: 0, running: 0, attention: 0, succeeded_today: 1 })
    if (path === `/content-packs/${ids.contentPack}` && method === "GET") return json(route, contentPack())
    if (path === `/stories/${ids.story}/evidence` && method === "GET") return json(route, [evidenceWire()])
    if (path === "/ai-provider-profiles" && method === "GET") return json(route, [providerWire()])
    if (path === "/prompt-templates" && method === "GET") return json(route, [{ id: ids.telegramTemplate, purpose_key: "telegram_pack" }])
    if (path === `/prompt-templates/${ids.telegramTemplate}/versions` && method === "GET") {
      return json(route, [{ id: ids.telegramPrompt, version: 1, checksum_sha256: "1".repeat(64), is_active: true }])
    }
    for (const platform of platforms) {
      if (path === `/platform-variants/${ids.variants[platform]}/revisions` && method === "GET") {
        return json(route, [revisionWire(platform)])
      }
    }
    if (path === `/platform-variant-revisions/${ids.revisions.instagram}/manual-publication-plan` && method === "GET") {
      if (!state.planCreated) return json(route, { detail: "No manual publication plan exists" }, 404)
      return json(route, manualPlanWire(state))
    }
    for (const platform of platforms) {
      if (path === `/platform-variant-revisions/${ids.revisions[platform]}` && method === "GET") {
        return json(route, revisionWire(platform))
      }
    }
    if (path === `/content-packs/${ids.contentPack}/exports` && method === "POST") {
      state.requests.export = body
      return json(route, { job_id: ids.exportJob, status: "queued", deduplicated: false }, 202)
    }
    if (path === `/exports/${ids.exportJob}` && method === "GET") {
      state.exportPolls += 1
      const outcome = exportOutcomeWire()
      state.exportFileMatrix = outcome.artifact.manifest.files.map((item) => ({
        fileName: item.file_name,
        kind: item.kind,
        platform: item.platform,
        revisionId: item.revision_id,
      }))
      return json(route, outcome)
    }
    if (path === "/manual-publication-plans" && method === "POST") {
      state.requests.createPlan = body
      state.planCreated = true
      return json(route, manualPlanWire(state), 201)
    }
    if (path === `/manual-publication-plans/${ids.manualPlan}/checklist` && method === "PATCH") {
      const update = (body as { checklist_state: Record<string, boolean> }).checklist_state
      Object.assign(state.checklist, update)
      state.checkedItems.push(...Object.keys(update))
      return json(route, manualPlanWire(state))
    }
    if (path === `/manual-publication-plans/${ids.manualPlan}/mark-published` && method === "POST") {
      state.requests.markPublished = body
      state.planPublished = true
      return json(route, manualPlanWire(state))
    }
    if (path === "/calendar" && method === "GET") {
      return json(route, {
        items: [{
          id: `manual:${ids.manualPlan}`,
          kind: "manual_publication",
          platform: "instagram",
          revision_id: ids.revisions.instagram,
          title: "Agent release",
          starts_at: scheduledFor,
          status: state.planPublished ? "manual_published" : "ready",
          action_url: `/review/${ids.revisions.instagram}`,
        }],
        timezone: url.searchParams.get("timezone"),
      })
    }

    return json(route, { detail: `Unhandled deterministic route: ${method} ${path}` }, 501)
  })

  return state
}

async function navigateToCalendar(page: Page, mobile: boolean) {
  if (mobile) {
    await page.getByRole("button", { name: "Open navigation" }).click()
    const dialog = page.getByRole("dialog", { name: "Newsroom navigation" })
    await expect(dialog).toBeVisible()
    await dialog.getByRole("link", { name: "Calendar", exact: true }).click()
  } else {
    await page.getByRole("navigation", { name: "Newsroom navigation" }).getByRole("link", { name: "Calendar", exact: true }).click()
  }
  await page.waitForURL((url) => url.pathname === "/calendar")
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() =>
    document.documentElement.scrollWidth > document.documentElement.clientWidth
    || document.body.scrollWidth > window.innerWidth
  )).toBe(false)
}

async function json(route: Route, body: unknown, status = 200) {
  await fulfillMockJson(route, body, status)
}

function contentPack() {
  return {
    id: ids.contentPack,
    story_id: ids.story,
    story_revision_id: ids.storyRevision,
    brand_profile_id: ids.brand,
    status: "approved",
    created_at: now,
    updated_at: now,
    variants: platforms.map((platform) => ({
      id: ids.variants[platform],
      platform,
      current_revision: revisionWire(platform),
    })),
  }
}

function revisionWire(platform: Platform) {
  const content = contentWire(platform)
  const manualChecklist = platform === "telegram" ? [] : content.manual_checklist as string[]
  const mediaPlan = platform === "telegram"
    ? [ids.media]
    : platform === "instagram"
      ? (content.carousel as Array<{ media: unknown }>).map((slide) => slide.media)
      : platform === "x"
        ? (content.posts as Array<{ media: unknown[] }>).flatMap((post) => post.media)
        : [content.hero_media]
  return {
    id: ids.revisions[platform],
    platform,
    platform_variant_id: ids.variants[platform],
    content_pack_id: ids.contentPack,
    story_id: ids.story,
    parent_revision_id: null,
    generation_attempt_id: ids.attempts[platform],
    revision_number: 1,
    content,
    content_hash: hashFor(platform),
    evidence_map: [citationWire()],
    manual_checklist: manualChecklist,
    validation_results: [{ gate: `${platform}_schema`, ok: true, reason: null }],
    validation_issues: [],
    media_plan: mediaPlan,
    source_media: [sourceMediaWire()],
    approval_state: "approved",
    approval_note: "Accepted for manual package verification",
    approved_at: "2026-07-13T09:00:00Z",
    created_by: "generation",
    origin: "generation",
    provider_profile: { id: ids.provider, name: "Offline acceptance provider", provider_type: "codex" },
    resolved_model: "offline-acceptance-model",
    prompt_version: {
      id: ids.prompts[platform],
      version: 1,
      output_schema_version: `${platform}_pack.v1`,
      checksum_sha256: hashFor(platform),
    },
    created_at: now,
  }
}

function contentWire(platform: Platform): Record<string, unknown> {
  if (platform === "telegram") return {
    body: "<strong>Agent release</strong> is verified against the cited report.",
    parse_mode: "HTML",
    buttons: [{ text: "Read report", url: evidenceUrl }],
    source_item_id: null,
    source_url: evidenceUrl,
    media_policy: "preserve",
    media_asset_ids: [ids.media],
    direction: "ltr",
    dry_run: false,
  }
  if (platform === "instagram") return {
    hook: "Agent release: the verified details",
    caption: "A grounded Instagram caption based on the cited report.",
    cta: "Read the cited report",
    hashtags: ["#NewsCraft", "#AgentRelease"],
    alt_text: "A report card summarizing the verified agent release",
    carousel: [{ order: 1, headline: "Agent release", body: "Verified details from the public report", media: mediaAssignment("slide") }],
    citations: [citationWire()],
    manual_checklist: ["Verify Instagram copy and carousel"],
  }
  if (platform === "x") return {
    mode: "thread",
    posts: [
      { order: 1, text: "Agent release: verified details from the cited report.", media: [], citations: [citationWire()] },
      { order: 2, text: "Read the exact source for context.", media: [mediaAssignment("post")], citations: [citationWire()] },
    ],
    link_strategy: "last_post",
    manual_checklist: ["Verify X thread order and links"],
  }
  return {
    title: "Agent release",
    slug: "agent-release",
    excerpt: "Verified details about the agent release.",
    body_markdown: "# Agent release\n\nThe exact grounded article body cites the public report.",
    headings: ["Agent release", "Why it matters"],
    citations: [citationWire()],
    tags: ["news", "agents"],
    seo_description: "Verified details and context about the agent release from the cited public report.",
    hero_media: mediaAssignment("hero"),
    canonical_sources: [evidenceUrl],
    manual_checklist: ["Verify Blog article and canonical source"],
  }
}

function citationWire() {
  return {
    evidence_snapshot_id: ids.evidence,
    evidence_key: "report:agent-release",
    source_url: evidenceUrl,
    locator: "chars:0-42",
    excerpt_sha256: "a".repeat(64),
  }
}

function mediaAssignment(role: "slide" | "post" | "hero") {
  return {
    media_asset_id: ids.media,
    role,
    order: 1,
    alt_text: "The verified agent release report cover",
    manual_brief: null,
    image_prompt: null,
  }
}

function sourceMediaWire() {
  return {
    id: ids.media,
    kind: "image",
    mime_type: "image/jpeg",
    width: 1200,
    height: 800,
    duration_seconds: null,
    byte_length: 2048,
    checksum_sha256: "b".repeat(64),
    fetch_status: "downloaded",
    available: true,
    role: "hero",
    order: 0,
  }
}

function evidenceWire() {
  return {
    id: ids.evidence,
    evidence_key: "report:agent-release",
    title: "Agent release report",
    content_text: "The verified public report describes the agent release and its exact operational context.",
    content_sha256: "c".repeat(64),
    source_url: evidenceUrl,
    authors: ["NewsCraft Research Desk"],
    published_at: "2026-07-13T07:00:00Z",
    captured_at: now,
  }
}

function providerWire() {
  return {
    id: ids.provider,
    name: "Offline acceptance provider",
    provider_type: "codex",
    default_model: "offline-acceptance-model",
    capabilities: { generation: true, research: false },
    unavailability_codes: [],
  }
}

function exportOutcomeWire() {
  const formats = [
    { kind: "json", extension: "json", byteLength: 128 },
    { kind: "markdown", extension: "md", byteLength: 256 },
    { kind: "html", extension: "html", byteLength: 384 },
  ] as const
  const files = platforms.flatMap((platform) => formats.map((format) => ({
    file_name: `${platform}/${ids.revisions[platform]}/content.${format.extension}`,
    sha256: hashFor(platform),
    byte_length: format.byteLength,
    kind: format.kind,
    platform,
    revision_id: ids.revisions[platform],
    media_asset_id: null,
  })))
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
    downloads: [
      `/exports/${ids.exportJob}/download/manifest.json`,
      `/exports/${ids.exportJob}/download/bundle.zip`,
      ...files.map((item) => `/exports/${ids.exportJob}/download/${item.file_name}`),
    ],
    error_code: null,
    error_message: null,
  }
}

function manualPlanWire(state: BackendState) {
  const ready = Object.values(state.checklist).every(Boolean)
  return {
    id: ids.manualPlan,
    platform_variant_revision_id: ids.revisions.instagram,
    platform: "instagram",
    scheduled_for: scheduledFor,
    display_timezone: "Asia/Tehran",
    status: state.planPublished ? "manual_published" : ready ? "ready" : "planned",
    checklist_state: { ...state.checklist },
    external_url: state.planPublished ? publicationUrl : null,
    operator_note: state.planPublished ? "Verified against the approved Instagram revision" : null,
    completed_at: state.planPublished ? completedAt : null,
    created_at: now,
    updated_at: state.planPublished ? completedAt : now,
  }
}

function hashFor(platform: Platform) {
  return ({ telegram: "1", instagram: "2", x: "3", blog: "4" } as const)[platform].repeat(64)
}

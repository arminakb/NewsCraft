import { expect, test, type Page, type Route } from "@playwright/test"

const ids = {
  template: "11111111-1111-4111-8111-111111111111",
  prompt1: "22222222-2222-4222-8222-222222222222",
  prompt2: "22222222-2222-4222-8222-222222222223",
  brand: "33333333-3333-4333-8333-333333333333",
  provider: "44444444-4444-4444-8444-444444444444",
  source: "55555555-5555-4555-8555-555555555555",
  destination: "66666666-6666-4666-8666-666666666666",
  route: "77777777-7777-4777-8777-777777777777",
  dryDraft: "88888888-8888-4888-8888-888888888880",
  draft1: "88888888-8888-4888-8888-888888888881",
  draft2: "88888888-8888-4888-8888-888888888882",
  publishJob: "99999999-9999-4999-8999-999999999991",
  workflowJob: "99999999-9999-4999-8999-999999999992",
}

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const) {
  test(`${viewport.name} completes the Telegram newsroom flow without horizontal overflow`, async ({ page }) => {
    test.setTimeout(60_000)
    const backend = await installTelegramBackend(page)
    await page.setViewportSize(viewport)

    await page.goto("/settings/content")
    await expect(page.getByRole("heading", { name: "Content settings" })).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.getByLabel("Custom instructions").fill("Preserve verified facts and write concise Persian copy")
    await page.getByRole("button", { name: "Create prompt version" }).click()
    await expect(page.getByText("Version 2", { exact: true })).toBeVisible()
    await page.getByRole("checkbox", { name: "Confirm prompt activation" }).check()
    await page.getByRole("button", { name: "Activate version 2" }).click()
    await expect(page.getByRole("list", { name: "Immutable prompt history" }).getByRole("listitem").filter({ hasText: "Version 2" })).toContainText("Active ·")
    expect(backend.requests.promptVersion).toMatchObject({
      system_template: "Preserve verified facts and write concise Persian copy",
    })
    for (const placeholder of [
      "source_text", "source_url", "source_channel", "language", "direction", "attribution_policy", "custom_footer",
    ]) expect(backend.requests.promptVersion.user_template).toContain(`{${placeholder}}`)

    await navigate(page, "Automations", viewport.name === "mobile")
    await page.getByRole("link", { name: "New automation" }).click()
    await expect(page.getByRole("heading", { name: "New Telegram automation" })).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await expect(page.getByLabel("Access mode")).toHaveValue("public_html")
    await expect(page.getByLabel("Research mode")).toHaveValue("off")
    await expect(page.getByLabel("Media policy")).toHaveValue("preserve")
    await expect(page.getByLabel("Publishing policy")).toHaveValue("review_required")
    await expect(page.getByLabel("Poll interval in seconds")).toHaveValue("300")

    await page.getByLabel("Automation name").fill("Persian breaking route")
    await page.getByLabel("Source name").fill("Source newsroom")
    await page.getByLabel("Source channel").fill("source_newsroom")
    await page.getByLabel("Destination name").fill("Main newsroom")
    await page.getByLabel("Destination target").fill("@newscraft")
    await page.getByLabel("Bot token environment variable").fill("TELEGRAM_BOT_TOKEN")
    await page.getByLabel("Publishing policy").selectOption("auto_publish")
    await page.getByRole("checkbox", { name: "Confirm automatic publishing" }).check()
    await page.getByRole("button", { name: "Create and activate" }).click()
    await expect(page).toHaveURL(new RegExp(`/automations/${ids.route}$`))
    await expect(page.getByRole("heading", { name: "Persian breaking route" })).toBeVisible()
    expect(backend.requests.source).toMatchObject({ access_mode: "public_html", channel_ref: "source_newsroom" })
    expect(backend.requests.destination).toMatchObject({ secret_ref: "TELEGRAM_BOT_TOKEN", allow_auto_publish: true })
    expect(backend.requests.route).toMatchObject({
      prompt_template_version_id: ids.prompt2,
      publishing_policy: "auto_publish",
      poll_interval_seconds: 300,
      confirm_auto_publish: true,
    })

    await navigate(page, "Automations", viewport.name === "mobile")
    await page.getByRole("link", { name: "Persian breaking route" }).click()
    await expect(page.getByText("Initializing")).toBeVisible()
    await expect(page.getByText("Last message 90")).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.getByLabel("Source message ID (optional)").fill("91")
    await page.getByRole("button", { name: "Run dry run" }).click()
    await expect(page.getByRole("status", { name: "Latest route action" })).toContainText("Dry run queued")
    expect(backend.requests.dryRun).toEqual({ source_message_id: 91 })

    await navigate(page, "Drafts", viewport.name === "mobile")
    await expect(page.getByText("pending review")).toBeVisible()
    await expect(page.getByText("پیش‌نویس آزمایشی")).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.getByRole("link", { name: "Review exact revision" }).click()
    await expect(page.getByText("Draft dry run blocks publishing")).toBeVisible()
    await expect(page.getByRole("button", { name: "Publish exact revision" })).toBeDisabled()
    expect(backend.requests.publish).toBeUndefined()

    await navigate(page, "Drafts", viewport.name === "mobile")
    // A later route poll produced a live item; reload for the next server-backed list read.
    await page.reload()
    await expect(page.getByText("pending review")).toBeVisible()
    await expect(page.getByText("پیش‌نویس اولیه")).toBeVisible()
    await page.getByRole("link", { name: "Review exact revision" }).click()
    await expect(page.getByText("Captured source evidence")).toBeVisible()
    await expect(page.getByText("image · image/jpeg")).toBeVisible()
    await expect(page.getByLabel("Telegram body")).toHaveAttribute("dir", "rtl")
    await expectNoHorizontalOverflow(page)
    await page.getByLabel("Telegram body").fill("نسخه دوم با زمینه تأییدشده")
    await page.getByRole("button", { name: "Save as new revision" }).click()
    await expect(page).toHaveURL(new RegExp(`/review/${ids.draft2}$`))
    await expect(page.getByRole("heading", { name: "Review Telegram revision 2" })).toBeVisible()
    expect(backend.requests.edit).toMatchObject({ content: { body: "نسخه دوم با زمینه تأییدشده" } })

    await page.getByRole("button", { name: "Approve exact revision" }).click()
    await expect(page.locator("[data-notice-title]", { hasText: "Revision approved" })).toBeVisible()
    expect(backend.requests.approve).toEqual({ content_hash: "b".repeat(64) })
    const publish = page.getByRole("button", { name: "Publish exact revision" })
    await expect(publish).toBeEnabled()
    await publish.click()
    await expect(page.getByRole("status").filter({ hasText: ids.publishJob })).toContainText("Queued")
    expect(backend.requests.publish).toEqual({ content_hash: "b".repeat(64) })

    await navigate(page, "Today", viewport.name === "mobile")
    const outcomes = page.getByRole("region", { name: "Telegram publication outcomes" })
    await expect(outcomes).toContainText("Remote IDs: 501, 502")
    await expect(outcomes.getByRole("link", { name: "Open published Telegram post" })).toHaveAttribute(
      "href", "https://t.me/newscraft/501"
    )
    await expectNoHorizontalOverflow(page)

    await navigate(page, "Automations", viewport.name === "mobile")
    await page.getByRole("link", { name: "Persian breaking route" }).click()
    await page.getByRole("button", { name: "Pause route" }).click()
    await expect(page.getByRole("button", { name: "Resume route" })).toBeVisible()
    await page.getByRole("button", { name: "Resume route" }).click()
    await expect(page.getByRole("button", { name: "Pause route" })).toBeVisible()
    await expect(page.getByLabel("Message count")).toHaveValue("20")
    await page.getByRole("button", { name: "Queue backfill" }).click()
    await expect(page.getByRole("status", { name: "Latest route action" })).toContainText("Backfill queued")
    expect(backend.requests.backfill).toEqual({ count: 20 })

    await navigate(page, "Today", viewport.name === "mobile")
    await page.getByRole("button", { name: "Pause automations" }).click()
    await expect(page.getByRole("button", { name: "Resume automations" })).toBeVisible()
    expect(backend.requests.control).toMatchObject({ global_pause: true })
    await navigate(page, "Automations", viewport.name === "mobile")
    await page.getByRole("link", { name: "Persian breaking route" }).click()
    await expect(page.getByText("Review Required")).toBeVisible()

    await expectNoHorizontalOverflow(page)
  })
}

test("ambiguous Telegram delivery requires operator reconciliation and has no generic retry", async ({ page }) => {
  const backend = await installTelegramBackend(page, { reconciliation: true })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/")

  const outcomes = page.getByRole("region", { name: "Telegram publication outcomes" })
  await expect(outcomes.getByText("Reconciliation required", { exact: true }).first()).toBeVisible()
  await expect(outcomes).toContainText("Automatic retry is disabled")
  await expect(outcomes.getByRole("button", { name: /retry/i })).toHaveCount(0)
  const remoteIds = outcomes.getByLabel("Verified remote message IDs")
  await remoteIds.fill("501, bad, 502")
  await expect(outcomes.getByRole("button", { name: "Confirm published IDs" })).toBeDisabled()
  await expect(outcomes.getByRole("alert")).toContainText("positive, unique message IDs")
  await remoteIds.fill("501, 502")
  await outcomes.getByRole("button", { name: "Confirm published IDs" }).click()
  await expect(outcomes).toContainText("Remote IDs: 501, 502")
  expect(backend.requests.reconcile).toEqual({ outcome: "published", remote_message_ids: [501, 502] })
})

type BackendState = {
  prompt2Created: boolean
  prompt2Active: boolean
  routeCreated: boolean
  routeInitialized: boolean
  routePaused: boolean
  dryRun: boolean
  dryRunReviewed: boolean
  childCreated: boolean
  approved: boolean
  published: boolean
  publishQueued: boolean
  controlPaused: boolean
  reconciliation: boolean
  reconciled: boolean
  requests: Record<string, any>
}

async function installTelegramBackend(page: Page, options: { reconciliation?: boolean } = {}) {
  const state: BackendState = {
    prompt2Created: false,
    prompt2Active: false,
    routeCreated: false,
    routeInitialized: false,
    routePaused: false,
    dryRun: false,
    dryRunReviewed: false,
    childCreated: false,
    approved: false,
    published: false,
    publishQueued: false,
    controlPaused: false,
    reconciliation: Boolean(options.reconciliation),
    reconciled: false,
    requests: {},
  }
  if (state.reconciliation) state.published = false

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace("/api/backend", "")
    const method = request.method()
    const body = method === "POST" || method === "PATCH" ? request.postDataJSON() : undefined

    if (path.includes("/telegram/drafts/") && path.includes("/media/") && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64"),
      })
    }

    if (path === "/automation-control") {
      if (method === "PATCH") {
        state.requests.control = body
        state.controlPaused = Boolean(body.global_pause)
      }
      return json(route, automationControl(state))
    }
    if (path === "/jobs/summary") return json(route, { queued: 0, running: 0, attention: 0, succeeded_today: 1 })
    if (path === "/jobs") return json(route, { items: [] })

    if (path === "/brand-profiles") return json(route, [brand()])
    if (path === "/prompt-templates") return json(route, [promptTemplate()])
    if (path === `/prompt-templates/${ids.template}/versions`) {
      if (method === "POST") {
        state.requests.promptVersion = body
        state.prompt2Created = true
        return json(route, promptVersion(2, false), 201)
      }
      return json(route, [
        ...(state.prompt2Created ? [promptVersion(2, state.prompt2Active)] : []),
        promptVersion(1, !state.prompt2Active),
      ])
    }
    if (path === `/prompt-template-versions/${ids.prompt2}/activate`) {
      state.prompt2Active = true
      return json(route, promptVersion(2, true))
    }
    if (path === "/ai-provider-profiles") return json(route, [provider()])

    if (path === "/telegram/sources" && method === "POST") {
      state.requests.source = body
      return json(route, source(), 201)
    }
    if (path === "/telegram/destinations") {
      if (method === "POST") {
        state.requests.destination = body
        return json(route, { destination: destination(), job: accepted("telegram.destination.check") }, 202)
      }
      return json(route, [destination()])
    }
    if (path === "/telegram/automations/options") return json(route, automationOptions(state))
    if (path === "/telegram/automations") {
      if (method === "POST") {
        state.requests.route = body
        state.routeCreated = true
        return json(route, telegramRoute(state), 201)
      }
      return json(route, state.routeCreated || state.reconciliation ? [telegramRoute(state)] : [])
    }
    if (path === `/telegram/automations/${ids.route}`) {
      state.routeInitialized = true
      return json(route, telegramRoute(state))
    }
    if (path === `/telegram/automations/${ids.route}/activate`) {
      state.routeCreated = true
      state.routeInitialized = false
      return json(route, {
        route: telegramRoute(state, { status: "initializing", activation_message_id: null, last_message_id: null }),
        job: accepted("telegram.route.initialize"),
      }, 202)
    }
    if (path === `/telegram/automations/${ids.route}/pause`) {
      state.routePaused = true
      return json(route, telegramRoute(state))
    }
    if (path === `/telegram/automations/${ids.route}/resume`) {
      state.routePaused = false
      return json(route, telegramRoute(state))
    }
    if (path === `/telegram/automations/${ids.route}/dry-run`) {
      state.requests.dryRun = body
      state.dryRun = true
      return json(route, { route: telegramRoute(state), job: accepted("telegram.route.dry_run") }, 202)
    }
    if (path === `/telegram/automations/${ids.route}/backfill`) {
      state.requests.backfill = body
      return json(route, { route: telegramRoute(state), job: accepted("telegram.route.backfill") }, 202)
    }
    if (path === `/telegram/automations/${ids.route}/dispatches`) return json(route, dispatches(state))

    if (path === "/telegram/drafts") {
      return json(route, [state.dryRun && !state.dryRunReviewed ? dryRunDraft(state) : draft(state.childCreated ? 2 : 1, state)])
    }
    if (path === `/telegram/drafts/${ids.dryDraft}`) {
      state.dryRunReviewed = true
      return json(route, dryRunDraft(state))
    }
    if (path === `/telegram/drafts/${ids.draft1}`) return json(route, draft(1, state))
    if (path === `/telegram/drafts/${ids.draft1}/revisions`) {
      state.requests.edit = body
      state.childCreated = true
      return json(route, draft(2, state), 201)
    }
    if (path === `/telegram/drafts/${ids.draft2}`) return json(route, draft(2, state))
    if (path === `/telegram/drafts/${ids.draft2}/approve`) {
      state.requests.approve = body
      state.approved = true
      return json(route, draft(2, state))
    }
    if (path === `/telegram/drafts/${ids.draft2}/publish`) {
      state.requests.publish = body
      state.publishQueued = true
      return json(route, {
        revision: draft(2, state),
        job: { publish_job_id: ids.publishJob, workflow_job_id: ids.workflowJob, status: "queued" },
      }, 202)
    }
    if (path === `/telegram/publish-jobs/${ids.publishJob}` && method === "GET") {
      const result = publishJob(state)
      if (state.publishQueued && !state.published) state.published = true
      return json(route, result)
    }
    if (path === `/telegram/publish-jobs/${ids.publishJob}/reconcile`) {
      state.requests.reconcile = body
      state.reconciled = true
      state.published = true
      return json(route, publication())
    }

    return json(route, { detail: `Unhandled deterministic route: ${method} ${path}` }, 501)
  })
  return state
}

async function navigate(page: Page, label: string, mobile: boolean) {
  if (mobile) {
    await page.getByRole("button", { name: "Open navigation" }).click()
    const dialog = page.getByRole("dialog", { name: "Newsroom navigation" })
    await expect(dialog).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await dialog.getByRole("link", { name: label, exact: true }).click()
  } else {
    await page.getByRole("navigation", { name: "Newsroom navigation" }).getByRole("link", { name: label, exact: true }).click()
  }
  const expectedPath = label === "Today" ? "/" : label === "Automations" ? "/automations" : label === "Drafts" ? "/drafts" : null
  if (expectedPath) await page.waitForURL((url) => url.pathname === expectedPath)
}

async function hasHorizontalOverflow(page: Page) {
  return page.evaluate(() =>
    document.documentElement.scrollWidth > document.documentElement.clientWidth
    || document.body.scrollWidth > window.innerWidth
  )
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => hasHorizontalOverflow(page)).toBe(false)
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
}

function automationControl(state: BackendState) {
  return {
    global_pause: state.controlPaused,
    dry_run: false,
    pause_reason: state.controlPaused ? "Paused from Newsroom" : null,
    paused_at: state.controlPaused ? "2026-07-12T09:00:00Z" : null,
    updated_at: "2026-07-12T09:00:00Z",
  }
}

function brand() {
  return {
    id: ids.brand, name: "Persian newsroom", output_language: "fa", tone: "neutral",
    editorial_rules: [], attribution_rules: {}, default_hashtags: [], platform_preferences: {}, is_default: true,
  }
}

function promptTemplate() {
  return { id: ids.template, purpose_key: "telegram_rewrite", name: "Telegram rewrite", description: "Immutable prompt" }
}

function promptVersion(version: 1 | 2, active: boolean) {
  return {
    id: version === 1 ? ids.prompt1 : ids.prompt2,
    prompt_template_id: ids.template,
    version,
    system_template: version === 1 ? "Rewrite faithfully" : "Preserve verified facts and write concise Persian copy",
    user_template: "{source_text} {source_url} {source_channel} {language} {direction} {attribution_policy} {custom_footer}",
    output_schema_version: "telegram_rewrite.v1",
    output_schema: {},
    checksum_sha256: (version === 1 ? "a" : "b").repeat(64),
    is_active: active,
    created_at: "2026-07-12T08:00:00Z",
  }
}

function provider() {
  return {
    id: ids.provider, name: "OpenRouter newsroom", provider_type: "openrouter", default_model: "openai/gpt-5-mini",
    settings: {}, enabled: true, configured: true,
  }
}

function source() {
  return {
    id: ids.source, name: "Source newsroom", channel_ref: "source_newsroom", access_mode: "public_html",
    language_hint: "fa", configured: true,
  }
}

function destination() {
  return {
    id: ids.destination, name: "Main newsroom", target_ref: "@newscraft", enabled: true,
    health_status: "healthy", configured: true, settings: { allow_auto_publish: true },
  }
}

function automationOptions(state: BackendState) {
  return {
    sources: [],
    destinations: [{ id: ids.destination, name: "Main newsroom", health_status: "healthy", allow_auto_publish: true }],
    brand_profiles: [{ id: ids.brand, name: "Persian newsroom" }],
    prompt_template_versions: [{ id: state.prompt2Active ? ids.prompt2 : ids.prompt1, version: state.prompt2Active ? 2 : 1 }],
    ai_provider_profiles: [{ id: ids.provider, name: "OpenRouter newsroom", provider_type: "openrouter", default_model: "openai/gpt-5-mini", configured: true }],
  }
}

function telegramRoute(
  state: BackendState,
  cursorState: { status: string; activation_message_id: number | null; last_message_id: number | null } = {
    status: state.routeInitialized ? "initializing" : "not_initialized",
    activation_message_id: state.routeInitialized ? 90 : null,
    last_message_id: state.routeInitialized ? 90 : null,
  },
) {
  return {
    id: ids.route,
    name: "Persian breaking route",
    source_id: ids.source,
    destination_id: ids.destination,
    brand_profile_id: ids.brand,
    prompt_template_version_id: ids.prompt2,
    ai_provider_profile_id: ids.provider,
    access_mode: "public_html",
    research_mode: "off",
    content_filters: { include_terms: [], exclude_terms: [], min_text_characters: 1, require_media: false },
    media_policy: "preserve",
    attribution_policy: "preserve",
    custom_footer: null,
    publishing_policy: "auto_publish",
    poll_interval_seconds: 300,
    quiet_hours: {},
    retry_policy: { max_attempts: 3, base_delay_seconds: 30, max_delay_seconds: 1800 },
    cursor_state: cursorState,
    enabled: true,
    paused_at: state.routePaused ? "2026-07-12T09:00:00Z" : null,
    last_polled_at: null,
    next_poll_at: "2026-07-12T09:05:00Z",
    created_at: "2026-07-12T08:00:00Z",
    updated_at: "2026-07-12T09:00:00Z",
  }
}

function accepted(kind: string) {
  return { job_id: ids.workflowJob, status: "queued", deduplicated: false, kind }
}

function dispatches(state: BackendState) {
  const rows = []
  if (state.dryRun) rows.push(dispatch(91, "review_required", "dry_run"))
  if (state.controlPaused) rows.unshift(dispatch(92, "review_required", "live"))
  return rows
}

function dispatch(messageId: number, status: string, kind: string) {
  return {
    id: `${ids.route.slice(0, -3)}${messageId}`,
    route_id: ids.route,
    source_item_id: ids.source,
    story_revision_id: ids.draft1,
    source_key: `message:${messageId}`,
    source_fingerprint: "f".repeat(64),
    source_message_ids: [messageId],
    dispatch_kind: kind,
    status,
    generation_run_id: null,
    variant_revision_id: ids.draft1,
    publish_job_id: null,
    error_code: null,
    error_message: null,
    created_at: "2026-07-12T09:00:00Z",
    updated_at: "2026-07-12T09:00:00Z",
  }
}

function draft(version: 1 | 2, state: BackendState) {
  const id = version === 1 ? ids.draft1 : ids.draft2
  const contentHash = (version === 1 ? "a" : "b").repeat(64)
  const reconciles = state.reconciliation && !state.reconciled
  return {
    id,
    platform_variant_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    parent_revision_id: version === 2 ? ids.draft1 : null,
    generation_attempt_id: null,
    revision_number: version,
    content: {
      body: version === 1 ? "پیش‌نویس اولیه" : "نسخه دوم با زمینه تأییدشده",
      parse_mode: "HTML",
      buttons: [],
      source_item_id: ids.source,
      source_url: "https://t.me/source_newsroom/91",
      media_policy: "preserve",
      media_asset_ids: ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"],
      direction: "rtl",
      dry_run: false,
    },
    content_hash: contentHash,
    evidence_map: [{ evidence_snapshot_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", evidence_key: "telegram.source", source_url: "https://t.me/source_newsroom/91", locator: "chars:0-18", excerpt_sha256: "c".repeat(64) }],
    evidence: [{ evidence_snapshot_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", evidence_key: "telegram.source", source_url: "https://t.me/source_newsroom/91", content_text: "متن منبع تأییدشده", content_sha256: "c".repeat(64) }],
    media: [{
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      kind: "image",
      mime_type: "image/jpeg",
      fetch_status: "downloaded",
      checksum_sha256: "d".repeat(64),
      preview_url: `/telegram/drafts/${id}/media/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb`,
    }],
    validation_results: [],
    approval_state: version === 2 && state.approved ? "approved" : "pending_review",
    approval_note: null,
    approved_at: version === 2 && state.approved ? "2026-07-12T09:00:00Z" : null,
    created_by: version === 1 ? "automation" : "operator",
    created_at: "2026-07-12T09:00:00Z",
    route_id: ids.route,
    dispatch_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    publish_job_id: state.published || reconciles ? ids.publishJob : null,
    publish_status: reconciles ? "reconciliation_required" : state.published ? "succeeded" : null,
    publication: state.published && !reconciles ? publication() : null,
  }
}

function dryRunDraft(state: BackendState) {
  const row = draft(1, state)
  return {
    ...row,
    id: ids.dryDraft,
    content: { ...row.content, body: "پیش‌نویس آزمایشی", dry_run: true },
    publish_job_id: null,
    publish_status: null,
    publication: null,
  }
}

function publication() {
  return {
    id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    publish_job_id: ids.publishJob,
    destination_id: ids.destination,
    platform_variant_revision_id: ids.draft2,
    remote_message_ids: [501, 502],
    permalink: "https://t.me/newscraft/501",
    payload_hash: "e".repeat(64),
    published_at: "2026-07-12T09:02:00Z",
    reconciliation_status: "confirmed",
  }
}

function publishJob(state: BackendState) {
  const ambiguous = state.reconciliation && !state.reconciled
  const succeeded = state.published || state.reconciled
  return {
    publish_job_id: ids.publishJob,
    workflow_job_id: ids.workflowJob,
    destination_id: ids.destination,
    platform_variant_revision_id: ids.draft2,
    status: ambiguous ? "reconciliation_required" : succeeded ? "succeeded" : "queued",
    payload_hash: "e".repeat(64),
    scheduled_for: null,
    created_at: "2026-07-12T09:00:00Z",
    updated_at: "2026-07-12T09:01:00Z",
    receipts: [{
      id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
      operation_index: 0,
      operation_key: "telegram:0:ambiguous",
      method: "sendMediaGroup",
      request_hash: "f".repeat(64),
      status: ambiguous ? "ambiguous" : succeeded ? "succeeded" : "pending",
      attempt_count: 1,
      remote_message_ids: succeeded ? [501, 502] : [],
      response_metadata: {},
      next_attempt_at: null,
      ambiguous_at: ambiguous ? "2026-07-12T09:01:00Z" : null,
      completed_at: succeeded ? "2026-07-12T09:02:00Z" : null,
      created_at: "2026-07-12T09:00:00Z",
      updated_at: "2026-07-12T09:01:00Z",
    }],
    publication: succeeded ? publication() : null,
  }
}

import { expect, test } from "@playwright/test"

const ids = {
  story: "10000000-0000-4000-8000-000000000001",
  storyRevision: "10000000-0000-4000-8000-000000000002",
  evidence: "10000000-0000-4000-8000-000000000003",
  contentPack: "10000000-0000-4000-8000-000000000004",
  variant: "10000000-0000-4000-8000-000000000005",
  revision: "10000000-0000-4000-8000-000000000006",
  generationAttempt: "10000000-0000-4000-8000-000000000007",
  provider: "10000000-0000-4000-8000-000000000008",
  brand: "10000000-0000-4000-8000-000000000009",
  canonicalTemplate: "10000000-0000-4000-8000-000000000010",
  telegramTemplate: "10000000-0000-4000-8000-000000000011",
  canonicalPromptVersion: "10000000-0000-4000-8000-000000000012",
  telegramPromptVersion: "10000000-0000-4000-8000-000000000013",
  intakeJob: "10000000-0000-4000-8000-000000000014",
  researchRun: "10000000-0000-4000-8000-000000000015",
  researchJob: "10000000-0000-4000-8000-000000000016",
  packJob: "10000000-0000-4000-8000-000000000017",
}

test("manual text to research to both prompt IDs to exact revision approval", async ({ page }) => {
  let researchStarted = false
  let revisionApproved = false
  let generationBody: Record<string, unknown> | null = null
  const now = "2026-07-12T08:00:00Z"
  const summary = { id: ids.story, title: "Agent release", status: "inbox", primary_language: "en", evidence_count: 1, latest_evidence_at: now, completeness: { complete: false, score: 40, reasons: ["More sources needed"] }, evidence_set_hash: "d".repeat(64), created_at: now, updated_at: now }
  const evidence = { id: ids.evidence, evidence_key: "operator-1", title: "Operator notes", content_text: "Confirmed source material long enough for manual intake and evidence capture.", content_sha256: "e".repeat(64), source_url: null, authors: [], published_at: null, captured_at: now }
  const revision = () => ({
    id: ids.revision,
    platform: "telegram",
    platform_variant_id: ids.variant,
    content_pack_id: ids.contentPack,
    story_id: ids.story,
    parent_revision_id: null,
    generation_attempt_id: ids.generationAttempt,
    revision_number: 1,
    content: { body: "Verified Telegram draft", parse_mode: "HTML", buttons: [], source_item_id: null, media_asset_ids: [], source_url: null, media_policy: "preserve", direction: "ltr", dry_run: false },
    content_hash: "a".repeat(64),
    evidence_map: [{ evidence_snapshot_id: evidence.id, evidence_key: "operator-1", source_url: null, locator: "chars:0-9", excerpt_sha256: "fe00b67b6dd1143f383553116b83dadce3502fb0282c3ec4ddaa99f756119626" }],
    manual_checklist: [],
    validation_results: [{ gate: "telegram_schema", ok: true, reason: null }],
    validation_issues: [],
    media_plan: [],
    source_media: [],
    approval_state: revisionApproved ? "approved" : "pending_review",
    approval_note: null,
    approved_at: revisionApproved ? "2026-07-12T09:00:00Z" : null,
    created_by: "generation",
    origin: "generation",
    provider_profile: { id: ids.provider, name: "Codex CLI", provider_type: "codex" },
    resolved_model: "gpt-5.4",
    prompt_version: { id: ids.telegramPromptVersion, version: 1, output_schema_version: "telegram_pack.v1", checksum_sha256: "f".repeat(64) },
    created_at: now,
  })
  const pack = () => ({ id: ids.contentPack, story_id: ids.story, story_revision_id: ids.storyRevision, brand_profile_id: ids.brand, status: revisionApproved ? "approved" : "pending_review", created_at: now, updated_at: now, variants: [{ id: ids.variant, platform: "telegram", current_revision: revision() }] })

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace("/api/backend", "")
    const method = request.method()
    if (path === "/stories" && method === "GET") return route.fulfill({ json: { items: [summary], next_cursor: null } })
    if (path === "/stories/manual" && method === "POST") return route.fulfill({ status: 202, json: { job_id: ids.intakeJob, status: "queued", deduplicated: false } })
    if (path === `/stories/${ids.story}` && method === "GET") return route.fulfill({ json: summary })
    if (path === `/stories/${ids.story}/evidence` && method === "GET") return route.fulfill({ json: [evidence] })
    if (path === `/stories/${ids.story}/research-runs` && method === "POST") { researchStarted = true; return route.fulfill({ status: 202, json: { disposition: "enqueued", run_id: ids.researchRun, job_id: ids.researchJob, completeness: summary.completeness } }) }
    if (path === `/stories/${ids.story}/research-runs` && method === "GET") return route.fulfill({ json: { items: researchStarted ? [{ id: ids.researchRun, story_id: ids.story, requested_mode: "manual", status: "succeeded", provider: { id: ids.provider, name: "Codex CLI", provider_type: "codex" }, budget: {}, completeness: { complete: true, score: 100, reasons: [] }, sources: [], result_revision_id: ids.storyRevision }] : [] } })
    if (path === "/ai-provider-profiles" && method === "GET") return route.fulfill({ json: [{ id: ids.provider, name: "Codex CLI", provider_type: "codex", default_model: "gpt-5.4", capabilities: { generation: true, research: true }, unavailability_codes: [] }] })
    if (path === "/brand-profiles" && method === "GET") return route.fulfill({ json: [{ id: ids.brand, name: "News desk", is_default: true }] })
    if (path === "/prompt-templates" && method === "GET") return route.fulfill({ json: [{ id: ids.canonicalTemplate, purpose_key: "canonical_story" }, { id: ids.telegramTemplate, purpose_key: "telegram_pack" }] })
    if (path === `/prompt-templates/${ids.canonicalTemplate}/versions`) return route.fulfill({ json: [{ id: ids.canonicalPromptVersion, version: 1, checksum_sha256: "c".repeat(64), is_active: true }] })
    if (path === `/prompt-templates/${ids.telegramTemplate}/versions`) return route.fulfill({ json: [{ id: ids.telegramPromptVersion, version: 1, checksum_sha256: "f".repeat(64), is_active: true }] })
    if (path === `/stories/${ids.story}/content-packs` && method === "POST") { generationBody = request.postDataJSON(); return route.fulfill({ status: 202, json: { job_id: ids.packJob, status: "queued", deduplicated: false } }) }
    if (path === `/platform-variant-revisions/${ids.revision}` && method === "GET") return route.fulfill({ json: revision() })
    if (path === `/content-packs/${ids.contentPack}`) return route.fulfill({ json: pack() })
    if (path === `/platform-variants/${ids.variant}/revisions`) return route.fulfill({ json: [revision()] })
    if (path === `/platform-variant-revisions/${ids.revision}/approve` && method === "POST") { revisionApproved = true; return route.fulfill({ json: revision() }) }
    if (path === `/telegram/drafts/${ids.revision}`) return route.fulfill({ json: { ...revision(), evidence: [{ evidence_snapshot_id: evidence.id, evidence_key: "operator-1", source_url: null, content_text: evidence.content_text, content_sha256: evidence.content_sha256 }], media: [], route_id: null, dispatch_id: null, publish_job_id: null, publish_status: null, publication: null } })
    if (path === "/telegram/destinations") return route.fulfill({ json: [] })
    if (path === "/automation-control") return route.fulfill({ json: { global_pause: false, dry_run: false, pause_reason: null, paused_at: null, updated_at: now } })
    return route.fulfill({ status: 501, json: { detail: `Unhandled ${method} ${path}` } })
  })

  await page.goto("/inbox")
  await page.getByRole("button", { name: "Add story" }).click()
  await page.getByRole("tab", { name: "Text" }).click()
  await page.getByLabel("Story title").fill("Agent release")
  await page.getByLabel("Story text").fill(evidence.content_text)
  await page.getByLabel("Source label").fill("Operator notes")
  await page.getByRole("dialog", { name: "Add story manually" }).getByRole("button", { name: "Add story" }).click()
  await expect(page.getByText("Intake queued", { exact: false })).toBeVisible()
  await page.getByRole("button", { name: "Research more" }).click()
  await page.getByRole("dialog", { name: "Research story" }).getByRole("button", { name: "Research more" }).click()
  await expect(page.getByText("Research completed")).toBeVisible()
  await page.getByRole("button", { name: "Close research" }).click()
  await page.getByRole("button", { name: "Open Agent release" }).click()
  await page.getByLabel("Canonical story prompt").selectOption(ids.canonicalPromptVersion)
  await page.getByLabel("Telegram pack prompt").selectOption(ids.telegramPromptVersion)
  await page.getByRole("button", { name: "Generate Telegram pack" }).click()
  await expect(page.getByText(/Content pack queued/)).toBeVisible()
  expect(generationBody).toMatchObject({ canonical_prompt_template_version_id: ids.canonicalPromptVersion, platform_prompt_template_version_id: ids.telegramPromptVersion, generation_provider_profile_id: ids.provider, research_run_id: ids.researchRun })

  await page.goto(`/drafts/${ids.contentPack}`)
  await page.getByLabel("Telegram message").fill("Unsaved browser Back edit")
  const canceledBackDialog = page.waitForEvent("dialog")
  await page.evaluate(() => history.back())
  const canceledBack = await canceledBackDialog
  expect(canceledBack.type()).toBe("beforeunload")
  await canceledBack.dismiss()
  await expect(page).toHaveURL(new RegExp(`/drafts/${ids.contentPack}$`))
  await expect(page.getByLabel("Telegram message")).toHaveValue("Unsaved browser Back edit")

  const confirmedBackDialog = page.waitForEvent("dialog")
  await page.evaluate(() => history.back())
  const confirmedBack = await confirmedBackDialog
  expect(confirmedBack.type()).toBe("beforeunload")
  await confirmedBack.accept()
  await expect(page).toHaveURL(/\/inbox$/)

  await page.goto(`/review/${ids.revision}`)
  await page.getByLabel("Telegram body").fill("Unsaved legacy editor Back edit")
  const canceledLegacyBackDialog = page.waitForEvent("dialog")
  await page.evaluate(() => history.back())
  const canceledLegacyBack = await canceledLegacyBackDialog
  expect(canceledLegacyBack.type()).toBe("beforeunload")
  await canceledLegacyBack.dismiss()
  await expect(page).toHaveURL(new RegExp(`/review/${ids.revision}$`))
  await expect(page.getByLabel("Telegram body")).toHaveValue("Unsaved legacy editor Back edit")

  const confirmedLegacyBackDialog = page.waitForEvent("dialog")
  await page.evaluate(() => history.back())
  const confirmedLegacyBack = await confirmedLegacyBackDialog
  expect(confirmedLegacyBack.type()).toBe("beforeunload")
  await confirmedLegacyBack.accept()
  await expect(page).toHaveURL(/\/inbox$/)

  await page.goto(`/review/${ids.revision}`)
  await expect(page.getByLabel("Telegram message")).toHaveValue("Verified Telegram draft")
  await page.getByRole("button", { name: "Approve revision" }).click()
  await expect(page.getByText("Revision approved")).toBeVisible()
})

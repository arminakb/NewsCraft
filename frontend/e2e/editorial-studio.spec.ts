import { expect, test } from "@playwright/test"

test("manual text to research to both prompt IDs to exact revision approval", async ({ page }) => {
  let researchStarted = false
  let generationBody: Record<string, unknown> | null = null
  const now = "2026-07-12T08:00:00Z"
  const summary = { id: "story-1", title: "Agent release", status: "inbox", primary_language: "en", evidence_count: 1, latest_evidence_at: now, completeness: { complete: false, score: 40, reasons: ["More sources needed"] }, evidence_set_hash: "d".repeat(64), created_at: now, updated_at: now }
  const evidence = { id: "51111111-1111-4111-8111-111111111111", evidence_key: "operator-1", title: "Operator notes", content_text: "Confirmed source material long enough for manual intake and evidence capture.", content_sha256: "e".repeat(64), source_url: null, authors: [], published_at: null, captured_at: now }
  const revision = { id: "rev-1", platform_variant_id: "variant-1", content_pack_id: "pack-1", story_id: "story-1", parent_revision_id: null, generation_attempt_id: "attempt-1", revision_number: 1, content: { body: "Verified Telegram draft", parse_mode: "HTML", buttons: [], source_item_id: null, media_asset_ids: [], source_url: null, media_policy: "preserve", direction: "ltr", dry_run: false }, content_hash: "a".repeat(64), evidence_map: [{ evidence_snapshot_id: evidence.id, evidence_key: "operator-1", source_url: null, locator: "chars:0-9", excerpt_sha256: "fe00b67b6dd1143f383553116b83dadce3502fb0282c3ec4ddaa99f756119626" }], validation_results: [{ gate: "telegram_schema", ok: true, reason: null }], approval_state: "pending_review", approval_note: null, approved_at: null, created_by: "generation", origin: "generation", provider_profile: { id: "provider-1", name: "Codex CLI", provider_type: "codex" }, resolved_model: "gpt-5.4", created_at: now }
  const pack = { id: "pack-1", story_id: "story-1", story_revision_id: "story-rev-2", brand_profile_id: "brand-1", status: "pending_review", created_at: now, updated_at: now, variants: [{ id: "variant-1", platform: "telegram" }] }

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace("/api/backend", "")
    const method = request.method()
    if (path === "/stories" && method === "GET") return route.fulfill({ json: { items: [summary], next_cursor: null } })
    if (path === "/stories/manual" && method === "POST") return route.fulfill({ status: 202, json: { job_id: "intake-job", status: "queued", deduplicated: false } })
    if (path === "/stories/story-1" && method === "GET") return route.fulfill({ json: summary })
    if (path === "/stories/story-1/evidence" && method === "GET") return route.fulfill({ json: [evidence] })
    if (path === "/stories/story-1/research-runs" && method === "POST") { researchStarted = true; return route.fulfill({ status: 202, json: { disposition: "enqueued", run_id: "run-1", job_id: "research-job", completeness: summary.completeness } }) }
    if (path === "/stories/story-1/research-runs" && method === "GET") return route.fulfill({ json: { items: researchStarted ? [{ id: "run-1", story_id: "story-1", requested_mode: "manual", status: "succeeded", provider: { id: "provider-1", name: "Codex CLI", provider_type: "codex" }, budget: {}, completeness: { complete: true, score: 100, reasons: [] }, sources: [], result_revision_id: "story-rev-2" }] : [] } })
    if (path === "/ai-provider-profiles" && method === "GET") return route.fulfill({ json: [{ id: "provider-1", name: "Codex CLI", provider_type: "codex", default_model: "gpt-5.4", capabilities: { generation: true, research: true }, unavailability_codes: [] }] })
    if (path === "/brand-profiles" && method === "GET") return route.fulfill({ json: [{ id: "brand-1", name: "News desk", is_default: true }] })
    if (path === "/prompt-templates" && method === "GET") return route.fulfill({ json: [{ id: "template-c", purpose_key: "canonical_story" }, { id: "template-t", purpose_key: "telegram_pack" }] })
    if (path === "/prompt-templates/template-c/versions") return route.fulfill({ json: [{ id: "canonical-story-v1", version: 1, checksum_sha256: "c".repeat(64), is_active: true }] })
    if (path === "/prompt-templates/template-t/versions") return route.fulfill({ json: [{ id: "telegram-pack-v1", version: 1, checksum_sha256: "f".repeat(64), is_active: true }] })
    if (path === "/stories/story-1/content-packs" && method === "POST") { generationBody = request.postDataJSON(); return route.fulfill({ status: 202, json: { job_id: "pack-job", status: "queued", deduplicated: false } }) }
    if (path === "/platform-variant-revisions/rev-1" && method === "GET") return route.fulfill({ json: revision })
    if (path === "/content-packs/pack-1") return route.fulfill({ json: pack })
    if (path === "/platform-variants/variant-1/revisions") return route.fulfill({ json: [revision] })
    if (path === "/platform-variant-revisions/rev-1/approve" && method === "POST") return route.fulfill({ json: { ...revision, approval_state: "approved", approved_at: "2026-07-12T09:00:00Z" } })
    if (path === "/telegram/drafts/rev-1") return route.fulfill({ json: { ...revision, platform_variant_id: "variant-1", evidence: [{ evidence_snapshot_id: evidence.id, evidence_key: "operator-1", source_url: null, content_text: evidence.content_text, content_sha256: evidence.content_sha256 }], media: [], route_id: null, dispatch_id: null, publish_job_id: null, publish_status: null, publication: null } })
    if (path === "/telegram/destinations") return route.fulfill({ json: [] })
    if (path === "/automation-control") return route.fulfill({ json: { global_pause: false, dry_run: false, pause_reason: null, paused_at: null, updated_at: now } })
    return route.fulfill({ status: 404, json: { detail: `Unhandled ${method} ${path}` } })
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
  await page.getByLabel("Canonical story prompt").selectOption("canonical-story-v1")
  await page.getByLabel("Telegram pack prompt").selectOption("telegram-pack-v1")
  await page.getByRole("button", { name: "Generate Telegram pack" }).click()
  await expect(page.getByText(/Content pack queued/)).toBeVisible()
  expect(generationBody).toMatchObject({ canonical_prompt_template_version_id: "canonical-story-v1", platform_prompt_template_version_id: "telegram-pack-v1", generation_provider_profile_id: "provider-1", research_run_id: "run-1" })

  await page.goto("/drafts/pack-1")
  await page.getByLabel("Telegram message").fill("Unsaved browser Back edit")
  const canceledBackDialog = page.waitForEvent("dialog")
  await page.evaluate(() => history.back())
  const canceledBack = await canceledBackDialog
  expect(canceledBack.type()).toBe("beforeunload")
  await canceledBack.dismiss()
  await expect(page).toHaveURL(/\/drafts\/pack-1$/)
  await expect(page.getByLabel("Telegram message")).toHaveValue("Unsaved browser Back edit")

  const confirmedBackDialog = page.waitForEvent("dialog")
  await page.evaluate(() => history.back())
  const confirmedBack = await confirmedBackDialog
  expect(confirmedBack.type()).toBe("beforeunload")
  await confirmedBack.accept()
  await expect(page).toHaveURL(/\/inbox$/)

  await page.goto("/review/rev-1")
  await page.getByLabel("Telegram body").fill("Unsaved legacy editor Back edit")
  const canceledLegacyBackDialog = page.waitForEvent("dialog")
  await page.evaluate(() => history.back())
  const canceledLegacyBack = await canceledLegacyBackDialog
  expect(canceledLegacyBack.type()).toBe("beforeunload")
  await canceledLegacyBack.dismiss()
  await expect(page).toHaveURL(/\/review\/rev-1$/)
  await expect(page.getByLabel("Telegram body")).toHaveValue("Unsaved legacy editor Back edit")

  const confirmedLegacyBackDialog = page.waitForEvent("dialog")
  await page.evaluate(() => history.back())
  const confirmedLegacyBack = await confirmedLegacyBackDialog
  expect(confirmedLegacyBack.type()).toBe("beforeunload")
  await confirmedLegacyBack.accept()
  await expect(page).toHaveURL(/\/inbox$/)

  await page.goto("/review/rev-1")
  await expect(page.getByLabel("Telegram message")).toHaveValue("Verified Telegram draft")
  await page.getByRole("button", { name: "Approve revision" }).click()
  await expect(page.getByText("Revision approved")).toBeVisible()
})

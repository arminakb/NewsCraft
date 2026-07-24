import {
  activatePromptVersion,
  activateTelegramRoute,
  approveTelegramDraft,
  backfillTelegramRoute,
  createAIProviderProfile,
  createBrandProfile,
  createPromptVersion,
  createTelegramDestination,
  createTelegramRoute,
  createTelegramSource,
  dryRunTelegramRoute,
  editTelegramDraft,
  getPromptVersions,
  getTelegramAutomationOptions,
  getTelegramDrafts,
  getTelegramPublishJob,
  pauseTelegramRoute,
  publishTelegramDraft,
  reconcileTelegramPublishJob,
  rejectTelegramDraft,
  resumeTelegramRoute,
} from "@/features/automations/telegram-api"
import { queryKeys } from "@/lib/query-keys"

const ids = {
  source: "11111111-1111-4111-8111-111111111111",
  destination: "22222222-2222-4222-8222-222222222222",
  brand: "33333333-3333-4333-8333-333333333333",
  prompt: "44444444-4444-4444-8444-444444444444",
  provider: "55555555-5555-4555-8555-555555555555",
  route: "66666666-6666-4666-8666-666666666666",
  revision: "77777777-7777-4777-8777-777777777777",
  publishJob: "88888888-8888-4888-8888-888888888888",
}

const backendAvailableState = {
  status: "available",
  owner: "worker-source-generation",
  observed_at: "2026-07-18T08:00:00Z",
  expires_at: "2026-07-18T08:02:00Z",
  failure_code: "available",
}
const availableState = {
  status: "available",
  owner: "worker-source-generation",
  observedAt: "2026-07-18T08:00:00Z",
  expiresAt: "2026-07-18T08:02:00Z",
  failureCode: "available",
}

const backendRoute = {
  id: ids.route,
  name: "Public to newsroom",
  source_id: ids.source,
  destination_id: ids.destination,
  brand_profile_id: ids.brand,
  prompt_template_version_id: ids.prompt,
  prompt_policy: "pinned",
  ai_provider_profile_id: ids.provider,
  access_mode: "public_html",
  research_mode: "off",
  content_filters: { include_terms: ["news"] },
  media_policy: "preserve",
  attribution_policy: "custom",
  custom_footer: "Source",
  publishing_policy: "review_required",
  poll_interval_seconds: 300,
  quiet_hours: {},
  retry_policy: { max_attempts: 3, base_delay_seconds: 30, max_delay_seconds: 1800 },
  cursor_state: { status: "ready", last_message_id: 90 },
  enabled: true,
  paused_at: null,
  last_polled_at: "2026-07-12T10:00:00Z",
  next_poll_at: "2026-07-12T10:05:00Z",
  created_at: "2026-07-12T09:00:00Z",
  updated_at: "2026-07-12T10:00:00Z",
}

describe("Telegram automation API", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("maps safe automation options without inventing secret references", async () => {
    const fetchSpy = stubFetch({
      sources: [{ id: ids.source, name: "Wire", access_mode: "public_html", capability_state: backendAvailableState }],
      destinations: [
        { id: ids.destination, name: "Newsroom", health_status: "healthy", allow_auto_publish: false, capability_state: backendAvailableState },
      ],
      brand_profiles: [{ id: ids.brand, name: "Main" }],
      prompt_template_versions: [{ id: ids.prompt, version: 2, is_active: true, checksum_sha256: "a".repeat(64) }],
      ai_provider_profiles: [
        { id: ids.provider, name: "OpenRouter", provider_type: "openrouter", default_model: "openai/gpt", configured: true, capabilities: { generation: true, research: true }, capability_states: { generation: backendAvailableState, research: backendAvailableState } },
      ],
      secret_ref: "MUST_NOT_CROSS_BOUNDARY",
    })

    await expect(getTelegramAutomationOptions()).resolves.toEqual({
      sources: [{ id: ids.source, name: "Wire", accessMode: "public_html", capabilityState: availableState }],
      destinations: [
        { id: ids.destination, name: "Newsroom", healthStatus: "healthy", allowAutoPublish: false, capabilityState: availableState },
      ],
      brandProfiles: [{ id: ids.brand, name: "Main" }],
      promptTemplateVersions: [{ id: ids.prompt, version: 2, isActive: true, checksumSha256: "a".repeat(64) }],
      aiProviderProfiles: [
        { id: ids.provider, name: "OpenRouter", providerType: "openrouter", defaultModel: "openai/gpt", configured: true, capabilities: { generation: true, research: true }, capabilityStates: { generation: availableState, research: availableState } },
      ],
    })
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/telegram/automations/options", undefined)
  })

  it("creates source, destination, and fully mapped route with exact snake-case requests", async () => {
    const fetchSpy = stubFetchSequence(
      { id: ids.source, name: "Wire", channel_ref: "@wire", access_mode: "mtproto_user", language_hint: "fa", configured: true, capability_state: backendAvailableState },
      {
        destination: { id: ids.destination, name: "Newsroom", target_ref: "@news", enabled: true, health_status: "unknown", configured: true, capability_state: backendAvailableState, settings: { allow_auto_publish: false } },
        job: { job_id: ids.publishJob, status: "queued", deduplicated: false },
      },
      backendRoute
    )

    await createTelegramSource({
      name: "Wire", channelRef: "@wire", accessMode: "mtproto_user", languageHint: "fa",
      apiIdSecretRef: "TELEGRAM_API_ID", apiHashSecretRef: "TELEGRAM_API_HASH", sessionSecretRef: "TELEGRAM_SESSION",
    })
    await createTelegramDestination({ name: "Newsroom", targetRef: "@news", secretRef: "TELEGRAM_BOT_TOKEN", allowAutoPublish: false })
    const route = await createTelegramRoute({
      name: "Public to newsroom", sourceId: ids.source, destinationId: ids.destination,
      brandProfileId: ids.brand, promptTemplateVersionId: ids.prompt, promptPolicy: "pinned", aiProviderProfileId: ids.provider,
      accessMode: "public_html", researchMode: "off", contentFilters: { includeTerms: ["news"] },
      mediaPolicy: "preserve", attributionPolicy: "custom", customFooter: "Source",
      publishingPolicy: "review_required", pollIntervalSeconds: 300,
      retryPolicy: { maxAttempts: 3, baseDelaySeconds: 30, maxDelaySeconds: 1800 }, confirmAutoPublish: false,
    })

    expect(route).toEqual(expect.objectContaining({
      sourceId: ids.source, promptTemplateVersionId: ids.prompt, pollIntervalSeconds: 300,
      lastPolledAt: "2026-07-12T10:00:00Z", nextPollAt: "2026-07-12T10:05:00Z",
      retryPolicy: { maxAttempts: 3, baseDelaySeconds: 30, maxDelaySeconds: 1800 },
    }))
    expect(fetchSpy.mock.calls.map(([path, init]) => [path, init && { ...init, body: JSON.parse(init.body as string) }])).toEqual([
      ["/api/backend/telegram/sources", { ...jsonPost({}), body: { name: "Wire", channel_ref: "@wire", access_mode: "mtproto_user", language_hint: "fa", api_id_secret_ref: "TELEGRAM_API_ID", api_hash_secret_ref: "TELEGRAM_API_HASH", session_secret_ref: "TELEGRAM_SESSION" } }],
      ["/api/backend/telegram/destinations", { ...jsonPost({}), body: { name: "Newsroom", target_ref: "@news", secret_ref: "TELEGRAM_BOT_TOKEN", allow_auto_publish: false } }],
      ["/api/backend/telegram/automations", { ...jsonPost({}), body: { name: "Public to newsroom", source_id: ids.source, destination_id: ids.destination, brand_profile_id: ids.brand, prompt_template_version_id: ids.prompt, prompt_policy: "pinned", ai_provider_profile_id: ids.provider, access_mode: "public_html", research_mode: "off", content_filters: { include_terms: ["news"] }, media_policy: "preserve", attribution_policy: "custom", custom_footer: "Source", publishing_policy: "review_required", poll_interval_seconds: 300, retry_policy: { max_attempts: 3, base_delay_seconds: 30, max_delay_seconds: 1800 }, confirm_auto_publish: false } }],
    ])
  })

  it("posts exact route lifecycle, dry-run, and bounded backfill requests", async () => {
    const accepted = { route: backendRoute, job: { job_id: ids.publishJob, status: "queued", deduplicated: false } }
    const fetchSpy = stubFetchSequence(accepted, backendRoute, backendRoute, accepted, accepted, accepted)

    await activateTelegramRoute(ids.route)
    await pauseTelegramRoute(ids.route)
    await resumeTelegramRoute(ids.route)
    await dryRunTelegramRoute(ids.route, { sourceMessageId: 91 })
    await backfillTelegramRoute(ids.route, { count: 20 })
    await backfillTelegramRoute(ids.route, { since: "2026-07-01T00:00:00Z" })

    expect(fetchSpy.mock.calls).toEqual([
      [`/api/backend/telegram/automations/${ids.route}/activate`, { method: "POST" }],
      [`/api/backend/telegram/automations/${ids.route}/pause`, { method: "POST" }],
      [`/api/backend/telegram/automations/${ids.route}/resume`, { method: "POST" }],
      [`/api/backend/telegram/automations/${ids.route}/dry-run`, jsonPost({ source_message_id: 91 })],
      [`/api/backend/telegram/automations/${ids.route}/backfill`, jsonPost({ count: 20 })],
      [`/api/backend/telegram/automations/${ids.route}/backfill`, jsonPost({ since: "2026-07-01T00:00:00Z" })],
    ])
  })

  it("maps draft evidence/media/publication and sends exact review mutations", async () => {
    const backendDraft = makeBackendDraft()
    const fetchSpy = stubFetchSequence(
      [backendDraft], backendDraft, backendDraft, backendDraft,
      { revision: backendDraft, job: { publish_job_id: ids.publishJob, workflow_job_id: ids.provider, status: "queued" } }
    )

    const [draft] = await getTelegramDrafts({ routeId: ids.route, approvalState: "pending_review" })
    expect(draft).toEqual(expect.objectContaining({
      revisionNumber: 2, contentHash: "a".repeat(64), approvalState: "pending_review",
      content: expect.objectContaining({ mediaPolicy: "preserve", mediaAssetIds: [ids.source], dryRun: false }),
      evidence: [expect.objectContaining({ evidenceSnapshotId: ids.brand, contentText: "source evidence" })],
      media: [expect.objectContaining({ mimeType: "image/jpeg", fetchStatus: "downloaded" })],
      publication: expect.objectContaining({ remoteMessageIds: [501, 502] }),
    }))
    await editTelegramDraft(ids.revision, { content: { body: "edited", parse_mode: "HTML", buttons: [] }, media_asset_ids: [ids.source] })
    await approveTelegramDraft(ids.revision, "a".repeat(64))
    await rejectTelegramDraft(ids.revision, "a".repeat(64), "Needs attribution")
    await publishTelegramDraft(ids.revision, "a".repeat(64))

    expect(fetchSpy.mock.calls).toEqual([
      [`/api/backend/telegram/drafts?route_id=${ids.route}&approval_state=pending_review`, undefined],
      [`/api/backend/telegram/drafts/${ids.revision}/revisions`, jsonPost({ content: { body: "edited", parse_mode: "HTML", buttons: [] }, media_asset_ids: [ids.source] })],
      [`/api/backend/telegram/drafts/${ids.revision}/approve`, jsonPost({ content_hash: "a".repeat(64) })],
      [`/api/backend/telegram/drafts/${ids.revision}/reject`, jsonPost({ content_hash: "a".repeat(64), note: "Needs attribution" })],
      [`/api/backend/telegram/drafts/${ids.revision}/publish`, jsonPost({ content_hash: "a".repeat(64) })],
    ])
  })

  it("maps durable publish jobs and sends reconciliation evidence exactly", async () => {
    const backendJob = makeBackendPublishJob()
    const fetchSpy = stubFetchSequence(backendJob, backendJob.publication)

    await expect(getTelegramPublishJob(ids.publishJob)).resolves.toEqual(expect.objectContaining({
      publishJobId: ids.publishJob,
      platformVariantRevisionId: ids.revision,
      receipts: [expect.objectContaining({ operationIndex: 0, remoteMessageIds: [501, 502] })],
      publication: expect.objectContaining({ reconciliationStatus: "operator_confirmed" }),
    }))
    await expect(
      reconcileTelegramPublishJob(ids.publishJob, {
        outcome: "published",
        remoteMessageIds: [501, 502],
        permalink: "https://t.me/news/501",
      })
    ).resolves.toEqual(expect.objectContaining({
      publishJobId: ids.publishJob,
      reconciliationStatus: "confirmed",
      publication: expect.objectContaining({ remoteMessageIds: [501, 502] }),
    }))

    expect(fetchSpy.mock.calls[1]).toEqual([
      `/api/backend/telegram/publish-jobs/${ids.publishJob}/reconcile`,
      jsonPost({ outcome: "published", remote_message_ids: [501, 502], permalink: "https://t.me/news/501" }),
    ])
  })

  it("maps settings and uses immutable prompt version and environment-reference requests", async () => {
    const fetchSpy = stubFetchSequence(
      { id: ids.brand, name: "Main", output_language: "fa", tone: "direct", editorial_rules: [], attribution_rules: {}, default_hashtags: [], platform_preferences: {}, is_default: true },
      { id: ids.prompt, prompt_template_id: ids.brand, version: 2, system_template: "system", user_template: "user", output_schema_version: "telegram_rewrite.v1", output_schema: {}, checksum_sha256: "b".repeat(64), is_active: false, created_at: "2026-07-12T10:00:00Z" },
      [{ id: ids.prompt, prompt_template_id: ids.brand, version: 2, system_template: "system", user_template: "user", output_schema_version: "telegram_rewrite.v1", output_schema: {}, checksum_sha256: "b".repeat(64), is_active: false, created_at: "2026-07-12T10:00:00Z" }],
      { id: ids.prompt, prompt_template_id: ids.brand, version: 2, system_template: "system", user_template: "user", output_schema_version: "telegram_rewrite.v1", output_schema: {}, checksum_sha256: "b".repeat(64), is_active: true, created_at: "2026-07-12T10:00:00Z" },
      { id: ids.provider, name: "OpenRouter", provider_type: "openrouter", default_model: "openai/gpt", settings: {}, enabled: true, configured: false }
    )

    await createBrandProfile({ name: "Main", outputLanguage: "fa", tone: "direct", editorialRules: [], attributionRules: {}, defaultHashtags: [], platformPreferences: {}, isDefault: true })
    await createPromptVersion(ids.brand, { systemTemplate: "system", userTemplate: "user" })
    await getPromptVersions(ids.brand)
    await activatePromptVersion(ids.prompt, "Editorial approval")
    await createAIProviderProfile({ name: "OpenRouter", providerType: "openrouter", defaultModel: "openai/gpt", secretRef: "OPENROUTER_API_KEY", enabled: true })

    expect(fetchSpy.mock.calls).toEqual([
      ["/api/backend/brand-profiles", jsonPost({ name: "Main", output_language: "fa", tone: "direct", editorial_rules: [], attribution_rules: {}, default_hashtags: [], platform_preferences: {}, is_default: true })],
      [`/api/backend/prompt-templates/${ids.brand}/versions`, jsonPost({ system_template: "system", user_template: "user" })],
      [`/api/backend/prompt-templates/${ids.brand}/versions`, undefined],
      [`/api/backend/prompt-template-versions/${ids.prompt}/activate`, jsonPost({ reason: "Editorial approval" })],
      ["/api/backend/ai-provider-profiles", jsonPost({ name: "OpenRouter", provider_type: "openrouter", default_model: "openai/gpt", secret_ref: "OPENROUTER_API_KEY", enabled: true })],
    ])
  })

  it("provides stable granular query keys", () => {
    const filters = { routeId: ids.route, approvalState: "pending_review" as const }
    expect(queryKeys.telegramSources).toEqual(["telegram", "sources"])
    expect(queryKeys.telegramDestinations).toEqual(["telegram", "destinations"])
    expect(queryKeys.telegramRoutes).toEqual(["telegram", "routes"])
    expect(queryKeys.telegramRoute(ids.route)).toEqual(["telegram", "routes", ids.route])
    expect(queryKeys.telegramDispatches(ids.route)).toEqual(["telegram", "routes", ids.route, "dispatches"])
    expect(queryKeys.telegramDrafts(filters)).toEqual(["telegram", "drafts", filters])
    expect(queryKeys.telegramDraft(ids.revision)).toEqual(["telegram", "drafts", ids.revision])
    expect(queryKeys.telegramPublishJob(ids.publishJob)).toEqual(["telegram", "publish-jobs", ids.publishJob])
  })
})

function makeBackendDraft() {
  return {
    id: ids.revision, platform_variant_id: ids.provider, parent_revision_id: null, generation_attempt_id: null,
    revision_number: 2, content: { body: "خبر", parse_mode: "HTML", buttons: [], source_item_id: ids.source, source_url: "https://t.me/wire/91", media_policy: "preserve", media_asset_ids: [ids.source], direction: "rtl", dry_run: false },
    content_hash: "a".repeat(64), evidence_map: [], evidence: [{ evidence_snapshot_id: ids.brand, evidence_key: "telegram:91", source_url: "https://t.me/wire/91", content_text: "source evidence", content_sha256: "b".repeat(64) }],
    media: [{ id: ids.source, kind: "image", mime_type: "image/jpeg", fetch_status: "downloaded", checksum_sha256: "c".repeat(64) }],
    validation_results: [], approval_state: "pending_review", approval_note: null, approved_at: null, created_by: "generator", created_at: "2026-07-12T10:00:00Z",
    route_id: ids.route, dispatch_id: ids.destination, publish_job_id: ids.publishJob, publish_status: "confirmed",
    publication: makeBackendPublishJob().publication,
  }
}

function makeBackendPublishJob() {
  return {
    publish_job_id: ids.publishJob, workflow_job_id: ids.provider, destination_id: ids.destination,
    platform_variant_revision_id: ids.revision, status: "confirmed", payload_hash: "d".repeat(64),
    scheduled_for: "2026-07-12T10:00:00Z", created_at: "2026-07-12T10:00:00Z", updated_at: "2026-07-12T10:01:00Z",
    receipts: [{ id: ids.source, operation_index: 0, operation_key: "media-group", method: "sendMediaGroup", request_hash: "e".repeat(64), status: "succeeded", attempt_count: 1, remote_message_ids: [501, 502], response_metadata: {}, next_attempt_at: null, ambiguous_at: null, completed_at: "2026-07-12T10:01:00Z", created_at: "2026-07-12T10:00:00Z", updated_at: "2026-07-12T10:01:00Z" }],
    publication: { id: ids.brand, publish_job_id: ids.publishJob, destination_id: ids.destination, platform_variant_revision_id: ids.revision, remote_message_ids: [501, 502], permalink: "https://t.me/news/501", payload_hash: "d".repeat(64), published_at: "2026-07-12T10:01:00Z", reconciliation_status: "operator_confirmed" },
  }
}

function jsonPost(body: unknown) {
  return { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
}

function stubFetch(payload: unknown) {
  return stubFetchSequence(payload)
}

function stubFetchSequence(...payloads: unknown[]) {
  const fetchSpy = vi.fn()
  for (const payload of payloads) {
    fetchSpy.mockResolvedValueOnce({ ok: true, status: 200, statusText: "OK", json: async () => payload, text: async () => JSON.stringify(payload) })
  }
  vi.stubGlobal("fetch", fetchSpy)
  return fetchSpy
}

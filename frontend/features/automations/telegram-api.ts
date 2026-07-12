import { apiRequest } from "@/lib/http"

import type {
  AIProviderProfile,
  AIProviderProfileInput,
  AIProviderProfilePatch,
  AutomationControl,
  BrandProfile,
  BrandProfileInput,
  BrandProfilePatch,
  JobAccepted,
  PromptTemplate,
  PromptTemplateInput,
  PromptVersion,
  PromptVersionInput,
  TelegramAutomationOptions,
  TelegramDestination,
  TelegramDestinationAccepted,
  TelegramDestinationInput,
  TelegramDispatch,
  TelegramDraft,
  TelegramDraftEditInput,
  TelegramDraftFilters,
  TelegramDraftPublishAccepted,
  TelegramPublication,
  TelegramPublishJob,
  TelegramPublishReceipt,
  TelegramReconcileInput,
  TelegramReconciliationResult,
  TelegramRoute,
  TelegramRouteAccepted,
  TelegramRouteBackfillInput,
  TelegramRouteDryRunInput,
  TelegramRouteInput,
  TelegramSource,
  TelegramSourceInput,
} from "./telegram-types"

type BackendJobAccepted = { job_id: string; status: JobAccepted["status"]; deduplicated: boolean }
type BackendTelegramRoute = {
  id: string; name: string; source_id: string; destination_id: string; brand_profile_id: string
  prompt_template_version_id: string; ai_provider_profile_id: string; access_mode: TelegramRoute["accessMode"]
  research_mode: TelegramRoute["researchMode"]; content_filters: Record<string, unknown>
  media_policy: TelegramRoute["mediaPolicy"]; attribution_policy: TelegramRoute["attributionPolicy"]
  custom_footer: string | null; publishing_policy: TelegramRoute["publishingPolicy"]
  poll_interval_seconds: number; quiet_hours: Record<string, unknown>; retry_policy: Record<string, unknown>
  cursor_state: Record<string, unknown>; enabled: boolean; paused_at: string | null
  last_polled_at: string | null; next_poll_at: string | null; created_at: string; updated_at: string
}
type BackendTelegramPublication = {
  id: string; publish_job_id: string; destination_id: string; platform_variant_revision_id: string
  remote_message_ids: number[]; permalink: string | null; payload_hash: string; published_at: string
  reconciliation_status: string
}
type BackendTelegramDraft = {
  id: string; platform_variant_id: string; parent_revision_id: string | null; generation_attempt_id: string | null
  revision_number: number; content: Record<string, unknown>; content_hash: string
  evidence_map: Array<Record<string, unknown>>; evidence: Array<Record<string, unknown>>
  media: Array<Record<string, unknown>>; validation_results: unknown[]
  approval_state: TelegramDraft["approvalState"]; approval_note: string | null; approved_at: string | null
  created_by: string; created_at: string; route_id: string | null; dispatch_id: string | null
  publish_job_id: string | null; publish_status: TelegramDraft["publishStatus"]
  publication: BackendTelegramPublication | null
}
type BackendTelegramReceipt = {
  id: string; operation_index: number; operation_key: string; method: TelegramPublishReceipt["method"]
  request_hash: string; status: TelegramPublishReceipt["status"]; attempt_count: number
  remote_message_ids: number[]; response_metadata: Record<string, unknown>; next_attempt_at: string | null
  ambiguous_at: string | null; completed_at: string | null; created_at: string; updated_at: string
}
type BackendTelegramPublishJob = {
  publish_job_id: string; workflow_job_id: string | null; destination_id: string
  platform_variant_revision_id: string; status: TelegramPublishJob["status"]; payload_hash: string
  scheduled_for: string | null; created_at: string; updated_at: string; receipts: BackendTelegramReceipt[]
  publication: BackendTelegramPublication | null
}

const json = (method: "POST" | "PATCH", body: unknown): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
})

const defined = (value: Record<string, unknown>) =>
  Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined))

export async function getTelegramAutomationOptions(): Promise<TelegramAutomationOptions> {
  const row = await apiRequest<{
    sources: Array<{ id: string; name: string; access_mode: TelegramRoute["accessMode"] }>
    destinations: Array<{ id: string; name: string; health_status: TelegramDestination["healthStatus"]; allow_auto_publish: boolean }>
    brand_profiles: Array<{ id: string; name: string }>
    prompt_template_versions: Array<{ id: string; version: number }>
    ai_provider_profiles: Array<{ id: string; name: string; provider_type: "fake" | "openrouter"; default_model: string | null; configured: boolean }>
  }>("/telegram/automations/options")
  return {
    sources: row.sources.map((item) => ({ id: item.id, name: item.name, accessMode: item.access_mode })),
    destinations: row.destinations.map((item) => ({ id: item.id, name: item.name, healthStatus: item.health_status, allowAutoPublish: item.allow_auto_publish })),
    brandProfiles: row.brand_profiles,
    promptTemplateVersions: row.prompt_template_versions,
    aiProviderProfiles: row.ai_provider_profiles.map((item) => ({ id: item.id, name: item.name, providerType: item.provider_type, defaultModel: item.default_model, configured: item.configured })),
  }
}

export async function getTelegramSources(): Promise<TelegramSource[]> {
  return (await apiRequest<Array<Record<string, unknown>>>("/telegram/sources")).map(mapTelegramSource)
}

export async function createTelegramSource(input: TelegramSourceInput): Promise<TelegramSource> {
  const row = await apiRequest<Record<string, unknown>>("/telegram/sources", json("POST", defined({
    name: input.name, channel_ref: input.channelRef, access_mode: input.accessMode,
    api_id_secret_ref: input.apiIdSecretRef, api_hash_secret_ref: input.apiHashSecretRef,
    session_secret_ref: input.sessionSecretRef, language_hint: input.languageHint,
  })))
  return mapTelegramSource(row)
}

export async function getTelegramDestinations(): Promise<TelegramDestination[]> {
  return (await apiRequest<Array<Record<string, unknown>>>("/telegram/destinations")).map(mapTelegramDestination)
}

export async function createTelegramDestination(input: TelegramDestinationInput): Promise<TelegramDestinationAccepted> {
  const row = await apiRequest<{ destination: Record<string, unknown>; job: BackendJobAccepted }>(
    "/telegram/destinations",
    json("POST", { name: input.name, target_ref: input.targetRef, secret_ref: input.secretRef, allow_auto_publish: input.allowAutoPublish ?? false })
  )
  return { destination: mapTelegramDestination(row.destination), job: mapJobAccepted(row.job) }
}

export async function getTelegramRoutes(): Promise<TelegramRoute[]> {
  return (await apiRequest<BackendTelegramRoute[]>("/telegram/automations")).map(mapTelegramRoute)
}

export async function getTelegramRoute(id: string): Promise<TelegramRoute> {
  return mapTelegramRoute(await apiRequest<BackendTelegramRoute>(`/telegram/automations/${encodeURIComponent(id)}`))
}

export async function createTelegramRoute(input: TelegramRouteInput): Promise<TelegramRoute> {
  const contentFilters = input.contentFilters
  const row = await apiRequest<BackendTelegramRoute>("/telegram/automations", json("POST", defined({
    name: input.name, source_id: input.sourceId, destination_id: input.destinationId,
    brand_profile_id: input.brandProfileId, prompt_template_version_id: input.promptTemplateVersionId,
    ai_provider_profile_id: input.aiProviderProfileId, access_mode: input.accessMode,
    research_mode: input.researchMode, content_filters: contentFilters ? defined({
      model: contentFilters.model, include_terms: contentFilters.includeTerms, exclude_terms: contentFilters.excludeTerms,
      min_text_characters: contentFilters.minTextCharacters, require_media: contentFilters.requireMedia,
    }) : undefined,
    media_policy: input.mediaPolicy, attribution_policy: input.attributionPolicy, custom_footer: input.customFooter,
    publishing_policy: input.publishingPolicy, poll_interval_seconds: input.pollIntervalSeconds,
    quiet_hours: input.quietHours ? { timezone: input.quietHours.timezone, start: input.quietHours.start, end: input.quietHours.end } : input.quietHours,
    retry_policy: input.retryPolicy ? { max_attempts: input.retryPolicy.maxAttempts, base_delay_seconds: input.retryPolicy.baseDelaySeconds, max_delay_seconds: input.retryPolicy.maxDelaySeconds } : undefined,
    confirm_auto_publish: input.confirmAutoPublish,
  })))
  return mapTelegramRoute(row)
}

export const activateTelegramRoute = (id: string) => routeAccepted(id, "activate")
export const pauseTelegramRoute = (id: string) => routeTransition(id, "pause")
export const resumeTelegramRoute = (id: string) => routeTransition(id, "resume")

export async function dryRunTelegramRoute(id: string, input: TelegramRouteDryRunInput = {}): Promise<TelegramRouteAccepted> {
  const row = await apiRequest<{ route: BackendTelegramRoute; job: BackendJobAccepted }>(
    `/telegram/automations/${encodeURIComponent(id)}/dry-run`,
    json("POST", { source_message_id: input.sourceMessageId ?? null })
  )
  return mapRouteAccepted(row)
}

export async function backfillTelegramRoute(id: string, input: TelegramRouteBackfillInput): Promise<TelegramRouteAccepted> {
  const row = await apiRequest<{ route: BackendTelegramRoute; job: BackendJobAccepted }>(
    `/telegram/automations/${encodeURIComponent(id)}/backfill`, json("POST", input)
  )
  return mapRouteAccepted(row)
}

export async function getTelegramDispatches(routeId: string): Promise<TelegramDispatch[]> {
  const rows = await apiRequest<Array<Record<string, unknown>>>(`/telegram/automations/${encodeURIComponent(routeId)}/dispatches`)
  return rows.map(mapTelegramDispatch)
}

export async function getTelegramDrafts(filters: TelegramDraftFilters = {}): Promise<TelegramDraft[]> {
  const params = new URLSearchParams()
  if (filters.routeId) params.set("route_id", filters.routeId)
  if (filters.approvalState) params.set("approval_state", filters.approvalState)
  const query = params.toString()
  return (await apiRequest<BackendTelegramDraft[]>(`/telegram/drafts${query ? `?${query}` : ""}`)).map(mapTelegramDraft)
}

export async function getTelegramDraft(id: string): Promise<TelegramDraft> {
  return mapTelegramDraft(await apiRequest<BackendTelegramDraft>(`/telegram/drafts/${encodeURIComponent(id)}`))
}

export async function editTelegramDraft(id: string, input: TelegramDraftEditInput): Promise<TelegramDraft> {
  return mapTelegramDraft(await apiRequest<BackendTelegramDraft>(
    `/telegram/drafts/${encodeURIComponent(id)}/revisions`, json("POST", input)
  ))
}

export const approveTelegramDraft = (id: string, contentHash: string) => draftHashMutation(id, "approve", { content_hash: contentHash })
export const rejectTelegramDraft = (id: string, contentHash: string, note?: string) => draftHashMutation(id, "reject", defined({ content_hash: contentHash, note }))

export async function publishTelegramDraft(id: string, contentHash: string): Promise<TelegramDraftPublishAccepted> {
  const row = await apiRequest<{ revision: BackendTelegramDraft; job: { publish_job_id: string; workflow_job_id: string; status: TelegramPublishJob["status"] } }>(
    `/telegram/drafts/${encodeURIComponent(id)}/publish`, json("POST", { content_hash: contentHash })
  )
  return { revision: mapTelegramDraft(row.revision), job: { publishJobId: row.job.publish_job_id, workflowJobId: row.job.workflow_job_id, status: row.job.status } }
}

export async function getTelegramPublishJob(id: string): Promise<TelegramPublishJob> {
  return mapTelegramPublishJob(await apiRequest<BackendTelegramPublishJob>(`/telegram/publish-jobs/${encodeURIComponent(id)}`))
}

export function reconcileTelegramPublishJob(id: string, input: TelegramReconcileInput): Promise<TelegramReconciliationResult>
export function reconcileTelegramPublishJob(
  id: string,
  input: { outcome: TelegramReconcileInput["outcome"]; remoteMessageIds?: number[]; permalink?: string | null }
): Promise<TelegramReconciliationResult>
export async function reconcileTelegramPublishJob(
  id: string,
  input: { outcome: TelegramReconcileInput["outcome"]; remoteMessageIds?: number[]; permalink?: string | null }
): Promise<TelegramReconciliationResult> {
  const row = await apiRequest<Record<string, unknown>>(
    `/telegram/publish-jobs/${encodeURIComponent(id)}/reconcile`,
    json("POST", { outcome: input.outcome, remote_message_ids: input.outcome === "published" ? (input.remoteMessageIds ?? []) : [], ...(input.outcome === "published" && input.permalink !== undefined ? { permalink: input.permalink } : {}) })
  )
  if (Array.isArray(row.remote_message_ids)) {
    const publication = mapTelegramPublication(row as unknown as BackendTelegramPublication)
    return {
      publishJobId: publication.publishJobId,
      reconciliationStatus: "confirmed",
      receipts: [],
      publication,
    }
  }
  return {
    publishJobId: row.publish_job_id as string,
    reconciliationStatus: row.reconciliation_status as TelegramReconciliationResult["reconciliationStatus"],
    receipts: ((row.receipts as BackendTelegramReceipt[] | undefined) ?? []).map(mapTelegramReceipt),
    ...(row.publication ? { publication: mapTelegramPublication(row.publication as BackendTelegramPublication) } : {}),
    ...(row.job ? { job: mapJobAccepted(row.job as BackendJobAccepted) } : {}),
  }
}

export async function getBrandProfiles(): Promise<BrandProfile[]> {
  return (await apiRequest<Array<Record<string, unknown>>>("/brand-profiles")).map(mapBrandProfile)
}
export async function createBrandProfile(input: BrandProfileInput): Promise<BrandProfile> {
  return mapBrandProfile(await apiRequest<Record<string, unknown>>("/brand-profiles", json("POST", brandBody(input))))
}
export async function updateBrandProfile(id: string, input: BrandProfilePatch): Promise<BrandProfile> {
  return mapBrandProfile(await apiRequest<Record<string, unknown>>(`/brand-profiles/${encodeURIComponent(id)}`, json("PATCH", brandBody(input))))
}

export async function getPromptTemplates(): Promise<PromptTemplate[]> {
  return (await apiRequest<Array<Record<string, unknown>>>("/prompt-templates")).map(mapPromptTemplate)
}
export async function createPromptTemplate(input: PromptTemplateInput): Promise<PromptTemplate> {
  return mapPromptTemplate(await apiRequest<Record<string, unknown>>("/prompt-templates", json("POST", { purpose_key: input.purposeKey, name: input.name, description: input.description })))
}
export async function getPromptVersions(templateId: string): Promise<PromptVersion[]> {
  return (await apiRequest<Array<Record<string, unknown>>>(`/prompt-templates/${encodeURIComponent(templateId)}/versions`)).map(mapPromptVersion)
}
export async function createPromptVersion(templateId: string, input: PromptVersionInput): Promise<PromptVersion> {
  return mapPromptVersion(await apiRequest<Record<string, unknown>>(`/prompt-templates/${encodeURIComponent(templateId)}/versions`, json("POST", { system_template: input.systemTemplate, user_template: input.userTemplate })))
}
export async function activatePromptVersion(versionId: string): Promise<PromptVersion> {
  return mapPromptVersion(await apiRequest<Record<string, unknown>>(`/prompt-template-versions/${encodeURIComponent(versionId)}/activate`, { method: "POST" }))
}

export async function getAIProviderProfiles(): Promise<AIProviderProfile[]> {
  return (await apiRequest<Array<Record<string, unknown>>>("/ai-provider-profiles")).map(mapAIProviderProfile)
}
export async function createAIProviderProfile(input: AIProviderProfileInput): Promise<AIProviderProfile> {
  return mapAIProviderProfile(await apiRequest<Record<string, unknown>>("/ai-provider-profiles", json("POST", providerBody(input))))
}
export async function updateAIProviderProfile(id: string, input: AIProviderProfilePatch): Promise<AIProviderProfile> {
  return mapAIProviderProfile(await apiRequest<Record<string, unknown>>(`/ai-provider-profiles/${encodeURIComponent(id)}`, json("PATCH", providerBody(input))))
}

export function mapAutomationControl(row: Record<string, unknown>): AutomationControl {
  return { globalPause: row.global_pause as boolean, dryRun: row.dry_run as boolean, pauseReason: row.pause_reason as string | null, pausedAt: row.paused_at as string | null, updatedAt: row.updated_at as string }
}

export function mapTelegramRoute(row: BackendTelegramRoute): TelegramRoute {
  const filters = row.content_filters
  const retry = row.retry_policy
  const quiet = row.quiet_hours
  return {
    id: row.id, name: row.name, sourceId: row.source_id, destinationId: row.destination_id,
    brandProfileId: row.brand_profile_id, promptTemplateVersionId: row.prompt_template_version_id,
    aiProviderProfileId: row.ai_provider_profile_id, accessMode: row.access_mode, researchMode: row.research_mode,
    contentFilters: { model: filters.model as string | null | undefined, includeTerms: filters.include_terms as string[] | undefined, excludeTerms: filters.exclude_terms as string[] | undefined, minTextCharacters: filters.min_text_characters as number | undefined, requireMedia: filters.require_media as boolean | undefined },
    mediaPolicy: row.media_policy, attributionPolicy: row.attribution_policy, customFooter: row.custom_footer,
    publishingPolicy: row.publishing_policy, pollIntervalSeconds: row.poll_interval_seconds,
    quietHours: typeof quiet.start === "string" && typeof quiet.end === "string" ? { timezone: quiet.timezone as string, start: quiet.start, end: quiet.end } : null,
    retryPolicy: { maxAttempts: retry.max_attempts as number, baseDelaySeconds: retry.base_delay_seconds as number, maxDelaySeconds: retry.max_delay_seconds as number },
    cursorState: { ...row.cursor_state, status: row.cursor_state.status as TelegramRoute["cursorState"]["status"], activationRequestedAt: row.cursor_state.activation_requested_at as string | undefined, activationMessageId: row.cursor_state.activation_message_id as number | null | undefined, lastMessageId: row.cursor_state.last_message_id as number | null | undefined, recentFingerprints: row.cursor_state.recent_fingerprints as Record<string, string> | undefined },
    enabled: row.enabled, pausedAt: row.paused_at, lastPolledAt: row.last_polled_at, nextPollAt: row.next_poll_at,
    createdAt: row.created_at, updatedAt: row.updated_at,
  }
}

export function mapTelegramDraft(row: BackendTelegramDraft): TelegramDraft {
  const content = row.content
  return {
    id: row.id, platformVariantId: row.platform_variant_id, parentRevisionId: row.parent_revision_id,
    generationAttemptId: row.generation_attempt_id, revisionNumber: row.revision_number,
    content: { body: content.body as string, parseMode: content.parse_mode as "HTML", buttons: content.buttons as TelegramDraft["content"]["buttons"], sourceItemId: content.source_item_id as string | null, sourceUrl: content.source_url as string | null, mediaPolicy: content.media_policy as TelegramDraft["content"]["mediaPolicy"], mediaAssetIds: content.media_asset_ids as string[], direction: content.direction as TelegramDraft["content"]["direction"], dryRun: content.dry_run as boolean },
    contentHash: row.content_hash,
    evidenceMap: row.evidence_map.map((item) => ({ evidenceSnapshotId: item.evidence_snapshot_id as string, evidenceKey: item.evidence_key as string, sourceUrl: item.source_url as string | null, locator: item.locator as string, excerptSha256: item.excerpt_sha256 as string })),
    evidence: row.evidence.map((item) => ({ evidenceSnapshotId: item.evidence_snapshot_id as string, evidenceKey: item.evidence_key as string, sourceUrl: item.source_url as string | null, contentText: item.content_text as string, contentSha256: item.content_sha256 as string })),
    media: row.media.map((item) => ({ id: item.id as string, kind: item.kind as string, mimeType: item.mime_type as string | null, fetchStatus: item.fetch_status as string, checksumSha256: item.checksum_sha256 as string | null, previewUrl: `/api/backend${item.preview_url as string}` })),
    validationResults: row.validation_results, approvalState: row.approval_state, approvalNote: row.approval_note,
    approvedAt: row.approved_at, createdBy: row.created_by, createdAt: row.created_at, routeId: row.route_id,
    dispatchId: row.dispatch_id, publishJobId: row.publish_job_id, publishStatus: row.publish_status,
    publication: row.publication ? mapTelegramPublication(row.publication) : null,
  }
}

export function mapTelegramPublishJob(row: BackendTelegramPublishJob): TelegramPublishJob {
  return { publishJobId: row.publish_job_id, workflowJobId: row.workflow_job_id, destinationId: row.destination_id, platformVariantRevisionId: row.platform_variant_revision_id, status: row.status, payloadHash: row.payload_hash, scheduledFor: row.scheduled_for, createdAt: row.created_at, updatedAt: row.updated_at, receipts: row.receipts.map(mapTelegramReceipt), publication: row.publication ? mapTelegramPublication(row.publication) : null }
}

function mapTelegramSource(row: Record<string, unknown>): TelegramSource {
  return { id: row.id as string, name: row.name as string, channelRef: row.channel_ref as string, accessMode: row.access_mode as TelegramSource["accessMode"], languageHint: row.language_hint as string | null, configured: row.configured as boolean }
}
function mapTelegramDestination(row: Record<string, unknown>): TelegramDestination {
  const settings = (row.settings ?? {}) as Record<string, unknown>
  const { allow_auto_publish: allowAutoPublish, ...safeSettings } = settings
  return { id: row.id as string, name: row.name as string, targetRef: row.target_ref as string, enabled: row.enabled as boolean, healthStatus: row.health_status as TelegramDestination["healthStatus"], configured: row.configured as boolean, settings: { ...safeSettings, allowAutoPublish: allowAutoPublish as boolean | undefined } }
}
function mapTelegramDispatch(row: Record<string, unknown>): TelegramDispatch {
  return { id: row.id as string, routeId: row.route_id as string, sourceItemId: row.source_item_id as string, storyRevisionId: row.story_revision_id as string, sourceKey: row.source_key as string, sourceFingerprint: row.source_fingerprint as string, sourceMessageIds: row.source_message_ids as number[], dispatchKind: row.dispatch_kind as TelegramDispatch["dispatchKind"], status: row.status as string, generationRunId: row.generation_run_id as string | null, variantRevisionId: row.variant_revision_id as string | null, publishJobId: row.publish_job_id as string | null, errorCode: row.error_code as string | null, errorMessage: row.error_message as string | null, createdAt: row.created_at as string, updatedAt: row.updated_at as string }
}
function mapTelegramReceipt(row: BackendTelegramReceipt): TelegramPublishReceipt {
  return { id: row.id, operationIndex: row.operation_index, operationKey: row.operation_key, method: row.method, requestHash: row.request_hash, status: row.status, attemptCount: row.attempt_count, remoteMessageIds: row.remote_message_ids, responseMetadata: row.response_metadata, nextAttemptAt: row.next_attempt_at, ambiguousAt: row.ambiguous_at, completedAt: row.completed_at, createdAt: row.created_at, updatedAt: row.updated_at }
}
function mapTelegramPublication(row: BackendTelegramPublication): TelegramPublication {
  return { id: row.id, publishJobId: row.publish_job_id, destinationId: row.destination_id, platformVariantRevisionId: row.platform_variant_revision_id, remoteMessageIds: row.remote_message_ids, permalink: row.permalink, payloadHash: row.payload_hash, publishedAt: row.published_at, reconciliationStatus: row.reconciliation_status as TelegramPublication["reconciliationStatus"] }
}
function mapJobAccepted(row: BackendJobAccepted): JobAccepted { return { jobId: row.job_id, status: row.status, deduplicated: row.deduplicated } }
function mapRouteAccepted(row: { route: BackendTelegramRoute; job: BackendJobAccepted }): TelegramRouteAccepted { return { route: mapTelegramRoute(row.route), job: mapJobAccepted(row.job) } }
async function routeAccepted(id: string, transition: "activate") { return mapRouteAccepted(await apiRequest<{ route: BackendTelegramRoute; job: BackendJobAccepted }>(`/telegram/automations/${encodeURIComponent(id)}/${transition}`, { method: "POST" })) }
async function routeTransition(id: string, transition: "pause" | "resume") { return mapTelegramRoute(await apiRequest<BackendTelegramRoute>(`/telegram/automations/${encodeURIComponent(id)}/${transition}`, { method: "POST" })) }
async function draftHashMutation(id: string, transition: "approve" | "reject", body: Record<string, unknown>) { return mapTelegramDraft(await apiRequest<BackendTelegramDraft>(`/telegram/drafts/${encodeURIComponent(id)}/${transition}`, json("POST", body))) }

function brandBody(input: BrandProfileInput | BrandProfilePatch) { return defined({ name: input.name, output_language: input.outputLanguage, tone: input.tone, editorial_rules: input.editorialRules, attribution_rules: input.attributionRules, default_hashtags: input.defaultHashtags, platform_preferences: input.platformPreferences, is_default: input.isDefault }) }
function mapBrandProfile(row: Record<string, unknown>): BrandProfile { return { id: row.id as string, name: row.name as string, outputLanguage: row.output_language as string, tone: row.tone as string, editorialRules: row.editorial_rules as string[], attributionRules: row.attribution_rules as Record<string, unknown>, defaultHashtags: row.default_hashtags as string[], platformPreferences: row.platform_preferences as Record<string, unknown>, isDefault: row.is_default as boolean } }
function mapPromptTemplate(row: Record<string, unknown>): PromptTemplate { return { id: row.id as string, purposeKey: row.purpose_key as string, name: row.name as string, description: row.description as string | null } }
function mapPromptVersion(row: Record<string, unknown>): PromptVersion { return { id: row.id as string, promptTemplateId: row.prompt_template_id as string, version: row.version as number, systemTemplate: row.system_template as string, userTemplate: row.user_template as string, outputSchemaVersion: row.output_schema_version as string, outputSchema: row.output_schema as Record<string, unknown>, checksumSha256: row.checksum_sha256 as string, isActive: row.is_active as boolean, createdAt: row.created_at as string } }
function providerBody(input: AIProviderProfileInput | AIProviderProfilePatch) { return defined({ name: input.name, provider_type: "providerType" in input ? input.providerType : undefined, default_model: input.defaultModel, secret_ref: input.secretRef, settings: input.settings, enabled: input.enabled }) }
function mapAIProviderProfile(row: Record<string, unknown>): AIProviderProfile { return { id: row.id as string, name: row.name as string, providerType: row.provider_type as AIProviderProfile["providerType"], defaultModel: row.default_model as string | null, settings: row.settings as Record<string, unknown>, enabled: row.enabled as boolean, configured: row.configured as boolean } }

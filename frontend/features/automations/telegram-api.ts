import type { components } from "@/lib/api/generated"
import { camelize } from "@/lib/camelize"
import { apiRequest } from "@/lib/http"

import type {
  BrandProfile,
  BrandProfileInput,
  CredentialCapabilityState,
  JobAccepted,
  PromptTemplate,
  PromptVersion,
  PromptVersionInput,
  TelegramAutomationOptions,
  TelegramDestinationHealth,
  TelegramDispatch,
  TelegramPublicationContext,
  TelegramPublishAccepted,
  TelegramPublishJob,
  TelegramPublishReceipt,
  TelegramRoute,
  TelegramRouteAccepted,
  TelegramRouteBackfillInput,
  TelegramRouteDryRunInput,
  TelegramRouteInput,
  TelegramSource,
  TelegramSourceInput,
} from "./telegram-types"

type BackendJobAccepted = { job_id: string; status: JobAccepted["status"]; deduplicated: boolean }
type Schemas = components["schemas"]
type BackendTelegramRoute = {
  id: string; name: string; source_id: string; destination_id: string; brand_profile_id: string
  prompt_template_version_id: string; ai_provider_profile_id: string; access_mode: TelegramRoute["accessMode"]
  prompt_policy: TelegramRoute["promptPolicy"]
  research_mode: TelegramRoute["researchMode"]; content_filters: Record<string, unknown>
  media_policy: TelegramRoute["mediaPolicy"]; attribution_policy: TelegramRoute["attributionPolicy"]
  custom_footer: string | null; publishing_policy: TelegramRoute["publishingPolicy"]
  poll_interval_seconds: number; quiet_hours: Record<string, unknown>; retry_policy: Record<string, unknown>
  cursor_state: Record<string, unknown>; enabled: boolean; paused_at: string | null
  last_polled_at: string | null; next_poll_at: string | null; created_at: string; updated_at: string
}
type BackendTelegramPublication = Schemas["TelegramPublicationOut"]
type BackendTelegramPublicationContext = Schemas["TelegramPublicationContextOut"]
type BackendTelegramReceipt = {
  id: string; operation_index: number; operation_key: string; method: TelegramPublishReceipt["method"]
  request_hash: string; status: TelegramPublishReceipt["status"]; attempt_count: number
  remote_message_ids: number[]; response_metadata: Record<string, unknown>; next_attempt_at: string | null
  ambiguous_at: string | null; completed_at: string | null; created_at: string; updated_at: string
}
type BackendTelegramDispatch = {
  id: string; route_id: string; source_item_id: string; story_id: string; story_revision_id: string
  source_key: string; source_fingerprint: string; source_message_ids: number[]
  dispatch_kind: TelegramDispatch["dispatchKind"]; status: string; generation_run_id: string | null
  variant_revision_id: string | null; publish_job_id: string | null; error_code: string | null
  error_message: string | null; created_at: string; updated_at: string
}
type BackendPromptTemplate = { id: string; purpose_key: string; name: string; description: string | null }
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
    sources: Array<{ id: string; name: string; access_mode: TelegramRoute["accessMode"]; capability_state: unknown }>
    destinations: Array<{ id: string; name: string; health_status: TelegramDestinationHealth; capability_state: unknown }>
    brand_profiles: Array<{ id: string; name: string }>
    prompt_template_versions: Array<{ id: string; version: number; is_active: boolean; checksum_sha256: string }>
    ai_provider_profiles: Array<{ id: string; name: string; provider_type: "fake" | "openrouter" | "codex"; default_model: string | null; configured: boolean; capabilities: { generation: boolean; research: boolean }; capability_states: { generation?: unknown; research?: unknown } }>
  }>("/telegram/automations/options")
  return {
    sources: row.sources.map((item) => ({ id: item.id, name: item.name, accessMode: item.access_mode, capabilityState: mapCredentialCapabilityState(item.capability_state) })),
    destinations: row.destinations.map((item) => ({ id: item.id, name: item.name, healthStatus: item.health_status, capabilityState: mapCredentialCapabilityState(item.capability_state) })),
    brandProfiles: row.brand_profiles,
    promptTemplateVersions: row.prompt_template_versions.map((item) => ({
      id: item.id,
      version: item.version,
      isActive: item.is_active,
      checksumSha256: item.checksum_sha256,
    })),
    aiProviderProfiles: row.ai_provider_profiles.map((item) => ({ id: item.id, name: item.name, providerType: item.provider_type, defaultModel: item.default_model, configured: item.configured, capabilities: item.capabilities, capabilityStates: { generation: mapCredentialCapabilityState(item.capability_states?.generation), research: mapCredentialCapabilityState(item.capability_states?.research) } })),
  }
}

export async function createTelegramSource(input: TelegramSourceInput): Promise<TelegramSource> {
  const row = await apiRequest<Record<string, unknown>>("/telegram/sources", json("POST", defined({
    name: input.name, channel_ref: input.channelRef, access_mode: input.accessMode,
    api_id_secret_ref: input.apiIdSecretRef, api_hash_secret_ref: input.apiHashSecretRef,
    session_secret_ref: input.sessionSecretRef, language_hint: input.languageHint,
  })))
  return mapTelegramSource(row)
}

// Destination listing has exactly one client:
// features/settings/content-settings-api.ts getTelegramDestinations, typed
// against the generated TelegramDestinationOut schema.

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
    prompt_policy: input.promptPolicy,
    ai_provider_profile_id: input.aiProviderProfileId, access_mode: input.accessMode,
    research_mode: input.researchMode, content_filters: contentFilters ? defined({
      model: contentFilters.model, include_terms: contentFilters.includeTerms, exclude_terms: contentFilters.excludeTerms,
      min_text_characters: contentFilters.minTextCharacters, require_media: contentFilters.requireMedia,
      research_provider_profile_id: contentFilters.researchProviderProfileId,
    }) : undefined,
    media_policy: input.mediaPolicy, attribution_policy: input.attributionPolicy, custom_footer: input.customFooter,
    publishing_policy: input.publishingPolicy, poll_interval_seconds: input.pollIntervalSeconds,
    quiet_hours: input.quietHours ? { timezone: input.quietHours.timezone, start: input.quietHours.start, end: input.quietHours.end } : input.quietHours,
    retry_policy: input.retryPolicy ? { max_attempts: input.retryPolicy.maxAttempts, base_delay_seconds: input.retryPolicy.baseDelaySeconds, max_delay_seconds: input.retryPolicy.maxDelaySeconds } : undefined,
    confirm_auto_publish: input.confirmAutoPublish,
  })))
  return mapTelegramRoute(row)
}

export const pauseTelegramRoute = (id: string) => routeTransition(id, "pause")
export const resumeTelegramRoute = (id: string) => routeTransition(id, "resume")

export async function updateTelegramRoutePromptPolicy(
  id: string,
  input: {
    promptPolicy: TelegramRoute["promptPolicy"]
    promptTemplateVersionId?: string | null
    confirmChange: boolean
  },
): Promise<TelegramRoute> {
  return mapTelegramRoute(await apiRequest<BackendTelegramRoute>(
    `/telegram/automations/${encodeURIComponent(id)}/prompt-policy`,
    json("PATCH", {
      prompt_policy: input.promptPolicy,
      prompt_template_version_id: input.promptTemplateVersionId ?? null,
      confirm_change: input.confirmChange,
    }),
  ))
}

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
  const rows = await apiRequest<BackendTelegramDispatch[]>(`/telegram/automations/${encodeURIComponent(routeId)}/dispatches`)
  return rows.map(mapTelegramDispatch)
}

export async function getTelegramPublicationOutcomes(): Promise<TelegramPublicationContext[]> {
  return camelize(await apiRequest<BackendTelegramPublicationContext[]>("/telegram/publication-outcomes"))
}

export async function getTelegramPublicationContext(id: string): Promise<TelegramPublicationContext> {
  return camelize(await apiRequest<BackendTelegramPublicationContext>(
    `/telegram/revisions/${encodeURIComponent(id)}/publication-context`,
  ))
}

export async function publishTelegramDraft(id: string, contentHash: string): Promise<TelegramPublishAccepted> {
  return camelize(await apiRequest<Schemas["TelegramPublishAcceptedOut"]>(
    `/telegram/drafts/${encodeURIComponent(id)}/publish`, json("POST", { content_hash: contentHash })
  ))
}

export async function getTelegramPublishJob(id: string): Promise<TelegramPublishJob> {
  return mapTelegramPublishJob(await apiRequest<BackendTelegramPublishJob>(`/telegram/publish-jobs/${encodeURIComponent(id)}`))
}

// Reconciliation decisions have exactly one client:
// features/operations/api.ts submitReconciliationDecision.

export async function createBrandProfile(input: BrandProfileInput): Promise<BrandProfile> {
  return apiRequest<BrandProfile>("/brand-profiles", json("POST", input))
}

export async function getPromptTemplates(): Promise<PromptTemplate[]> {
  return (await apiRequest<BackendPromptTemplate[]>("/prompt-templates")).map(mapPromptTemplate)
}
export async function getPromptVersions(templateId: string): Promise<PromptVersion[]> {
  return apiRequest<PromptVersion[]>(`/prompt-templates/${encodeURIComponent(templateId)}/versions`)
}
export async function createPromptVersion(templateId: string, input: PromptVersionInput): Promise<PromptVersion> {
  return apiRequest<PromptVersion>(`/prompt-templates/${encodeURIComponent(templateId)}/versions`, json("POST", input))
}
export async function activatePromptVersion(versionId: string, reason: string): Promise<PromptVersion> {
  return apiRequest<PromptVersion>(`/prompt-template-versions/${encodeURIComponent(versionId)}/activate`, json("POST", { reason }))
}

export function mapTelegramRoute(row: BackendTelegramRoute): TelegramRoute {
  const filters = row.content_filters
  const retry = row.retry_policy
  const quiet = row.quiet_hours
  return {
    id: row.id, name: row.name, sourceId: row.source_id, destinationId: row.destination_id,
    brandProfileId: row.brand_profile_id, promptTemplateVersionId: row.prompt_template_version_id,
    promptPolicy: row.prompt_policy,
    aiProviderProfileId: row.ai_provider_profile_id, accessMode: row.access_mode, researchMode: row.research_mode,
    contentFilters: { model: filters.model as string | null | undefined, includeTerms: filters.include_terms as string[] | undefined, excludeTerms: filters.exclude_terms as string[] | undefined, minTextCharacters: filters.min_text_characters as number | undefined, requireMedia: filters.require_media as boolean | undefined, researchProviderProfileId: filters.research_provider_profile_id as string | undefined },
    mediaPolicy: row.media_policy, attributionPolicy: row.attribution_policy, customFooter: row.custom_footer,
    publishingPolicy: row.publishing_policy, pollIntervalSeconds: row.poll_interval_seconds,
    quietHours: typeof quiet.start === "string" && typeof quiet.end === "string" ? { timezone: quiet.timezone as string, start: quiet.start, end: quiet.end } : null,
    retryPolicy: { maxAttempts: retry.max_attempts as number, baseDelaySeconds: retry.base_delay_seconds as number, maxDelaySeconds: retry.max_delay_seconds as number },
    cursorState: { ...row.cursor_state, status: row.cursor_state.status as TelegramRoute["cursorState"]["status"], activationRequestedAt: row.cursor_state.activation_requested_at as string | undefined, activationMessageId: row.cursor_state.activation_message_id as number | null | undefined, lastMessageId: row.cursor_state.last_message_id as number | null | undefined, recentFingerprints: row.cursor_state.recent_fingerprints as Record<string, string> | undefined },
    enabled: row.enabled, pausedAt: row.paused_at, lastPolledAt: row.last_polled_at, nextPollAt: row.next_poll_at,
    createdAt: row.created_at, updatedAt: row.updated_at,
  }
}

export function mapTelegramPublishJob(row: BackendTelegramPublishJob): TelegramPublishJob {
  return camelize(row)
}

function mapTelegramSource(row: Record<string, unknown>): TelegramSource {
  return { id: row.id as string, name: row.name as string, channelRef: row.channel_ref as string, accessMode: row.access_mode as TelegramSource["accessMode"], languageHint: row.language_hint as string | null, configured: row.configured as boolean, capabilityState: mapCredentialCapabilityState(row.capability_state) }
}
function mapTelegramDispatch(row: BackendTelegramDispatch): TelegramDispatch {
  return camelize(row)
}
function mapJobAccepted(row: BackendJobAccepted): JobAccepted { return camelize(row) }
function mapRouteAccepted(row: { route: BackendTelegramRoute; job: BackendJobAccepted }): TelegramRouteAccepted { return { route: mapTelegramRoute(row.route), job: mapJobAccepted(row.job) } }
async function routeTransition(id: string, transition: "pause" | "resume") { return mapTelegramRoute(await apiRequest<BackendTelegramRoute>(`/telegram/automations/${encodeURIComponent(id)}/${transition}`, { method: "POST" })) }
function mapPromptTemplate(row: BackendPromptTemplate): PromptTemplate { return camelize(row) }

function mapCredentialCapabilityState(value: unknown): CredentialCapabilityState {
  const row = value && typeof value === "object" ? value as Record<string, unknown> : {}
  const status = ["available", "unavailable", "unknown", "stale"].includes(String(row.status))
    ? row.status as CredentialCapabilityState["status"]
    : "unknown"
  return {
    status,
    owner: typeof row.owner === "string" ? row.owner : null,
    observedAt: typeof row.observed_at === "string" ? row.observed_at : null,
    expiresAt: typeof row.expires_at === "string" ? row.expires_at : null,
    failureCode: typeof row.failure_code === "string" ? row.failure_code : "observation_missing",
  }
}

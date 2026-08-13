import type { JobStatus } from "@/features/jobs/types"
import type { components } from "@/lib/api/generated"
import type { Camelized } from "@/lib/camelize"

type Schemas = components["schemas"]

export type TelegramAccessMode = "public_html" | "mtproto_user"
export type TelegramResearchMode = "off" | "manual" | "auto_if_incomplete"
export type TelegramMediaPolicy = "preserve" | "omit" | "replace_manually"
export type TelegramAttributionPolicy = "preserve" | "remove" | "custom"
export type TelegramPublishingPolicy = "review_required" | "auto_publish"
export type TelegramPromptPolicy = "pinned" | "follow_active"
export type TelegramDestinationHealth = "unknown" | "healthy" | "unhealthy"
export type CredentialCapabilityStatus = "available" | "unavailable" | "unknown" | "stale"
export type CredentialCapabilityState = {
  status: CredentialCapabilityStatus
  owner: string | null
  observedAt: string | null
  expiresAt: string | null
  failureCode: string
}
export type TelegramPublishStatus =
  | "queued"
  | "dispatching"
  | "running"
  | "retrying"
  | "attention"
  | "reconciliation_required"
  | "succeeded"
  | "failed"
export type TelegramReceiptStatus = "pending" | "dispatching" | "succeeded" | "ambiguous" | "failed"
export type JobAccepted = {
  jobId: string
  status: JobStatus
  deduplicated: boolean
}

export type TelegramSource = {
  id: string
  name: string
  channelRef: string
  accessMode: TelegramAccessMode
  languageHint: string | null
  configured: boolean
  capabilityState: CredentialCapabilityState
}

export type TelegramSourceInput = {
  name: string
  channelRef: string
  accessMode: TelegramAccessMode
  languageHint?: string
  apiIdSecretRef?: string | null
  apiHashSecretRef?: string | null
  sessionSecretRef?: string | null
}

export type TelegramDestination = {
  id: string
  name: string
  targetRef: string
  enabled: boolean
  healthStatus: TelegramDestinationHealth
  configured: boolean
  capabilityState: CredentialCapabilityState
}

export type TelegramContentFilters = {
  model?: string | null
  includeTerms?: string[]
  excludeTerms?: string[]
  minTextCharacters?: number
  requireMedia?: boolean
  researchProviderProfileId?: string
}

export type TelegramQuietHours = { timezone: string; start: string; end: string }
export type TelegramRetryPolicy = {
  maxAttempts: number
  baseDelaySeconds: number
  maxDelaySeconds: number
}
export type TelegramCursorState = {
  status?: "not_initialized" | "initializing" | "ready"
  activationRequestedAt?: string
  activationMessageId?: number | null
  lastMessageId?: number | null
  recentFingerprints?: Record<string, string>
} & Record<string, unknown>

export type TelegramRoute = {
  id: string
  name: string
  sourceId: string
  destinationId: string
  brandProfileId: string
  promptTemplateVersionId: string
  promptPolicy: TelegramPromptPolicy
  aiProviderProfileId: string
  accessMode: TelegramAccessMode
  researchMode: TelegramResearchMode
  contentFilters: TelegramContentFilters
  mediaPolicy: TelegramMediaPolicy
  attributionPolicy: TelegramAttributionPolicy
  customFooter: string | null
  publishingPolicy: TelegramPublishingPolicy
  pollIntervalSeconds: number
  quietHours: TelegramQuietHours | null
  retryPolicy: TelegramRetryPolicy
  cursorState: TelegramCursorState
  enabled: boolean
  pausedAt: string | null
  lastPolledAt: string | null
  nextPollAt: string | null
  createdAt: string
  updatedAt: string
}

export type TelegramRouteInput = {
  name: string
  sourceId: string
  destinationId: string
  brandProfileId: string
  promptTemplateVersionId: string
  promptPolicy: TelegramPromptPolicy
  aiProviderProfileId: string
  accessMode: TelegramAccessMode
  researchMode?: TelegramResearchMode
  contentFilters?: TelegramContentFilters
  mediaPolicy?: TelegramMediaPolicy
  attributionPolicy?: TelegramAttributionPolicy
  customFooter?: string | null
  publishingPolicy?: TelegramPublishingPolicy
  pollIntervalSeconds?: number
  quietHours?: TelegramQuietHours | null
  retryPolicy?: TelegramRetryPolicy
  confirmAutoPublish?: boolean
}

export type TelegramRouteAccepted = { route: TelegramRoute; job: JobAccepted }
export type TelegramRouteDryRunInput = { sourceMessageId?: number | null }
export type TelegramRouteBackfillInput =
  | { count: number; since?: never }
  | { since: string; count?: never }

export type TelegramDispatchKind = "live" | "backfill" | "dry_run" | "source_edit"
export type TelegramDispatch = {
  id: string
  routeId: string
  sourceItemId: string
  storyId: string
  storyRevisionId: string
  sourceKey: string
  sourceFingerprint: string
  sourceMessageIds: number[]
  dispatchKind: TelegramDispatchKind
  status: string
  generationRunId: string | null
  variantRevisionId: string | null
  publishJobId: string | null
  errorCode: string | null
  errorMessage: string | null
  createdAt: string
  updatedAt: string
}

export type TelegramOption = { id: string; name: string }
export type TelegramAutomationOptions = {
  sources: Array<TelegramOption & { accessMode: TelegramAccessMode; capabilityState: CredentialCapabilityState }>
  destinations: Array<TelegramOption & { healthStatus: TelegramDestinationHealth; capabilityState: CredentialCapabilityState }>
  brandProfiles: TelegramOption[]
  promptTemplateVersions: Array<{ id: string; version: number; isActive: boolean; checksumSha256: string }>
  aiProviderProfiles: Array<
    TelegramOption & { providerType: "fake" | "openrouter" | "codex"; defaultModel: string | null; configured: boolean; capabilities: { generation: boolean; research: boolean }; capabilityStates: { generation: CredentialCapabilityState; research: CredentialCapabilityState } }
  >
}

export type TelegramPublication = Camelized<Schemas["TelegramPublicationOut"]>
export type TelegramPublicationContext = Camelized<Schemas["TelegramPublicationContextOut"]>
export type TelegramPublishAccepted = Camelized<Schemas["TelegramPublishAcceptedOut"]>

export type TelegramPublishReceipt = {
  id: string
  operationIndex: number
  operationKey: string
  method: "sendMessage" | "sendPhoto" | "sendVideo" | "sendDocument" | "sendMediaGroup"
  requestHash: string
  status: TelegramReceiptStatus
  attemptCount: number
  remoteMessageIds: number[]
  responseMetadata: Record<string, unknown>
  nextAttemptAt: string | null
  ambiguousAt: string | null
  completedAt: string | null
  createdAt: string
  updatedAt: string
}
export type TelegramPublishJob = {
  publishJobId: string
  workflowJobId: string | null
  destinationId: string
  platformVariantRevisionId: string
  status: TelegramPublishStatus
  payloadHash: string
  scheduledFor: string | null
  createdAt: string
  updatedAt: string
  receipts: TelegramPublishReceipt[]
  publication: TelegramPublication | null
}

export type BrandProfile = Schemas["BrandProfileOut"]
export type BrandProfileInput = Schemas["BrandProfileCreate"]
export type BrandProfilePatch = Schemas["BrandProfilePatch"]

export type PromptTemplate = { id: string; purposeKey: string; name: string; description: string | null }
export type PromptVersion = Schemas["PromptTemplateVersionOut"]
export type PromptVersionInput = Schemas["PromptTemplateVersionCreate"]

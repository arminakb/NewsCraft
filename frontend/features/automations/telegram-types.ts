import type { JobStatus } from "@/features/jobs/types"

export type TelegramAccessMode = "public_html" | "mtproto_user"
export type TelegramResearchMode = "off" | "manual" | "auto_if_incomplete"
export type TelegramMediaPolicy = "preserve" | "omit" | "replace_manually"
export type TelegramAttributionPolicy = "preserve" | "remove" | "custom"
export type TelegramPublishingPolicy = "review_required" | "auto_publish"
export type TelegramPromptPolicy = "pinned" | "follow_active"
export type TelegramApprovalState = "draft" | "pending_review" | "approved" | "rejected"
export type TelegramDirection = "ltr" | "rtl"
export type TelegramParseMode = "HTML"
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
export type TelegramReconciliationOutcome = "published" | "not_published"

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
  settings: { allowAutoPublish?: boolean } & Record<string, unknown>
}

export type TelegramDestinationInput = {
  name: string
  targetRef: string
  secretRef: string
  allowAutoPublish?: boolean
}

export type TelegramDestinationAccepted = {
  destination: TelegramDestination
  job: JobAccepted
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
  destinations: Array<TelegramOption & { healthStatus: TelegramDestinationHealth; allowAutoPublish: boolean; capabilityState: CredentialCapabilityState }>
  brandProfiles: TelegramOption[]
  promptTemplateVersions: Array<{ id: string; version: number; isActive: boolean; checksumSha256: string }>
  aiProviderProfiles: Array<
    TelegramOption & { providerType: "fake" | "openrouter" | "codex"; defaultModel: string | null; configured: boolean; capabilities: { generation: boolean; research: boolean }; capabilityStates: { generation: CredentialCapabilityState; research: CredentialCapabilityState } }
  >
}

export type TelegramButton = { text: string; url: string }
export type TelegramRewriteContent = {
  body: string
  parseMode: TelegramParseMode
  buttons: TelegramButton[]
  sourceItemId: string | null
  sourceUrl: string | null
  mediaPolicy: TelegramMediaPolicy
  mediaAssetIds: string[]
  direction: TelegramDirection
  dryRun: boolean
}
export type TelegramEvidenceCitation = {
  evidenceSnapshotId: string
  evidenceKey: string
  sourceUrl: string | null
  locator: string
  excerptSha256: string
}
export type TelegramEvidence = {
  evidenceSnapshotId: string
  evidenceKey: string
  sourceUrl: string | null
  contentText: string
  contentSha256: string
}
export type TelegramDraftMedia = {
  id: string
  kind: string
  mimeType: string | null
  fetchStatus: string
  checksumSha256: string | null
  previewUrl: string
}
export type TelegramPublication = {
  id: string
  publishJobId: string
  destinationId: string
  platformVariantRevisionId: string
  remoteMessageIds: number[]
  permalink: string | null
  payloadHash: string
  publishedAt: string
  reconciliationStatus: "confirmed"
}
export type TelegramDraft = {
  id: string
  platformVariantId: string
  parentRevisionId: string | null
  generationAttemptId: string | null
  revisionNumber: number
  content: TelegramRewriteContent
  contentHash: string
  evidenceMap: TelegramEvidenceCitation[]
  evidence: TelegramEvidence[]
  media: TelegramDraftMedia[]
  validationResults: unknown[]
  approvalState: TelegramApprovalState
  approvalNote: string | null
  approvedAt: string | null
  createdBy: string
  createdAt: string
  routeId: string | null
  dispatchId: string | null
  publishJobId: string | null
  publishStatus: TelegramPublishStatus | null
  publication: TelegramPublication | null
}
export type TelegramDraftFilters = { routeId?: string; approvalState?: TelegramApprovalState }
export type TelegramDraftEditInput = {
  content: { body: string; parse_mode: TelegramParseMode; buttons: TelegramButton[] }
  media_asset_ids: string[]
}
export type TelegramDraftPublishAccepted = {
  revision: TelegramDraft
  job: { publishJobId: string; workflowJobId: string; status: TelegramPublishStatus }
}

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
export type TelegramReconcileInput =
  | { outcome: "published"; remoteMessageIds: number[]; permalink?: string | null }
  | { outcome: "not_published"; remoteMessageIds?: never; permalink?: never }
export type TelegramReconciliationResult = {
  publishJobId: string
  reconciliationStatus: "confirmed" | "requeued"
  receipts: TelegramPublishReceipt[]
  publication?: TelegramPublication
  job?: JobAccepted
}

export type AutomationControl = {
  globalPause: boolean
  dryRun: boolean
  pauseReason: string | null
  pausedAt: string | null
  updatedAt: string
}

export type BrandProfile = {
  id: string
  name: string
  outputLanguage: string
  tone: string
  editorialRules: string[]
  attributionRules: Record<string, unknown>
  defaultHashtags: string[]
  platformPreferences: Record<string, unknown>
  isDefault: boolean
}
export type BrandProfileInput = Omit<BrandProfile, "id">
export type BrandProfilePatch = Partial<BrandProfileInput>

export type PromptTemplate = { id: string; purposeKey: string; name: string; description: string | null }
export type PromptTemplateInput = Omit<PromptTemplate, "id">
export type PromptVersion = {
  id: string
  promptTemplateId: string
  version: number
  systemTemplate: string
  userTemplate: string
  outputSchemaVersion: string
  outputSchema: Record<string, unknown>
  checksumSha256: string
  isActive: boolean
  activatedAt: string | null
  activatedByType: string | null
  activatedById: string | null
  activationReason: string | null
  createdAt: string
}
export type PromptVersionInput = { systemTemplate: string; userTemplate: string }

export type AIProviderProfile = {
  id: string
  name: string
  providerType: "fake" | "openrouter" | "codex"
  defaultModel: string | null
  settings: Record<string, unknown>
  enabled: boolean
  configured: boolean
  capabilities: { generation: boolean; research: boolean }
  capabilityStates: { generation: CredentialCapabilityState; research: CredentialCapabilityState }
  unavailabilityCodes: string[]
}
export type AIProviderProfileInput = {
  name: string
  providerType: "fake" | "openrouter" | "codex"
  defaultModel?: string | null
  secretRef?: string | null
  settings?: Record<string, unknown> | null
  enabled?: boolean
}
export type AIProviderProfilePatch = Omit<Partial<AIProviderProfileInput>, "providerType">

export type ResearchMode = "off" | "manual" | "auto_if_incomplete"
export type EditorialState = "inbox" | "shortlisted" | "rejected" | "drafted"

export type Completeness = { complete: boolean; score: number; reasons: string[] }
export type AIProviderOption = {
  id: string
  name: string
  providerType: "fake" | "openrouter" | "codex"
  defaultModel: string | null
  capabilities: { generation: boolean; research: boolean }
  unavailableReason: string | null
}
export type PromptVersionOption = {
  id: string
  purpose: "canonical_story" | "telegram_pack"
  version: number
  checksumSha256: string
  active: boolean
}
export type BrandOption = { id: string; name: string; isDefault: boolean }
export type StoryFilters = {
  search?: string
  editorialState?: EditorialState
  completeness?: "complete" | "incomplete"
  includeSuperseded?: boolean
  limit?: number
  cursor?: string
}
export type StorySummary = {
  id: string
  title: string
  evidenceCount: number
  latestEvidenceAt: string | null
  completeness: Completeness
  editorialState: EditorialState
  status: string
  primaryLanguage: string
  evidenceSetHash: string
  createdAt: string
  updatedAt: string
}
export type EvidenceDetail = {
  id: string
  evidenceKey: string
  title: string | null
  contentText: string
  contentSha256: string
  sourceUrl: string | null
  authors: string[]
  publishedAt: string | null
  capturedAt: string
}
export type StoryDetail = StorySummary & { evidence: EvidenceDetail[] }
export type StoryPage = { items: StorySummary[]; nextCursor: string | null }
export type JobAccepted = { jobId: string; status: string; deduplicated: boolean }
export type ResearchSourceDetail = { id: string; url: string; title: string | null; contentSha256: string; publishedAt: string | null }
export type ResearchRunDetail = {
  id: string
  storyId: string
  requestedMode: "manual" | "auto_if_incomplete"
  status: string
  provider: { id: string; name: string; providerType: string } | null
  budget: { maxQueries: number; maxPages: number; maxElapsedSeconds: number }
  requestedModel: string | null
  resolvedModel: string | null
  evidenceSetHash: string | null
  completeness: Completeness | null
  attempts: Array<{ id: string; attemptNumber: number; status: string; errorMessage: string | null }>
  sources: ResearchSourceDetail[]
  resultStoryRevisionId: string | null
}
export type ResearchDisposition = { disposition: "skipped" | "complete_without_research" | "enqueued"; runId: string | null; jobId: string | null; completeness: Completeness }

export type TelegramButton = { text: string; url: string }
export type EvidenceCitation = { evidenceSnapshotId: string; evidenceKey: string; sourceUrl: string | null; locator: string; excerptSha256: string }
export type RevisionState = "draft" | "pending_review" | "approved" | "rejected"
export type ValidationResult = { gate: string; ok: boolean; reason: string | null }
export type VariantRevision = {
  id: string
  variantId: string
  contentPackId: string
  storyId: string
  parentRevisionId: string | null
  generationAttemptId: string | null
  revisionNumber: number
  content: {
    body: string
    parseMode: "HTML"
    buttons: TelegramButton[]
    mediaAssetIds: string[]
    sourceUrl: string | null
    mediaPolicy: string
    direction: "ltr" | "rtl" | "auto"
    dryRun: boolean
  }
  contentHash: string
  evidenceMap: EvidenceCitation[]
  validationResults: ValidationResult[]
  approvalState: RevisionState
  approvalNote: string | null
  approvedAt: string | null
  createdBy: string
  origin: "operator" | "generation" | "automation"
  createdAt: string
  providerProfile: { id: string; name: string; providerType: string } | null
  resolvedModel: string | null
}
export type ContentPackSummary = { id: string; storyId: string; storyRevisionId: string; brandProfileId: string; status: string; createdAt: string; updatedAt: string; lastFailure: string | null; jobId: string | null; variants: Array<{ id: string; platform: "telegram" }> }
export type ContentPackDetail = ContentPackSummary & { variantRevisions: Record<string, VariantRevision[]> }
export type ContentPackRequestSummary = { id: string; jobId: string | null; storyId: string; status: string; lastFailure: string | null; createdAt: string; updatedAt: string; pack: ContentPackSummary | null }

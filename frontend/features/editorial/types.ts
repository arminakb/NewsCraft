import type {
  CitationRef,
  Platform,
  RevisionState,
  TelegramButton,
  ValidationResult,
} from "@/features/packages/types"

export type { RevisionState, TelegramButton, ValidationResult }

export type Completeness = {
  complete: boolean
  score: number
  reasons: string[]
}

export type AIProviderOption = {
  id: string
  name: string
  providerType: "fake" | "openrouter" | "codex"
  defaultModel: string | null
  capabilities: { generation: boolean; research: boolean }
  unavailableReason: string | null
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
  attempts: Array<{
    id: string
    attemptNumber: number
    status: string
    errorMessage: string | null
  }>
  sources: Array<{
    id: string
    url: string
    title: string | null
    contentSha256: string
    publishedAt: string | null
  }>
  resultStoryRevisionId: string | null
}

export type EvidenceCitation = CitationRef

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

export type ContentPackSummary = {
  id: string
  storyId: string
  storyRevisionId: string
  brandProfileId: string
  status: string
  createdAt: string
  updatedAt: string
  lastFailure: string | null
  jobId: string | null
  variants: Array<{ id: string; platform: Platform }>
}

export type ContentPackRequestSummary = {
  id: string
  jobId: string | null
  storyId: string
  status: string
  lastFailure: string | null
  createdAt: string
  updatedAt: string
  pack: ContentPackSummary | null
}

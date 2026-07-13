import type { JobAccepted } from "@/features/jobs/types"

export const RETENTION_CONFIRMATION = "DELETE PREVIEWED DATA" as const

export type OperationHealthStatus = "healthy" | "degraded" | "down" | "unknown"

export type OperationComponentHealth = {
  status: OperationHealthStatus
  observedAt: string | null
  lastSuccessAt: string | null
  message: string
  actionUrl: string | null
}

export type OperationAttentionItem = {
  id: string
  severity: "warning" | "error"
  kind: "job" | "route" | "research" | "generation" | "publication" | "destination" | "source"
  title: string
  occurredAt: string
  actionUrl: string
}

export type OperationsSnapshot = {
  generatedAt: string
  globalPaused: boolean
  dryRun: boolean
  components: Record<string, OperationComponentHealth>
  queueCounts: Record<string, number>
  attention: OperationAttentionItem[]
}

export type HistoryCategory =
  | "collection"
  | "research"
  | "generation"
  | "edit"
  | "approval"
  | "schedule"
  | "publish"
  | "retry"
  | "pause"
  | "cancel"
  | "reconcile"

export type HistorySubjectType = "automation_route" | "story" | "job"

export type HistoryFilters = {
  subjectType?: HistorySubjectType
  subjectId?: string
  category?: HistoryCategory
  status?: string
  cursor?: string
  limit?: number
}

export type HistoryEntry = {
  id: string
  occurredAt: string
  category: HistoryCategory
  status: string
  title: string
  summary: string
  jobId: string | null
  subjectUrl: string
  sanitizedMetadata: Record<string, unknown>
}

export type HistoryPage = {
  items: HistoryEntry[]
  nextCursor: string | null
}

export type ReconciliationDestination = {
  id: string
  name: string
  targetRef: string
}

export type ReconciliationOperation = {
  operationIndex: number
  operationKey: string
  method: string
  requestHash: string
  status: string
  attemptCount: number
  remoteMessageIds: number[]
  sentAt: string | null
}

export type ReconciliationCase = {
  publishJobId: string
  status: "pending"
  publishStatus: string
  workflowJobId: string | null
  platformVariantRevisionId: string
  destination: ReconciliationDestination
  operations: ReconciliationOperation[]
  ambiguousOperationKey: string
  ambiguousAt: string | null
  ambiguityReason: string
}

export type ReconciliationDecision =
  | {
      outcome: "published"
      remoteMessageIds: number[]
      permalink?: string | null
      operatorNote: string
    }
  | {
      outcome: "not_published"
      operatorNote: string
    }

export type ReconciliationReceipt = {
  id: string
  operationIndex: number
  operationKey: string
  method: string
  requestHash: string
  status: string
  attemptCount: number
  remoteMessageIds: number[]
  responseMetadata: Record<string, unknown>
  nextAttemptAt: string | null
  ambiguousAt: string | null
  completedAt: string | null
  createdAt: string
  updatedAt: string
}

export type ReconciledPublication = {
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

export type RequeuedReconciliation = {
  publishJobId: string
  reconciliationStatus: "requeued"
  job: JobAccepted
  receipts: ReconciliationReceipt[]
}

export type ReconciliationDecisionResult = ReconciledPublication | RequeuedReconciliation

export type RetentionPolicyValues = {
  rawPayloadDays: number
  completedJobDays: number
  attemptMetadataDays: number
  exportArtifactDays: number
  unreferencedMediaDays: number
}

export type RetentionPolicy = RetentionPolicyValues & {
  id: "global"
  createdAt: string
  updatedAt: string
}

export type RetentionCategory =
  | "raw_payload"
  | "completed_job"
  | "attempt_metadata"
  | "export_artifact"
  | "unreferenced_media"

export type RetentionRecordType =
  | "raw_payload"
  | "workflow_job"
  | "research_attempt"
  | "generation_attempt"
  | "publish_attempt"
  | "media_asset"

export type RetentionCandidate = {
  category: RetentionCategory
  recordType: RetentionRecordType
  recordId: string
  operation: "scrub" | "expire"
  occurredAt: string
  byteLength: number | null
}

export type RetentionCategorySummary = {
  count: number
  byteLength: number | null
  oldestAt: string | null
  newestAt: string | null
}

export type RetentionPreview = {
  runId: string
  previewToken: string
  schemaRevision: string
  policy: RetentionPolicyValues
  candidates: RetentionCandidate[]
  counts: Partial<Record<RetentionCategory, RetentionCategorySummary>>
  previewedAt: string
  previewExpiresAt: string
}

export type RetentionRunAccepted = JobAccepted

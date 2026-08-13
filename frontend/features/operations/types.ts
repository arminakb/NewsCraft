import type { JobAccepted } from "@/features/jobs/types"
import type { components } from "@/lib/api/generated"

type Schemas = components["schemas"]

export const RETENTION_CONFIRMATION = "DELETE PREVIEWED DATA" as const

export type OperationComponentHealth = Schemas["ComponentHealthOut"]
export type OperationsSnapshot = Schemas["OperationsSnapshotOut"]
export type OperationalHealthSnapshot = Schemas["OperationalHealthSnapshot"]
export type OperationalHealthState = Schemas["HealthState"]
export type OperationalDependency = Schemas["DependencyHealth"]
export type OperationalComponent = Schemas["ComponentOperationalHealth"]
export type OperationalQueue = Schemas["QueueOperationalHealth"]

export type HistoryCategory = Schemas["HistoryCategory"]
export type HistorySubjectType = Schemas["HistorySubjectType"]

export type HistoryFilters = {
  subjectType?: HistorySubjectType
  subjectId?: string
  category?: HistoryCategory
  status?: string
  cursor?: string
  limit?: number
}

export type HistoryEntry = Schemas["HistoryEntryOut"]
export type HistoryPage = Schemas["HistoryPageOut"]

export type ReconciliationDestination = Schemas["ReconciliationDestination"]
export type ReconciliationCase = Schemas["ReconciliationCase"]

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

export type RetentionPolicyValues = Schemas["RetentionPolicyInput"]
export type RetentionPolicy = Schemas["RetentionPolicyOut"]
export type RetentionCategory = Schemas["RetentionCategory"]
export type RetentionRecordType = Schemas["RetentionRecordType"]
export type RetentionPreview = Schemas["RetentionPreviewOut"]

export type RetentionRunAccepted = JobAccepted

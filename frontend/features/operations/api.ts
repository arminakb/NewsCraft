import { camelize } from "@/lib/camelize"
import { apiRequest } from "@/lib/http"
import type { components } from "@/lib/api/generated"

import { RETENTION_CONFIRMATION } from "./types"
import type {
  HistoryCategory,
  HistoryFilters,
  HistoryPage,
  HistorySubjectType,
  OperationsSnapshot,
  ReconciliationCase,
  ReconciliationDecision,
  ReconciliationDecisionResult,
  RetentionPolicy,
  RetentionPolicyValues,
  RetentionPreview,
  RetentionRunAccepted,
} from "./types"

type BackendOperationsSnapshot = components["schemas"]["OperationsSnapshotOut"]
type BackendHistoryPage = components["schemas"]["HistoryPageOut"]
type BackendReconciliationCase = components["schemas"]["ReconciliationCase"]

type BackendReconciliationReceipt = {
  id: string
  operation_index: number
  operation_key: string
  method: string
  request_hash: string
  status: string
  attempt_count: number
  remote_message_ids: number[]
  response_metadata: Record<string, unknown>
  next_attempt_at: string | null
  ambiguous_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

type BackendReconciledPublication = {
  id: string
  publish_job_id: string
  destination_id: string
  platform_variant_revision_id: string
  remote_message_ids: number[]
  permalink: string | null
  payload_hash: string
  published_at: string
  reconciliation_status: "confirmed"
}

type BackendJobAccepted = components["schemas"]["JobAcceptedOut"]

type BackendRequeuedReconciliation = {
  publish_job_id: string
  reconciliation_status: "requeued"
  job: BackendJobAccepted
  receipts: BackendReconciliationReceipt[]
}

type BackendReconciliationDecisionResult = BackendReconciledPublication | BackendRequeuedReconciliation

type BackendRetentionPolicy = components["schemas"]["RetentionPolicyOut"]
type BackendRetentionPreview = components["schemas"]["RetentionPreviewOut"]

export async function fetchOperationsDiagnostics(): Promise<OperationsSnapshot> {
  const row = await apiRequest<BackendOperationsSnapshot>("/operations/diagnostics")
  return {
    ...row,
    outbound_proxy: {
      ...row.outbound_proxy,
      configuration_error_code: row.outbound_proxy.configuration_error_code ?? null,
      scheme: row.outbound_proxy.scheme ?? null,
    },
  }
}

export async function fetchOperationsHistory(filters: HistoryFilters = {}): Promise<HistoryPage> {
  if ((filters.subjectType === undefined) !== (filters.subjectId === undefined)) {
    throw new Error("History subject type and subject ID must be supplied together")
  }

  const search = new URLSearchParams()
  setOptional(search, "subject_type", filters.subjectType)
  setOptional(search, "subject_id", filters.subjectId)
  setOptional(search, "category", filters.category)
  setOptional(search, "status", filters.status)
  setOptional(search, "cursor", filters.cursor)
  if (filters.limit !== undefined) search.set("limit", String(filters.limit))
  const query = search.toString()

  return apiRequest<BackendHistoryPage>(`/operations/history${query ? `?${query}` : ""}`)
}

export async function fetchReconciliationCases(): Promise<ReconciliationCase[]> {
  return apiRequest<BackendReconciliationCase[]>("/telegram/reconciliation")
}

export async function submitReconciliationDecision(
  publishJobId: string,
  decision: ReconciliationDecision,
): Promise<ReconciliationDecisionResult> {
  const remoteMessageIds = decision.outcome === "published" ? decision.remoteMessageIds : []
  const permalink = decision.outcome === "published" ? decision.permalink ?? null : null
  const row = await apiRequest<BackendReconciliationDecisionResult>(
    `/telegram/publish-jobs/${encodeURIComponent(publishJobId)}/reconcile`,
    jsonRequest("POST", {
      outcome: decision.outcome,
      remote_message_ids: remoteMessageIds,
      permalink,
      operator_note: decision.operatorNote,
    }),
  )
  if (row.reconciliation_status !== "requeued") return camelize(row)
  const converted = camelize(row)
  return {
    ...converted,
    job: row.job,
    receipts: converted.receipts.map((receipt, index) => ({
      ...receipt,
      responseMetadata: row.receipts[index].response_metadata,
    })),
  }
}

export async function fetchRetentionPolicy(): Promise<RetentionPolicy> {
  return apiRequest<BackendRetentionPolicy>("/operations/retention-policy")
}

export async function updateRetentionPolicy(
  policy: RetentionPolicyValues,
): Promise<RetentionPolicy> {
  return apiRequest<BackendRetentionPolicy>(
    "/operations/retention-policy",
    jsonRequest("PUT", policy),
  )
}

export async function createRetentionPreview(): Promise<RetentionPreview> {
  return apiRequest<BackendRetentionPreview>(
    "/operations/retention-preview",
    jsonRequest("POST", {}),
  )
}

export async function enqueueRetentionRun(previewToken: string): Promise<RetentionRunAccepted> {
  return apiRequest<BackendJobAccepted>(
    "/operations/retention-runs",
    jsonRequest("POST", {
      preview_token: previewToken,
      confirmation: RETENTION_CONFIRMATION,
    }),
  )
}

function setOptional(
  search: URLSearchParams,
  key: string,
  value: HistorySubjectType | HistoryCategory | string | undefined,
) {
  if (value !== undefined) search.set(key, value)
}

function jsonRequest(method: "POST" | "PUT", body: object): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }
}

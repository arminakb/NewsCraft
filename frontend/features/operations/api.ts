import { apiRequest } from "@/lib/http"

import type { JobAccepted, JobStatus } from "@/features/jobs/types"
import { RETENTION_CONFIRMATION } from "./types"
import type {
  HistoryCategory,
  HistoryEntry,
  HistoryFilters,
  HistoryPage,
  HistorySubjectType,
  OperationAttentionItem,
  OperationComponentHealth,
  OperationsSnapshot,
  ReconciledPublication,
  ReconciliationCase,
  ReconciliationDecision,
  ReconciliationDecisionResult,
  ReconciliationOperation,
  ReconciliationReceipt,
  RequeuedReconciliation,
  RetentionCandidate,
  RetentionCategory,
  RetentionCategorySummary,
  RetentionPolicy,
  RetentionPolicyValues,
  RetentionPreview,
  RetentionRecordType,
  RetentionRunAccepted,
} from "./types"

type BackendOperationComponentHealth = {
  status: OperationComponentHealth["status"]
  observed_at: string | null
  last_success_at: string | null
  message: string
  action_url: string | null
}

type BackendOperationAttentionItem = {
  id: string
  severity: OperationAttentionItem["severity"]
  kind: OperationAttentionItem["kind"]
  title: string
  occurred_at: string
  action_url: string
}

type BackendOperationsSnapshot = {
  generated_at: string
  global_paused: boolean
  dry_run: boolean
  components: Record<string, BackendOperationComponentHealth>
  queue_counts: Record<string, number>
  attention: BackendOperationAttentionItem[]
  outbound_proxy: {
    mode: "direct" | "proxy"
    scheme: string | null
    bypass_rule_count: number
    last_connectivity_status: "not_checked" | "ok" | "failed"
    configuration_error_code: string | null
  }
}

type BackendHistoryEntry = {
  id: string
  occurred_at: string
  category: HistoryCategory
  status: string
  title: string
  summary: string
  job_id: string | null
  subject_url: string
  sanitized_metadata: Record<string, unknown>
}

type BackendHistoryPage = {
  items: BackendHistoryEntry[]
  next_cursor: string | null
}

type BackendReconciliationOperation = {
  operation_index: number
  operation_key: string
  method: string
  request_hash: string
  status: string
  attempt_count: number
  remote_message_ids: number[]
  sent_at: string | null
}

type BackendReconciliationCase = {
  publish_job_id: string
  status: "pending"
  publish_status: string
  workflow_job_id: string | null
  platform_variant_revision_id: string
  destination: {
    id: string
    name: string
    target_ref: string
  }
  operations: BackendReconciliationOperation[]
  ambiguous_operation_key: string
  ambiguous_at: string | null
  ambiguity_reason: string
}

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

type BackendJobAccepted = {
  job_id: string
  status: JobStatus
  deduplicated: boolean
}

type BackendRequeuedReconciliation = {
  publish_job_id: string
  reconciliation_status: "requeued"
  job: BackendJobAccepted
  receipts: BackendReconciliationReceipt[]
}

type BackendReconciliationDecisionResult = BackendReconciledPublication | BackendRequeuedReconciliation

type BackendRetentionPolicyValues = {
  raw_payload_days: number
  completed_job_days: number
  attempt_metadata_days: number
  export_artifact_days: number
  unreferenced_media_days: number
}

type BackendRetentionPolicy = BackendRetentionPolicyValues & {
  id: "global"
  created_at: string
  updated_at: string
}

type BackendRetentionCandidate = {
  category: RetentionCategory
  record_type: RetentionRecordType
  record_id: string
  operation: RetentionCandidate["operation"]
  occurred_at: string
  byte_length: number | null
}

type BackendRetentionCategorySummary = {
  count: number
  byte_length: number | null
  oldest_at: string | null
  newest_at: string | null
}

type BackendRetentionPreview = {
  run_id: string
  preview_token: string
  schema_revision: string
  policy: BackendRetentionPolicyValues
  candidates: BackendRetentionCandidate[]
  counts: Partial<Record<RetentionCategory, BackendRetentionCategorySummary>>
  previewed_at: string
  preview_expires_at: string
}

export async function fetchOperationsDiagnostics(): Promise<OperationsSnapshot> {
  return mapOperationsSnapshot(await apiRequest<BackendOperationsSnapshot>("/operations/diagnostics"))
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

  return mapHistoryPage(
    await apiRequest<BackendHistoryPage>(`/operations/history${query ? `?${query}` : ""}`),
  )
}

export async function fetchReconciliationCases(): Promise<ReconciliationCase[]> {
  const rows = await apiRequest<BackendReconciliationCase[]>("/telegram/reconciliation")
  return rows.map(mapReconciliationCase)
}

export async function fetchReconciliationCase(publishJobId: string): Promise<ReconciliationCase> {
  return mapReconciliationCase(
    await apiRequest<BackendReconciliationCase>(
      `/telegram/reconciliation/${encodeURIComponent(publishJobId)}`,
    ),
  )
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
  return row.reconciliation_status === "requeued"
    ? mapRequeuedReconciliation(row)
    : mapReconciledPublication(row)
}

export async function fetchRetentionPolicy(): Promise<RetentionPolicy> {
  return mapRetentionPolicy(
    await apiRequest<BackendRetentionPolicy>("/operations/retention-policy"),
  )
}

export async function updateRetentionPolicy(
  policy: RetentionPolicyValues,
): Promise<RetentionPolicy> {
  return mapRetentionPolicy(
    await apiRequest<BackendRetentionPolicy>(
      "/operations/retention-policy",
      jsonRequest("PUT", retentionPolicyBody(policy)),
    ),
  )
}

export async function createRetentionPreview(): Promise<RetentionPreview> {
  return mapRetentionPreview(
    await apiRequest<BackendRetentionPreview>(
      "/operations/retention-preview",
      jsonRequest("POST", {}),
    ),
  )
}

export async function enqueueRetentionRun(previewToken: string): Promise<RetentionRunAccepted> {
  return mapJobAccepted(
    await apiRequest<BackendJobAccepted>(
      "/operations/retention-runs",
      jsonRequest("POST", {
        preview_token: previewToken,
        confirmation: RETENTION_CONFIRMATION,
      }),
    ),
  )
}

function mapOperationsSnapshot(row: BackendOperationsSnapshot): OperationsSnapshot {
  const components: Record<string, OperationComponentHealth> = {}
  for (const [componentId, component] of Object.entries(row.components)) {
    components[componentId] = {
      status: component.status,
      observedAt: component.observed_at,
      lastSuccessAt: component.last_success_at,
      message: component.message,
      actionUrl: component.action_url,
    }
  }
  return {
    generatedAt: row.generated_at,
    globalPaused: row.global_paused,
    dryRun: row.dry_run,
    components,
    queueCounts: row.queue_counts,
    attention: row.attention.map(mapAttentionItem),
    outboundProxy: {
      mode: row.outbound_proxy.mode,
      scheme: row.outbound_proxy.scheme,
      bypassRuleCount: row.outbound_proxy.bypass_rule_count,
      lastConnectivityStatus: row.outbound_proxy.last_connectivity_status,
      configurationErrorCode: row.outbound_proxy.configuration_error_code,
    },
  }
}

function mapAttentionItem(row: BackendOperationAttentionItem): OperationAttentionItem {
  return {
    id: row.id,
    severity: row.severity,
    kind: row.kind,
    title: row.title,
    occurredAt: row.occurred_at,
    actionUrl: row.action_url,
  }
}

function mapHistoryPage(row: BackendHistoryPage): HistoryPage {
  return {
    items: row.items.map(mapHistoryEntry),
    nextCursor: row.next_cursor,
  }
}

function mapHistoryEntry(row: BackendHistoryEntry): HistoryEntry {
  return {
    id: row.id,
    occurredAt: row.occurred_at,
    category: row.category,
    status: row.status,
    title: row.title,
    summary: row.summary,
    jobId: row.job_id,
    subjectUrl: row.subject_url,
    sanitizedMetadata: row.sanitized_metadata,
  }
}

function mapReconciliationCase(row: BackendReconciliationCase): ReconciliationCase {
  return {
    publishJobId: row.publish_job_id,
    status: row.status,
    publishStatus: row.publish_status,
    workflowJobId: row.workflow_job_id,
    platformVariantRevisionId: row.platform_variant_revision_id,
    destination: {
      id: row.destination.id,
      name: row.destination.name,
      targetRef: row.destination.target_ref,
    },
    operations: row.operations.map(mapReconciliationOperation),
    ambiguousOperationKey: row.ambiguous_operation_key,
    ambiguousAt: row.ambiguous_at,
    ambiguityReason: row.ambiguity_reason,
  }
}

function mapReconciliationOperation(row: BackendReconciliationOperation): ReconciliationOperation {
  return {
    operationIndex: row.operation_index,
    operationKey: row.operation_key,
    method: row.method,
    requestHash: row.request_hash,
    status: row.status,
    attemptCount: row.attempt_count,
    remoteMessageIds: row.remote_message_ids,
    sentAt: row.sent_at,
  }
}

function mapReconciledPublication(row: BackendReconciledPublication): ReconciledPublication {
  return {
    id: row.id,
    publishJobId: row.publish_job_id,
    destinationId: row.destination_id,
    platformVariantRevisionId: row.platform_variant_revision_id,
    remoteMessageIds: row.remote_message_ids,
    permalink: row.permalink,
    payloadHash: row.payload_hash,
    publishedAt: row.published_at,
    reconciliationStatus: row.reconciliation_status,
  }
}

function mapRequeuedReconciliation(row: BackendRequeuedReconciliation): RequeuedReconciliation {
  return {
    publishJobId: row.publish_job_id,
    reconciliationStatus: row.reconciliation_status,
    job: mapJobAccepted(row.job),
    receipts: row.receipts.map(mapReconciliationReceipt),
  }
}

function mapReconciliationReceipt(row: BackendReconciliationReceipt): ReconciliationReceipt {
  return {
    id: row.id,
    operationIndex: row.operation_index,
    operationKey: row.operation_key,
    method: row.method,
    requestHash: row.request_hash,
    status: row.status,
    attemptCount: row.attempt_count,
    remoteMessageIds: row.remote_message_ids,
    responseMetadata: row.response_metadata,
    nextAttemptAt: row.next_attempt_at,
    ambiguousAt: row.ambiguous_at,
    completedAt: row.completed_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

function mapRetentionPolicy(row: BackendRetentionPolicy): RetentionPolicy {
  return {
    id: row.id,
    ...mapRetentionPolicyValues(row),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

function mapRetentionPolicyValues(row: BackendRetentionPolicyValues): RetentionPolicyValues {
  return {
    rawPayloadDays: row.raw_payload_days,
    completedJobDays: row.completed_job_days,
    attemptMetadataDays: row.attempt_metadata_days,
    exportArtifactDays: row.export_artifact_days,
    unreferencedMediaDays: row.unreferenced_media_days,
  }
}

function retentionPolicyBody(policy: RetentionPolicyValues): BackendRetentionPolicyValues {
  return {
    raw_payload_days: policy.rawPayloadDays,
    completed_job_days: policy.completedJobDays,
    attempt_metadata_days: policy.attemptMetadataDays,
    export_artifact_days: policy.exportArtifactDays,
    unreferenced_media_days: policy.unreferencedMediaDays,
  }
}

function mapRetentionPreview(row: BackendRetentionPreview): RetentionPreview {
  const counts: Partial<Record<RetentionCategory, RetentionCategorySummary>> = {}
  for (const [category, summary] of Object.entries(row.counts) as Array<
    [RetentionCategory, BackendRetentionCategorySummary]
  >) {
    counts[category] = {
      count: summary.count,
      byteLength: summary.byte_length,
      oldestAt: summary.oldest_at,
      newestAt: summary.newest_at,
    }
  }
  return {
    runId: row.run_id,
    previewToken: row.preview_token,
    schemaRevision: row.schema_revision,
    policy: mapRetentionPolicyValues(row.policy),
    candidates: row.candidates.map(mapRetentionCandidate),
    counts,
    previewedAt: row.previewed_at,
    previewExpiresAt: row.preview_expires_at,
  }
}

function mapRetentionCandidate(row: BackendRetentionCandidate): RetentionCandidate {
  return {
    category: row.category,
    recordType: row.record_type,
    recordId: row.record_id,
    operation: row.operation,
    occurredAt: row.occurred_at,
    byteLength: row.byte_length,
  }
}

function mapJobAccepted(row: BackendJobAccepted): JobAccepted {
  return {
    jobId: row.job_id,
    status: row.status,
    deduplicated: row.deduplicated,
  }
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

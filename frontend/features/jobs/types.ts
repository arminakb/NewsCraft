export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "needs_review" | "cancelled"
export type JobErrorClass = "retryable" | "needs_review" | "permanent"
export type JobOrigin = "manual" | "scheduler" | "automation" | "retry"

export type WorkflowJob = {
  id: string
  jobType: string
  status: JobStatus
  origin: JobOrigin
  priority: number
  pauseSensitive: boolean
  scheduledFor: string
  attemptCount: number
  maxAttempts: number
  progress: number
  progressMessage: string | null
  errorClass: JobErrorClass | null
  errorCode: string | null
  errorMessage: string | null
  startedAt: string | null
  finishedAt: string | null
  createdAt: string
  updatedAt: string
}

export type JobEvent = {
  id: string
  eventType: string
  actor: string
  eventData: Record<string, unknown>
  createdAt: string
}

export type WorkflowJobDetail = WorkflowJob & {
  payload: Record<string, unknown>
  result: Record<string, unknown>
  events: JobEvent[]
}

export type JobSummary = {
  queued: number
  running: number
  attention: number
  succeededToday: number
}

export type JobAccepted = {
  jobId: string
  status: JobStatus
  deduplicated: boolean
}

export type JobFilters = {
  statuses?: readonly JobStatus[]
  jobType?: string
  errorClass?: JobErrorClass
  limit?: number
}

export type EnqueueIngestInput = {
  requestId: string
  platforms?: string[]
  sourceIds?: string[]
}

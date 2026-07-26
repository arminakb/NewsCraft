import type { components } from "@/lib/api/generated"

type Schemas = components["schemas"]

export type JobStatus = Schemas["JobStatus"]
export type JobErrorClass = Schemas["JobErrorClass"]
export type JobOrigin = Schemas["JobOrigin"]
export type WorkflowJob = Schemas["JobOut"]
export type JobEvent = Schemas["JobEventOut"]
export type WorkflowJobDetail = Schemas["JobDetailOut"]
export type JobSummary = Schemas["JobSummaryOut"]
export type JobAccepted = Schemas["JobAcceptedOut"]

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

import type { components } from "@/lib/api/generated"
import { camelize } from "@/lib/camelize"
import { apiRequest } from "@/lib/http"

import type {
  Automation,
  AutomationCreateInput,
  AutomationDetail,
  AutomationListFilters,
  AutomationNodeCatalog,
  AutomationPage,
  AutomationPatchInput,
  AutomationResourceCatalog,
  AutomationResourceRequest,
  AutomationRun,
  AutomationRunFilters,
  AutomationRunPage,
  AutomationRunStartInput,
  AutomationTemplate,
  AutomationTemplateCreateInput,
  AutomationVersion,
  AutomationVersionInput,
  AutomationVersionPage,
  GraphValidation,
} from "./automation-types"

type Schemas = components["schemas"]

function snakeize(value: unknown, preserveKeys = false): unknown {
  if (Array.isArray(value)) return value.map((item) => snakeize(item))
  if (value === null || typeof value !== "object") return value
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      preserveKeys ? key : key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`),
      snakeize(item, key === "layout" || key === "promptChecksums" || key === "prompt_checksums"),
    ]),
  )
}

function json(method: "POST" | "PATCH", body: unknown, idempotencyKey?: string): RequestInit {
  return {
    method,
    headers: {
      "content-type": "application/json",
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
    },
    body: JSON.stringify(snakeize(body)),
  }
}

function withSignal(init: RequestInit | undefined, signal?: AbortSignal): RequestInit | undefined {
  return signal ? { ...init, signal } : init
}

export async function getAutomations(filters: AutomationListFilters = {}, signal?: AbortSignal): Promise<AutomationPage> {
  const params = new URLSearchParams()
  if (filters.limit !== undefined) params.set("limit", String(filters.limit))
  if (filters.cursor) params.set("cursor", filters.cursor)
  if (filters.includeArchived !== undefined) params.set("include_archived", String(filters.includeArchived))
  const query = params.size ? `?${params.toString()}` : ""
  return camelize(await apiRequest<Schemas["AutomationPageOut"]>(`/automations${query}`, withSignal(undefined, signal))) as unknown as AutomationPage
}

export async function getAutomation(id: string, signal?: AbortSignal): Promise<AutomationDetail> {
  return camelize(await apiRequest<Schemas["AutomationDetailOut"]>(
    `/automations/${encodeURIComponent(id)}`,
    withSignal(undefined, signal),
  )) as unknown as AutomationDetail
}

export async function createAutomation(
  input: AutomationCreateInput,
  idempotencyKey: string,
): Promise<AutomationDetail> {
  return camelize(await apiRequest<Schemas["AutomationDetailOut"]>(
    "/automations",
    json("POST", input, idempotencyKey),
  )) as unknown as AutomationDetail
}

export async function patchAutomation(id: string, input: AutomationPatchInput): Promise<Automation> {
  return camelize(await apiRequest<Schemas["AutomationOut"]>(
    `/automations/${encodeURIComponent(id)}`,
    json("PATCH", input),
  )) as unknown as Automation
}

export async function duplicateAutomation(
  id: string,
  input: AutomationTemplateCreateInput,
  idempotencyKey: string,
): Promise<AutomationDetail> {
  return camelize(await apiRequest<Schemas["AutomationDetailOut"]>(
    `/automations/${encodeURIComponent(id)}/duplicate`,
    json("POST", input, idempotencyKey),
  )) as unknown as AutomationDetail
}

async function lifecycle(id: string, action: "archive" | "pause" | "resume", expectedRevision: number) {
  return camelize(await apiRequest<Schemas["AutomationOut"]>(
    `/automations/${encodeURIComponent(id)}/${action}`,
    json("POST", { expectedRevision }),
  ))
}

export const archiveAutomation = (id: string, expectedRevision: number) => lifecycle(id, "archive", expectedRevision)
export async function activateAutomation(id: string, expectedRevision: number, idempotencyKey: string) {
  return camelize(await apiRequest<Schemas["AutomationOut"]>(
    `/automations/${encodeURIComponent(id)}/activate`,
    json("POST", { expectedRevision }, idempotencyKey),
  ))
}
export const pauseAutomation = (id: string, expectedRevision: number) => lifecycle(id, "pause", expectedRevision)
export const resumeAutomation = (id: string, expectedRevision: number) => lifecycle(id, "resume", expectedRevision)

export async function getAutomationVersions(
  automationId: string,
  filters: Pick<AutomationListFilters, "limit" | "cursor"> = {},
  signal?: AbortSignal,
): Promise<AutomationVersionPage> {
  const params = new URLSearchParams()
  if (filters.limit !== undefined) params.set("limit", String(filters.limit))
  if (filters.cursor) params.set("cursor", filters.cursor)
  const query = params.size ? `?${params.toString()}` : ""
  return camelize(await apiRequest<Schemas["AutomationVersionPageOut"]>(
    `/automations/${encodeURIComponent(automationId)}/versions${query}`,
    withSignal(undefined, signal),
  )) as unknown as AutomationVersionPage
}

export async function getAutomationVersion(automationId: string, version: number, signal?: AbortSignal): Promise<AutomationVersion> {
  return camelize(await apiRequest<Schemas["AutomationVersionOut"]>(
    `/automations/${encodeURIComponent(automationId)}/versions/${version}`,
    withSignal(undefined, signal),
  )) as unknown as AutomationVersion
}

export async function createAutomationVersion(
  automationId: string,
  input: AutomationVersionInput,
  idempotencyKey: string,
): Promise<AutomationVersion> {
  return camelize(await apiRequest<Schemas["AutomationVersionOut"]>(
    `/automations/${encodeURIComponent(automationId)}/versions`,
    json("POST", input, idempotencyKey),
  )) as unknown as AutomationVersion
}

export async function restoreAutomationVersion(
  automationId: string,
  version: number,
  expectedRevision: number,
  idempotencyKey: string,
  creationReason = "version restored as draft",
): Promise<AutomationVersion> {
  return camelize(await apiRequest<Schemas["AutomationVersionOut"]>(
    `/automations/${encodeURIComponent(automationId)}/versions/${version}/restore-as-draft`,
    json("POST", { expectedRevision, creationReason }, idempotencyKey),
  )) as unknown as AutomationVersion
}

export async function validateAutomationVersion(automationId: string, version: number): Promise<GraphValidation> {
  return camelize(await apiRequest<Schemas["GraphValidationResult"]>(
    `/automations/${encodeURIComponent(automationId)}/versions/${version}/validate`,
    json("POST", {}),
  ))
}

export async function getAutomationNodeCatalog(signal?: AbortSignal): Promise<AutomationNodeCatalog> {
  return camelize(await apiRequest<Schemas["AutomationNodeCatalogOut"]>(
    "/automation-node-catalog",
    withSignal(undefined, signal),
  ))
}

export async function getAutomationResourceCatalog(
  resources: AutomationResourceRequest[],
  automationId?: string,
  signal?: AbortSignal,
): Promise<AutomationResourceCatalog> {
  return camelize(await apiRequest<Schemas["AutomationResourceCatalogOut"]>(
    "/automation-resource-catalog",
    withSignal(json("POST", { resources, automationId }), signal),
  ))
}

export async function getAutomationTemplates(signal?: AbortSignal): Promise<AutomationTemplate[]> {
  return camelize(await apiRequest<Schemas["AutomationTemplateOut"][]>(
    "/automation-templates",
    withSignal(undefined, signal),
  )) as unknown as AutomationTemplate[]
}

export async function createAutomationFromTemplate(
  templateKey: string,
  input: AutomationTemplateCreateInput,
  idempotencyKey: string,
): Promise<AutomationDetail> {
  return camelize(await apiRequest<Schemas["AutomationDetailOut"]>(
    `/automation-templates/${encodeURIComponent(templateKey)}/create`,
    json("POST", input, idempotencyKey),
  )) as unknown as AutomationDetail
}

export async function getAutomationRuns(
  automationId: string,
  filters: AutomationRunFilters = {},
  signal?: AbortSignal,
): Promise<AutomationRunPage> {
  const params = new URLSearchParams()
  if (filters.limit !== undefined) params.set("limit", String(filters.limit))
  if (filters.cursor) params.set("cursor", filters.cursor)
  if (filters.status) params.set("status", filters.status)
  if (filters.dryRun !== undefined && filters.dryRun !== null) params.set("dry_run", String(filters.dryRun))
  if (filters.dateFrom) params.set("date_from", filters.dateFrom)
  if (filters.dateTo) params.set("date_to", filters.dateTo)
  if (filters.failedOnly) params.set("failed_only", "true")
  const query = params.size ? `?${params.toString()}` : ""
  return camelize(await apiRequest<Schemas["AutomationRunPageOut"]>(
    `/automations/${encodeURIComponent(automationId)}/runs${query}`,
    withSignal(undefined, signal),
  )) as unknown as AutomationRunPage
}

export async function getAutomationRun(runId: string, signal?: AbortSignal): Promise<AutomationRun> {
  return camelize(await apiRequest<Schemas["AutomationRunOut"]>(
    `/automation-runs/${encodeURIComponent(runId)}`,
    withSignal(undefined, signal),
  )) as unknown as AutomationRun
}

export async function startAutomationRun(
  automationId: string,
  input: AutomationRunStartInput,
  idempotencyKey: string,
): Promise<AutomationRun> {
  return camelize(await apiRequest<Schemas["AutomationRunOut"]>(
    `/automations/${encodeURIComponent(automationId)}/runs`,
    json("POST", input, idempotencyKey),
  )) as unknown as AutomationRun
}

import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import Ajv, { type ValidateFunction } from "ajv"
import addFormats from "ajv-formats"
import type { Page, Route } from "@playwright/test"

import type { components } from "../../lib/api/generated"

type HttpMethod = "get" | "post" | "put" | "patch" | "delete"
type JsonObject = Record<string, unknown>

export type MockStory = {
  id: string
  title: string
  status: string
  primary_language: string
  evidence_count: number
  latest_evidence_at: string | null
  completeness: { complete: boolean; score: number; reasons: string[] }
  evidence_set_hash: string
  created_at: string
  updated_at: string
}

export type MockBackendOptions = {
  automations?: components["schemas"]["AutomationOut"][]
  stories?: MockStory[]
  operations?: components["schemas"]["OperationsSnapshotOut"]
  operationalHealth?: components["schemas"]["OperationalHealthSnapshot"]
  operationsDelayMs?: number
  operationsFailure?: boolean
}

const CONTRACT_ID = "newscraft-openapi"
const contract = JSON.parse(
  readFileSync(resolve(process.cwd(), "../contracts/openapi.json"), "utf8"),
) as JsonObject
const ajv = new Ajv({ allErrors: true, strict: false })
addFormats(ajv)
ajv.addSchema(contract, CONTRACT_ID)
const validators = new Map<string, ValidateFunction>()

export const OPERATIONS_FIXTURE = {
  generated_at: "2026-07-13T08:00:00Z",
  global_paused: false,
  dry_run: true,
  components: {},
  queue_counts: {},
  attention: [
    {
      id: "job:contract-error",
      severity: "error",
      kind: "generation",
      title: "Generation requires review",
      occurred_at: "2026-07-13T07:59:00Z",
      action_url: "/jobs?status=needs_review",
    },
  ],
  outbound_proxy: {
    mode: "direct",
    scheme: null,
    bypass_rule_count: 0,
    last_connectivity_status: "not_checked",
    configuration_error_code: null,
  },
} satisfies components["schemas"]["OperationsSnapshotOut"]

export const OPERATIONAL_HEALTH_FIXTURE = {
  generated_at: "2026-07-13T08:00:00Z",
  state: "healthy",
  state_definitions: {
    healthy: "Fresh and available.",
    stale: "Observation is older than warning threshold.",
    unavailable: "Required path cannot serve work.",
    unknown: "No trustworthy observation is available.",
  },
  dependencies: {
    database: {
      state: "healthy",
      code: "database_connected",
      observed_at: "2026-07-13T08:00:00Z",
      latency_ms: 12,
      message: "Database connectivity is available",
      runbook_url: "/docs/operations/readiness-and-health#database-unavailable",
    },
    schema: {
      state: "healthy",
      code: "schema_current",
      observed_at: "2026-07-13T08:00:00Z",
      latency_ms: 12,
      message: "Database schema is current",
      runbook_url: "/docs/operations/readiness-and-health#schema-mismatch",
    },
  },
  components: {},
  queues: [],
  recoveries: [],
  alerts: [],
  metrics: {},
  outbound_proxy: {
    mode: "direct",
    scheme: null,
    bypass_rule_count: 0,
    last_connectivity_status: "not_checked",
    configuration_error_code: null,
  },
} satisfies components["schemas"]["OperationalHealthSnapshot"]

export const RECONCILIATION_FIXTURE = [] satisfies components["schemas"]["ReconciliationCase"][]

export const AVAILABLE_CAPABILITY_FIXTURE = {
  status: "available",
  owner: "browser-test",
  observed_at: "2026-07-13T08:00:00Z",
  expires_at: "2026-07-13T08:05:00Z",
  failure_code: "available",
} satisfies components["schemas"]["CapabilityStatus"]

export function assertContractResponse(
  method: string,
  path: string,
  status: number,
  body: unknown,
): void {
  const normalizedMethod = method.toLowerCase() as HttpMethod
  const contractPath = resolveContractPath(path)
  const key = `${normalizedMethod} ${contractPath} ${status}`
  let validate = validators.get(key)
  if (!validate) {
    const pointer = [
      "paths",
      contractPath,
      normalizedMethod,
      "responses",
      String(status),
      "content",
      "application/json",
      "schema",
    ].map(escapePointer).join("/")
    validate = ajv.compile({ $ref: `${CONTRACT_ID}#/${pointer}` })
    validators.set(key, validate)
  }
  if (!validate(body)) {
    throw new Error(`Mock response violates ${key}: ${ajv.errorsText(validate.errors)}`)
  }
}

export async function fulfillMockJson(route: Route, body: unknown, status = 200): Promise<void> {
  const request = route.request()
  const path = new URL(request.url()).pathname.replace(/^\/api\/backend/, "")
  if (status !== 501) assertContractResponse(request.method(), path, status, body)
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
}

export async function installMockBackend(
  page: Page,
  options: MockBackendOptions = {},
): Promise<string[]> {
  const unhandledRequests: string[] = []
  let dateTimeSettings = {
    timezone: "Asia/Tehran",
    updated_at: "2026-07-13T08:00:00Z",
  }

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api\/backend/, "")
    const method = request.method()

    if (path === "/operator-settings/date-time" && method === "GET") {
      await fulfillContractJson(route, method, path, dateTimeSettings)
      return
    }
    if (path === "/operator-settings/date-time" && method === "PUT") {
      const body = request.postDataJSON() as { timezone: string }
      dateTimeSettings = {
        timezone: body.timezone,
        updated_at: "2026-07-13T08:01:00Z",
      }
      await fulfillContractJson(route, method, path, dateTimeSettings)
      return
    }
    if (method === "GET" && path === "/automation-control") {
      await fulfillContractJson(route, method, path, {
        global_pause: false,
        dry_run: true,
        pause_reason: null,
        paused_at: null,
        updated_at: "2026-07-13T08:00:00Z",
      })
      return
    }
    if (method === "GET" && path === "/jobs/summary") {
      await fulfillContractJson(route, method, path, {
        queued: 0,
        running: 0,
        attention: 0,
        succeeded_today: 0,
      })
      return
    }
    if (method === "GET" && path === "/jobs") {
      await fulfillContractJson(route, method, path, { items: [] })
      return
    }
    if (method === "GET" && path === "/telegram/publication-outcomes") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/stories") {
      const search = url.searchParams.get("search")?.trim().toLocaleLowerCase()
      const stories = search
        ? (options.stories ?? []).filter((story) => story.title.toLocaleLowerCase().includes(search))
        : options.stories ?? []
      const requestedLimit = Number(url.searchParams.get("limit") ?? "100")
      const limit = Number.isInteger(requestedLimit) ? Math.min(Math.max(requestedLimit, 1), 100) : 100
      const cursor = url.searchParams.get("cursor")
      const offset = cursor?.startsWith("offset:") ? Number(cursor.slice("offset:".length)) : 0
      const safeOffset = Number.isInteger(offset) && offset >= 0 ? offset : 0
      const nextOffset = safeOffset + limit
      await fulfillContractJson(route, method, path, {
        items: stories.slice(safeOffset, nextOffset),
        next_cursor: nextOffset < stories.length ? `offset:${nextOffset}` : null,
      })
      return
    }
    if (method === "GET" && path === "/telegram/automations") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/automations") {
      await fulfillContractJson(route, method, path, { items: options.automations ?? [], next_cursor: null })
      return
    }
    if (method === "GET" && path === "/automation-node-catalog") {
      await fulfillContractJson(route, method, path, {
        schema_version: 1,
        max_nodes: 30,
        max_edges: 60,
        nodes: [],
      })
      return
    }
    if (method === "GET" && path === "/telegram/automations/options") {
      await fulfillContractJson(route, method, path, {
        sources: [],
        destinations: [],
        brand_profiles: [],
        prompt_template_versions: [],
        ai_provider_profiles: [],
      })
      return
    }
    if (method === "GET" && path === "/brand-profiles") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/prompt-templates") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/llm-providers") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/telegram/destinations") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/telegram/proxies") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/codex-gateway/connections") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/codex-gateway/activity") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/content-pack-requests") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/calendar") {
      await fulfillContractJson(route, method, path, {
        items: [],
        timezone: url.searchParams.get("timezone") ?? "Asia/Tehran",
      })
      return
    }
    if (method === "GET" && path === "/operations/diagnostics") {
      if (options.operationsDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.operationsDelayMs))
      }
      if (options.operationsFailure) {
        await route.abort("failed")
        return
      }
      await fulfillContractJson(route, method, path, options.operations ?? OPERATIONS_FIXTURE)
      return
    }
    if (method === "GET" && path === "/operations/health") {
      if (options.operationsDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.operationsDelayMs))
      }
      if (options.operationsFailure) {
        await route.abort("failed")
        return
      }
      await fulfillContractJson(route, method, path, options.operationalHealth ?? OPERATIONAL_HEALTH_FIXTURE)
      return
    }
    if (method === "GET" && path === "/operations/retention-policy") {
      await fulfillContractJson(route, method, path, {
        id: "global",
        raw_payload_days: 30,
        completed_job_days: 90,
        attempt_metadata_days: 90,
        export_artifact_days: 14,
        unreferenced_media_days: 30,
        created_at: "2026-07-13T08:00:00Z",
        updated_at: "2026-07-13T08:00:00Z",
      })
      return
    }
    if (method === "GET" && path === "/telegram/reconciliation") {
      await fulfillContractJson(route, method, path, RECONCILIATION_FIXTURE)
      return
    }

    const requestLabel = `${method} ${path}${url.search}`
    unhandledRequests.push(requestLabel)
    await route.fulfill({
      status: 501,
      contentType: "application/json",
      body: JSON.stringify({ detail: `Unhandled deterministic test request: ${requestLabel}` }),
    })
  })

  return unhandledRequests
}

async function fulfillContractJson(
  route: Route,
  method: string,
  path: string,
  body: unknown,
  status = 200,
): Promise<void> {
  assertContractResponse(method, path, status, body)
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

function escapePointer(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1")
}

function resolveContractPath(actualPath: string): string {
  const paths = (contract.paths ?? {}) as JsonObject
  if (actualPath in paths) return actualPath
  const matches = Object.keys(paths).filter((candidate) => {
    const pattern = candidate
      .split("/")
      .map((part) => part.startsWith("{") && part.endsWith("}") ? "[^/]+" : escapeRegex(part))
      .join("/")
    return new RegExp(`^${pattern}$`).test(actualPath)
  })
  if (matches.length !== 1) throw new Error(`No unique OpenAPI path matches ${actualPath}`)
  return matches[0]
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

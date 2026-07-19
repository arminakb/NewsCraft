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
  stories?: MockStory[]
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

export const RECONCILIATION_FIXTURE = [] satisfies components["schemas"]["ReconciliationCase"][]

export function assertContractResponse(
  method: string,
  path: string,
  status: number,
  body: unknown,
): void {
  const normalizedMethod = method.toLowerCase() as HttpMethod
  const key = `${normalizedMethod} ${path} ${status}`
  let validate = validators.get(key)
  if (!validate) {
    const pointer = [
      "paths",
      path,
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

export async function installMockBackend(
  page: Page,
  options: MockBackendOptions = {},
): Promise<string[]> {
  const unhandledRequests: string[] = []

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api\/backend/, "")
    const method = request.method()

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
    if (method === "GET" && path === "/telegram/drafts") {
      await fulfillContractJson(route, method, path, [])
      return
    }
    if (method === "GET" && path === "/stories") {
      await fulfillContractJson(route, method, path, {
        items: options.stories ?? [],
        next_cursor: null,
      })
      return
    }
    if (method === "GET" && path === "/telegram/automations") {
      await fulfillContractJson(route, method, path, [])
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
      await fulfillContractJson(route, method, path, OPERATIONS_FIXTURE)
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

import { readFileSync, readdirSync } from "node:fs"
import { resolve } from "node:path"

import { describe, expect, it } from "vitest"

import {
  assertContractResponse,
  OPERATIONS_FIXTURE,
  RECONCILIATION_FIXTURE,
} from "@/e2e/support/mock-backend"

describe("generated OpenAPI mock contract", () => {
  it("accepts the shared diagnostics and reconciliation fixtures", () => {
    expect(() =>
      assertContractResponse("GET", "/operations/diagnostics", 200, OPERATIONS_FIXTURE),
    ).not.toThrow()
    expect(() =>
      assertContractResponse("GET", "/telegram/reconciliation", 200, RECONCILIATION_FIXTURE),
    ).not.toThrow()
  })

  it("rejects a fixture missing a required wire field", () => {
    const { generated_at: _missing, ...invalid } = OPERATIONS_FIXTURE

    expect(() =>
      assertContractResponse("GET", "/operations/diagnostics", 200, invalid),
    ).toThrow(/generated_at/)
  })

  it("rejects an undocumented operation or status", () => {
    expect(() => assertContractResponse("GET", "/removed-route", 200, {})).toThrow()
    expect(() =>
      assertContractResponse("GET", "/operations/diagnostics", 201, OPERATIONS_FIXTURE),
    ).toThrow()
  })

  it("resolves concrete resource URLs to their OpenAPI path templates", () => {
    expect(() => assertContractResponse("GET", "/stories/not-a-uuid", 422, {
      detail: [{
        type: "uuid_parsing",
        loc: ["path", "story_id"],
        msg: "Input should be a valid UUID",
        input: "not-a-uuid",
      }],
    })).not.toThrow()
  })

  it("keeps every mocked browser suite on a fail-closed unmatched-request boundary", () => {
    const e2eRoot = resolve(process.cwd(), "e2e")
    for (const name of readdirSync(e2eRoot).filter((entry) => entry.endsWith(".spec.ts"))) {
      const source = readFileSync(resolve(e2eRoot, name), "utf8")
      expect(
        source.includes("installMockBackend") || (source.includes("Unhandled") && source.includes("501")),
        `${name} must reject unmatched backend requests`,
      ).toBe(true)
      expect(
        source.includes("installMockBackend") || source.includes("fulfillMockJson"),
        `${name} must validate JSON responses against OpenAPI`,
      ).toBe(true)
    }
  })

  it("keeps covered operations transport types on the generated wire boundary", () => {
    const source = readFileSync(resolve(process.cwd(), "features/operations/api.ts"), "utf8")
    expect(source).toContain('from "@/lib/api/generated"')
    expect(source).not.toContain("type BackendOperationsSnapshot = {")
    expect(source).not.toContain("type BackendReconciliationCase = {")
    expect(source).not.toContain("type BackendHistoryPage = {")
  })
})

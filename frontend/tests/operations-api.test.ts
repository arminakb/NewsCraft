import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  fetchOperationsDiagnostics,
  fetchOperationsHistory,
  fetchReconciliationCases,
} from "@/features/operations/api"
import { apiRequest } from "@/lib/http"

vi.mock("@/lib/http", () => ({ apiRequest: vi.fn() }))

describe("operations generated wire/domain boundary", () => {
  beforeEach(() => vi.resetAllMocks())

  it("normalizes optional generated diagnostics fields to explicit null", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      generated_at: "2026-07-13T08:00:00Z",
      global_paused: false,
      dry_run: true,
      components: {},
      queue_counts: { queued: 2 },
      attention: [],
      outbound_proxy: {
        mode: "direct",
        bypass_rule_count: 0,
        last_connectivity_status: "not_checked",
      },
    })

    await expect(fetchOperationsDiagnostics()).resolves.toMatchObject({
      generatedAt: "2026-07-13T08:00:00Z",
      queueCounts: { queued: 2 },
      outboundProxy: { scheme: null, configurationErrorCode: null },
    })
    expect(apiRequest).toHaveBeenCalledWith("/operations/diagnostics")
  })

  it("maps UTC history timestamps, enum categories, metadata, and null cursor", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      items: [
        {
          id: "event-1",
          occurred_at: "2026-07-13T08:00:00Z",
          category: "reconcile",
          status: "confirmed",
          title: "Publication reconciled",
          summary: "Operator confirmed the remote publication.",
          job_id: null,
          subject_url: "/diagnostics",
          sanitized_metadata: { operation_count: 1 },
        },
      ],
      next_cursor: null,
    })

    await expect(fetchOperationsHistory({ limit: 25 })).resolves.toEqual({
      items: [
        {
          id: "event-1",
          occurredAt: "2026-07-13T08:00:00Z",
          category: "reconcile",
          status: "confirmed",
          title: "Publication reconciled",
          summary: "Operator confirmed the remote publication.",
          jobId: null,
          subjectUrl: "/diagnostics",
          sanitizedMetadata: { operation_count: 1 },
        },
      ],
      nextCursor: null,
    })
    expect(apiRequest).toHaveBeenCalledWith("/operations/history?limit=25")
  })

  it("uses the generated reconciliation list contract", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([])

    await expect(fetchReconciliationCases()).resolves.toEqual([])
    expect(apiRequest).toHaveBeenCalledWith("/telegram/reconciliation")
  })
})

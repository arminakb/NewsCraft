import { afterEach, describe, expect, it, vi } from "vitest"

import {
  createAutomation,
  createAutomationVersion,
  getAutomationRun,
  getAutomationRuns,
  getAutomationNodeCatalog,
  getAutomationResourceCatalog,
  getAutomations,
  startAutomationRun,
  validateAutomationVersion,
} from "@/features/automations/automation-api"
import type { WorkflowGraph } from "@/features/automations/automation-types"
import { emptyWorkflowGraph } from "@/features/automations/workflow-editor-state"
import { queryKeys } from "@/lib/query-keys"

const graph: WorkflowGraph = {
  schemaVersion: 1,
  entryNodeId: "trigger-1",
  nodes: [
    { id: "trigger-1", type: "manual", config: { storyRevisionId: "11111111-1111-4111-8111-111111111111" } },
    { id: "draft-1", type: "save_drafts", config: {} },
  ],
  edges: [{ sourceNodeId: "trigger-1", sourcePort: "story", targetNodeId: "draft-1", targetPort: "drafts" }],
  outputNodeIds: ["draft-1"],
  metadata: { layout: { TriggerNode: { x: 80, y: 120 } } },
}

afterEach(() => vi.unstubAllGlobals())

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
}

describe("generalized Automation API", () => {
  it("uses bounded list query parameters and camelizes responses", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>((_input, _init) => response({ items: [], next_cursor: "next" }))
    vi.stubGlobal("fetch", fetch)

    await expect(getAutomations({ limit: 25, cursor: "cursor", includeArchived: true })).resolves.toEqual({
      items: [],
      nextCursor: "next",
    })
    expect(fetch).toHaveBeenCalledWith(
      "/api/backend/automations?limit=25&cursor=cursor&include_archived=true",
      undefined,
    )
  })

  it("forwards cancellation to Automation reads", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>((_input, _init) => response({ items: [], next_cursor: null }))
    vi.stubGlobal("fetch", fetch)
    const controller = new AbortController()

    await getAutomations({ limit: 25 }, controller.signal)

    expect(fetch).toHaveBeenCalledWith(
      "/api/backend/automations?limit=25",
      { signal: controller.signal },
    )
  })

  it("sends canonical snake-case graph input and idempotency keys", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>((_input, _init) => response({ id: "automation" }))
    vi.stubGlobal("fetch", fetch)

    await createAutomation({ name: "Workflow", graph }, "create-1")
    await createAutomationVersion("automation", { expectedRevision: 1, graph }, "save-2")

    const first = fetch.mock.calls[0][1] as RequestInit
    expect(first.headers).toMatchObject({ "Idempotency-Key": "create-1", "content-type": "application/json" })
    expect(JSON.parse(first.body as string)).toMatchObject({
      name: "Workflow",
      graph: {
        schema_version: 1,
        entry_node_id: "trigger-1",
        output_node_ids: ["draft-1"],
        metadata: { layout: { TriggerNode: { x: 80, y: 120 } } },
      },
    })
    const second = fetch.mock.calls[1][1] as RequestInit
    expect(second.headers).toMatchObject({ "Idempotency-Key": "save-2" })
    expect(JSON.parse(second.body as string).expected_revision).toBe(1)
  })

  it("serializes an empty workflow without inserting graph defaults", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>((_input, _init) => response({ id: "version" }))
    vi.stubGlobal("fetch", fetch)

    await createAutomationVersion("automation", { expectedRevision: 1, graph: emptyWorkflowGraph() }, "empty-save")

    expect(JSON.parse((fetch.mock.calls[0][1] as RequestInit).body as string)).toMatchObject({
      graph: {
        entry_node_id: "",
        nodes: [],
        edges: [],
        output_node_ids: [],
        metadata: { layout: {} },
      },
    })
  })

  it("uses safe catalog and validation endpoints", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>((_input, _init) => response({
      schema_version: 1,
      max_nodes: 30,
      max_edges: 60,
      nodes: [],
    }))
    vi.stubGlobal("fetch", fetch)

    await getAutomationNodeCatalog()
    await getAutomationResourceCatalog(
      [{ kind: "provider", id: "11111111-1111-4111-8111-111111111111" }],
      "automation",
    )
    await validateAutomationVersion("automation", 2)

    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/backend/automation-node-catalog",
      "/api/backend/automation-resource-catalog",
      "/api/backend/automations/automation/versions/2/validate",
    ])
    const resourceBody = JSON.parse((fetch.mock.calls[1][1] as RequestInit).body as string)
    expect(resourceBody).toEqual({
      resources: [{ kind: "provider", id: "11111111-1111-4111-8111-111111111111" }],
      automation_id: "automation",
    })
  })

  it("uses persisted run endpoints with bounded filters and dry-run idempotency", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>((_input, _init) => response({ items: [], next_cursor: null }))
    vi.stubGlobal("fetch", fetch)

    await getAutomationRuns("automation", {
      limit: 20,
      cursor: "run-cursor",
      status: "failed",
      dryRun: true,
      dateFrom: "2026-08-01T00:00:00.000Z",
      dateTo: "2026-08-01T23:59:59.999Z",
      failedOnly: true,
    })
    await getAutomationRun("run-1")
    await startAutomationRun("automation", { versionNumber: 3, dryRun: true, storyId: "story-1" }, "run-key")

    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/backend/automations/automation/runs?limit=20&cursor=run-cursor&status=failed&dry_run=true&date_from=2026-08-01T00%3A00%3A00.000Z&date_to=2026-08-01T23%3A59%3A59.999Z&failed_only=true",
      "/api/backend/automation-runs/run-1",
      "/api/backend/automations/automation/runs",
    ])
    const runRequest = fetch.mock.calls[2][1] as RequestInit
    expect(runRequest.headers).toMatchObject({ "Idempotency-Key": "run-key" })
    expect(JSON.parse(runRequest.body as string)).toEqual({ version_number: 3, dry_run: true, story_id: "story-1" })
  })

  it("keeps generalized query keys separate from legacy Telegram keys", () => {
    expect(queryKeys.automations()).toEqual(["automations", {}])
    expect(queryKeys.automation("id")).toEqual(["automations", "id"])
    expect(queryKeys.automationVersions("id")).toEqual(["automations", "id", "versions"])
    expect(queryKeys.automationVersion("id", 3)).toEqual(["automations", "id", "versions", 3])
    expect(queryKeys.automationTemplates).toEqual(["automations", "templates"])
    expect(queryKeys.automationRuns("id", { limit: 20 })).toEqual(["automations", "id", "runs", { limit: 20 }])
    expect(queryKeys.telegramRoutes).toEqual(["telegram", "routes"])
  })
})

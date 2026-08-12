import { describe, expect, it } from "vitest"

import type { AutomationNodeCatalog, AutomationNodeDefinition } from "@/features/automations/automation-types"
import { defaultConfig, normalizeWorkflowGraphForSave, type JsonSchema } from "@/features/automations/workflow-graph"

const nodeSchemas: Array<[string, JsonSchema]> = [
  ["manual", { type: "object", properties: { storyRevisionId: { type: "string" } } }],
  ["collection_article_added", { type: "object", properties: { collectionId: { type: "string" } } }],
  ["new_source_item", { type: "object", properties: { sourceIds: { type: "array", items: { type: "string" } } } }],
  ["schedule", { type: "object", properties: { scheduleKind: { type: "string", default: "daily" }, timezone: { type: "string", default: "Asia/Tehran" }, localTime: { type: "string" }, intervalMinutes: { type: "integer" }, catchUpLimit: { type: "integer", default: 1 } } }],
  ["select_content", { type: "object", properties: { sourceIds: { type: "array", items: { type: "string" } }, languages: { type: "array", items: { type: "string" } }, topics: { type: "array", items: { type: "string" } }, contentTypes: { type: "array", items: { type: "string" } }, minimumScore: { type: "integer" }, requireMedia: { type: "boolean" }, sort: { type: "string", default: "newest" }, maxCount: { type: "integer", default: 20 } } }],
  ["filter_content", { type: "object", properties: { includeTerms: { type: "array", items: { type: "string" } }, excludeTerms: { type: "array", items: { type: "string" } }, minTextCharacters: { type: "integer", default: 1 }, requireMedia: { type: "boolean", default: false } } }],
  ["research", { type: "object", properties: { providerProfileId: { type: "string" }, mode: { type: "string", default: "auto_if_incomplete" }, queryBudget: { type: "integer", default: 3 }, pageBudget: { type: "integer", default: 10 }, timeBudgetSeconds: { type: "integer", default: 120 } } }],
  ["generate_content_pack", { type: "object", properties: { editorialProfileId: { type: "string" }, providerProfileId: { type: "string" }, promptVersionIds: { type: "array", items: { type: "string" }, minItems: 1 }, promptChecksums: { type: "object", additionalProperties: { type: "string" } }, platforms: { type: "array", items: { type: "string" }, minItems: 1 } } }],
  ["validate", { type: "object", properties: { validatorIds: { type: "array", items: { type: "string" }, minItems: 1 } } }],
  ["human_review", { type: "object", properties: { instructions: { type: "string" } } }],
  ["save_drafts", { type: "object", properties: {} }],
  ["manual_package", { type: "object", properties: { platforms: { type: "array", items: { type: "string" }, minItems: 1 } } }],
  ["telegram_publish", { type: "object", properties: { destinationId: { type: "string" }, quietHours: { type: "object", additionalProperties: { type: "string" } }, retryPolicy: { type: "object", additionalProperties: { type: "integer" } } } }],
]

function definition(type: string, configSchema: JsonSchema): AutomationNodeDefinition {
  return {
    type,
    family: "test",
    displayName: type,
    description: "",
    entry: type === "manual",
    terminal: type === "save_drafts" || type === "manual_package" || type === "telegram_publish",
    configSchema,
    inputs: [],
    outputs: [],
    uiHints: {},
    runtimeJobTypes: [],
    runtimeStatus: "existing",
    runtimeOwner: "compiler",
  }
}

function catalog(): AutomationNodeCatalog {
  return {
    schemaVersion: 1,
    maxNodes: 30,
    maxEdges: 60,
    nodes: nodeSchemas.map(([type, configSchema]) => definition(type, configSchema)),
  }
}

function graphWithMetadata(catalogValue: AutomationNodeCatalog) {
  return {
    schemaVersion: 1 as const,
    entryNodeId: "manual-1",
    nodes: catalogValue.nodes.map((node, index) => ({
      id: `${node.type}-${index + 1}`,
      type: node.type,
      config: {
        ...seedConfigProperties(node.configSchema as JsonSchema),
        kind: "article",
        capabilities: ["textual"],
        inputContract: { allOf: ["textual"] },
        outputContract: { kind: "article" },
        preservesInputArtifact: true,
        runtimeState: { selected: true },
      },
    })),
    edges: [],
    outputNodeIds: ["telegram_publish-13"],
    metadata: { layout: { "manual-1": { x: 20, y: 30 } } },
  }
}

function seedConfigProperties(schema: JsonSchema) {
  return Object.fromEntries(Object.keys(schema.properties ?? {}).map((key) => {
    if (key.endsWith("Ids")) return [key, ["saved-id"]]
    if (key === "platforms") return [key, ["telegram"]]
    if (key === "promptChecksums") return [key, { "saved-id": "a".repeat(64) }]
    if (key === "requireMedia") return [key, false]
    if (key === "retryPolicy" || key === "quietHours") return [key, {}]
    return [key, null]
  }))
}

describe("workflow save serialization", () => {
  it("serializes all active nodes from editable schema fields only", () => {
    const catalogValue = catalog()
    const normalized = normalizeWorkflowGraphForSave(graphWithMetadata(catalogValue), catalogValue)

    expect(normalized.nodes).toHaveLength(13)
    expect(normalized.nodes.every((node) => Object.keys(node).sort().join(",") === "config,id,type")).toBe(true)
    for (const node of normalized.nodes) {
      const allowed = new Set(Object.keys((catalogValue.nodes.find((item) => item.type === node.type)!.configSchema as JsonSchema).properties ?? {}).map((key) => key.replace(/_([a-z])/g, (_match, letter: string) => letter.toUpperCase())))
      expect(Object.keys(node.config).every((key) => allowed.has(key))).toBe(true)
      expect(node.config).not.toHaveProperty("kind")
      expect(node.config).not.toHaveProperty("capabilities")
      expect(node.config).not.toHaveProperty("inputContract")
      expect(node.config).not.toHaveProperty("outputContract")
      expect(node.config).not.toHaveProperty("runtimeState")
    }
  })

  it("does not manufacture invalid empty arrays and normalizes legacy config names", () => {
    const catalogValue = catalog()
    const generate = catalogValue.nodes.find((item) => item.type === "generate_content_pack")!
    const validators = catalogValue.nodes.find((item) => item.type === "validate")!
    const manualPackage = catalogValue.nodes.find((item) => item.type === "manual_package")!
    expect(defaultConfig(generate)).not.toHaveProperty("platforms")
    expect(defaultConfig(validators)).not.toHaveProperty("validatorIds")
    expect(defaultConfig(manualPackage)).not.toHaveProperty("platforms")

    const normalized = normalizeWorkflowGraphForSave({
      schemaVersion: 1,
      entryNodeId: "generate-1",
      nodes: [{
        id: "generate-1",
        type: "generate_content_pack",
        configuration: {
          brandProfileId: "legacy-editorial",
          promptTemplateVersionId: "prompt-1",
          promptChecksumSha256: "a".repeat(64),
          kind: "article",
        },
      } as never],
      edges: [],
      outputNodeIds: [],
      metadata: { layout: {} },
    }, catalogValue)

    expect(normalized.nodes[0].config).toMatchObject({
      editorialProfileId: "legacy-editorial",
      promptVersionIds: ["prompt-1"],
      promptChecksums: { "prompt-1": "a".repeat(64) },
    })
    expect(normalized.nodes[0].config).not.toHaveProperty("brandProfileId")
    expect(normalized.nodes[0].config).not.toHaveProperty("promptTemplateVersionId")
    expect(normalized.nodes[0].config).not.toHaveProperty("kind")
  })
})

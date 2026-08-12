import { describe, expect, it } from "vitest"

import type { AutomationNodeCatalog, WorkflowGraph } from "@/features/automations/automation-types"
import { connectWorkflowNodes, validateWorkflowClient } from "@/features/automations/workflow-graph"

const articleCaps = ["textual", "structured", "article", "reviewable", "generatable"] as const
const researchCaps = ["textual", "structured", "research", "reviewable", "generatable"] as const
const draftCaps = ["textual", "structured", "draft", "reviewable"] as const

function catalog(): AutomationNodeCatalog {
  const output = (name: string, kind: "article" | "research" | "draft", capabilities: readonly string[], preservesInputArtifact = false, addsCapabilities: readonly string[] = []) => ({
    name,
    artifactTypes: [name],
    required: true,
    maxConnections: null,
    outputContract: { kind, capabilities: [...capabilities], preservesInputArtifact, addsCapabilities },
  })
  const input = (name: string, allOf: readonly string[], acceptedKinds: readonly ("article" | "research" | "draft")[] = []) => ({
    name,
    artifactTypes: [name],
    required: true,
    maxConnections: 1,
    inputContract: { allOf: [...allOf], anyOf: [], acceptedKinds: [...acceptedKinds] },
  })
  const base = { configSchema: { type: "object", properties: {} }, uiHints: {}, runtimeJobTypes: [], runtimeStatus: "existing" as const, runtimeOwner: "compiler" as const }
  return {
    schemaVersion: 1,
    maxNodes: 30,
    maxEdges: 60,
    nodes: [
      { ...base, type: "collection_article_added", family: "trigger", displayName: "Collection Article Added", description: "", entry: true, terminal: false, inputs: [], outputs: [output("article", "article", articleCaps)] },
      { ...base, type: "research", family: "research", displayName: "AI Research", description: "", entry: false, terminal: false, inputs: [input("story", ["textual"], ["article", "research"])], outputs: [output("story", "research", researchCaps)] },
      { ...base, type: "human_review", family: "review", displayName: "Human Review", description: "", entry: false, terminal: false, inputs: [input("draft", ["reviewable"])], outputs: [output("approved", "research", [], true, ["approved", "publishable"])] },
      { ...base, type: "generate_content_pack", family: "generate", displayName: "AI Generate", description: "", entry: false, terminal: false, inputs: [input("story", ["generatable"], ["article", "research"])], outputs: [output("drafts", "draft", draftCaps)] },
      { ...base, type: "save_drafts", family: "output", displayName: "Save to Drafts", description: "", entry: false, terminal: true, inputs: [input("drafts", ["draft"], ["draft"])], outputs: [] },
    ],
  } as unknown as AutomationNodeCatalog
}

function graph(): WorkflowGraph {
  return {
    schemaVersion: 1 as const,
    entryNodeId: "trigger-1",
    nodes: [
      { id: "trigger-1", type: "collection_article_added", config: { collectionId: "collection-1" } },
      { id: "research-1", type: "research", config: { providerProfileId: "provider-1" } },
      { id: "review-1", type: "human_review", config: {} },
      { id: "generate-1", type: "generate_content_pack", config: { editorialProfileId: "profile-1", providerProfileId: "provider-1", promptVersionIds: ["prompt-1"] } },
      { id: "drafts-1", type: "save_drafts", config: {} },
    ],
    edges: [],
    outputNodeIds: ["drafts-1"],
    metadata: { layout: {} },
  }
}

describe("workflow artifact contracts", () => {
  it("connects research through review into generation using capabilities", () => {
    const catalogValue = catalog()
    let current = graph()
    for (const edge of [
      { sourceNodeId: "trigger-1", sourcePort: "article", targetNodeId: "research-1", targetPort: "story" },
      { sourceNodeId: "research-1", sourcePort: "story", targetNodeId: "review-1", targetPort: "draft" },
      { sourceNodeId: "review-1", sourcePort: "approved", targetNodeId: "generate-1", targetPort: "story" },
      { sourceNodeId: "generate-1", sourcePort: "drafts", targetNodeId: "drafts-1", targetPort: "drafts" },
    ]) {
      const result = connectWorkflowNodes(current, catalogValue, edge)
      expect(result.error).toBeUndefined()
      current = result.graph!
    }

    const validation = validateWorkflowClient(current, catalogValue)
    expect(validation.findings.filter((finding) => finding.severity === "error")).toEqual([])
  })

  it("keeps structural trigger rejection and capability errors", () => {
    const catalogValue = catalog()
    const triggerIncoming = connectWorkflowNodes(graph(), catalogValue, {
      sourceNodeId: "research-1",
      sourcePort: "story",
      targetNodeId: "trigger-1",
      targetPort: "article",
    })
    expect(triggerIncoming.error).toMatch(/trigger/i)

    const incompatible = connectWorkflowNodes(graph(), catalogValue, {
      sourceNodeId: "trigger-1",
      sourcePort: "article",
      targetNodeId: "drafts-1",
      targetPort: "drafts",
    })
    expect(incompatible.error).toMatch(/capabilities/i)
  })
})

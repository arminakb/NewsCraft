import { configuredNodeLabel } from "@/features/automations/workflow-node-visual"
import { emptyWorkflowGraph } from "@/features/automations/workflow-editor-state"
import { connectWorkflowNodes, insertWorkflowNode, validateWorkflowClient, workflowResourceRequests } from "@/features/automations/workflow-graph"
import type { WorkflowGraph } from "@/features/automations/automation-types"

const collectionId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

describe("collection article trigger editing", () => {
  it("can only be placed as the first trigger and starts invalid until configured", () => {
    const empty = insertWorkflowNode(emptyWorkflowGraph(), catalog as never, "collection_article_added")
    expect(empty.graph).toMatchObject({
      entryNodeId: "collection-article-added-1",
      nodes: [{ type: "collection_article_added", config: {} }],
    })
    expect(validateWorkflowClient(empty.graph!, catalog as never).findings).toEqual(
      expect.arrayContaining([expect.objectContaining({ code: "automation_resource_unavailable", fieldPath: "config.collectionId" })]),
    )

    const after = insertWorkflowNode(empty.graph!, catalog as never, "collection_article_added")
    expect(after.graph).toBeUndefined()
    expect(after.error).toMatch(/one trigger/i)

    const configured = {
      ...empty.graph!,
      nodes: [{ ...empty.graph!.nodes[0], config: { collectionId } }],
    }
    expect(validateWorkflowClient(configured, catalog as never).valid).toBe(true)
    expect(workflowResourceRequests(configured)).toEqual([{ kind: "collection", id: collectionId }])
  })

  it("renders the stable Feed collection name and unavailable state", () => {
    const node = { type: "collection_article_added", config: { collectionId } }
    expect(configuredNodeLabel(node, "Collection article added", [{
      id: collectionId,
      kind: "collection",
      displayName: "Reading queue",
      state: "ready",
      reasonCode: null,
      capabilities: ["collection_article_added"],
      referencedByActiveVersion: false,
      manageHref: "/feed",
    }])).toBe("Reading queue")
    expect(configuredNodeLabel(node, "Collection article added", [])).toBe("Loading Feed collection…")
  })

  it("adds an article-processing package after the trigger", () => {
    const trigger = insertWorkflowNode(emptyWorkflowGraph(), articleCatalog as never, "collection_article_added")
    const configured = {
      ...trigger.graph!,
      nodes: [{ ...trigger.graph!.nodes[0], config: { collectionId } }],
    }

    const packageNode = insertWorkflowNode(configured, articleCatalog as never, "generate_content_pack")

    expect(packageNode.error).toBeUndefined()
    expect(packageNode.graph?.edges).toEqual([{
      sourceNodeId: "collection-article-added-1",
      sourcePort: "article",
      targetNodeId: "generate-content-pack-1",
      targetPort: "story",
    }])
    expect(packageNode.graph?.outputNodeIds).toEqual([])

    const outputNode = insertWorkflowNode(packageNode.graph!, articleCatalog as never, "save_drafts")
    expect(outputNode.error).toBeUndefined()
    expect(outputNode.graph?.outputNodeIds).toEqual(["save-drafts-1"])
    expect(validateWorkflowClient(outputNode.graph!, articleCatalog as never).valid).toBe(true)
    expect(validateWorkflowClient(packageNode.graph!, articleCatalog as never).findings).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ code: "edge_port_invalid" })]),
    )

    const incompatible = insertWorkflowNode(configured, articleCatalog as never, "save_drafts")
    expect(incompatible.graph).toBeUndefined()
    expect(incompatible.error).toMatch(/cannot accept output/i)

    const incoming = connectWorkflowNodes(outputNode.graph!, articleCatalog as never, {
      sourceNodeId: "save-drafts-1",
      sourcePort: "missing",
      targetNodeId: "collection-article-added-1",
      targetPort: "article",
    })
    expect(incoming.graph).toBeUndefined()
    expect(incoming.error).toMatch(/trigger/i)
  })

  it("accepts the stable article contract on every article-processing node", () => {
    const trigger = insertWorkflowNode(emptyWorkflowGraph(), articleCatalog as never, "collection_article_added")
    let graph: WorkflowGraph = {
      ...trigger.graph!,
      nodes: [{ ...trigger.graph!.nodes[0], config: { collectionId } }],
    }

    for (const type of ["filter_content", "research", "generate_content_pack", "save_drafts"]) {
      const result = insertWorkflowNode(graph, articleCatalog as never, type)
      expect(result.error).toBeUndefined()
      graph = result.graph!
    }

    expect(validateWorkflowClient(graph, articleCatalog as never).valid).toBe(true)
  })
})

const catalog = {
  schemaVersion: 1,
  maxNodes: 30,
  maxEdges: 60,
  nodes: [
    {
      type: "collection_article_added",
      family: "trigger",
      displayName: "Collection article added",
      description: "Start when a new article is saved to one Feed collection.",
      entry: true,
      terminal: true,
      runtimeStatus: "existing",
      runtimeOwner: "compiler",
      runtimeJobTypes: ["automation.run.start"],
      inputs: [],
      outputs: [{ name: "article", artifactTypes: ["article.collection_added"], required: true, maxConnections: null }],
      configSchema: { type: "object", properties: { collectionId: { type: ["string", "null"] } } },
      uiHints: { icon: "file-text" },
    },
  ],
}

const articleCatalog = {
  ...catalog,
  nodes: [
    ...catalog.nodes,
    {
      type: "filter_content",
      family: "select_filter",
      displayName: "Filter content",
      description: "Pass or stop using deterministic allowlisted rules.",
      entry: false,
      terminal: false,
      runtimeStatus: "existing",
      runtimeOwner: "generation",
      runtimeJobTypes: ["telegram.route.process"],
      inputs: [{ name: "story", artifactTypes: ["story.revision_ref", "article.collection_added"], required: true, maxConnections: 1 }],
      outputs: [{ name: "accepted", artifactTypes: ["story.revision_ref", "article.collection_added"], required: true, maxConnections: null }],
      configSchema: { type: "object", properties: {} },
      uiHints: { icon: "filter" },
    },
    {
      type: "research",
      family: "research",
      displayName: "AI Research",
      description: "Add bounded source-grounded research evidence.",
      entry: false,
      terminal: false,
      runtimeStatus: "existing",
      runtimeOwner: "generation",
      runtimeJobTypes: ["research_story"],
      inputs: [{ name: "story", artifactTypes: ["story.revision_ref", "article.collection_added"], required: true, maxConnections: 1 }],
      outputs: [{ name: "story", artifactTypes: ["story.researched_revision_ref"], required: true, maxConnections: null }],
      configSchema: { type: "object", properties: { providerProfileId: { type: "string", default: "ffffffff-ffff-4fff-8fff-ffffffffffff" } } },
      uiHints: { icon: "search" },
    },
    {
      type: "generate_content_pack",
      family: "generate",
      displayName: "Generate content package",
      description: "Generate bounded reviewable platform drafts.",
      entry: false,
      terminal: false,
      runtimeStatus: "existing",
      runtimeOwner: "generation",
      runtimeJobTypes: ["content_pack.generate"],
      inputs: [{ name: "story", artifactTypes: ["story.revision_ref", "story.researched_revision_ref", "story.revision_set_ref", "article.collection_added"], required: true, maxConnections: 1 }],
      outputs: [{ name: "drafts", artifactTypes: ["draft.revision_set_ref"], required: true, maxConnections: null }],
      configSchema: {
        type: "object",
        properties: {
          editorialProfileId: { type: "string", default: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" },
          providerProfileId: { type: "string", default: "ffffffff-ffff-4fff-8fff-ffffffffffff" },
          promptVersionIds: { type: "array", items: { type: "string" }, default: ["11111111-1111-4111-8111-111111111111"] },
        },
      },
      uiHints: { icon: "sparkles" },
    },
    {
      type: "save_drafts",
      family: "output",
      displayName: "Save to Drafts",
      description: "Persist drafts.",
      entry: false,
      terminal: true,
      runtimeStatus: "existing",
      runtimeOwner: "compiler",
      runtimeJobTypes: [],
      inputs: [{ name: "drafts", artifactTypes: ["draft.revision_set_ref"], required: true, maxConnections: 1 }],
      outputs: [],
      configSchema: { type: "object", properties: {} },
      uiHints: { icon: "file-check" },
    },
  ],
}

import { configuredNodeLabel } from "@/features/automations/workflow-node-visual"
import { emptyWorkflowGraph } from "@/features/automations/workflow-editor-state"
import { insertWorkflowNode, validateWorkflowClient, workflowResourceRequests } from "@/features/automations/workflow-graph"

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
      outputs: [{ name: "article", artifactTypes: ["article.collection_added"], required: false, maxConnections: null }],
      configSchema: { type: "object", properties: { collectionId: { type: ["string", "null"] } } },
      uiHints: { icon: "file-text" },
    },
  ],
}

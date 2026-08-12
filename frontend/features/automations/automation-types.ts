import type { components } from "@/lib/api/generated"
import type { Camelized } from "@/lib/camelize"

type Schemas = components["schemas"]

export type ArtifactCapability = NonNullable<Schemas["ArtifactInputContract"]["all_of"]>[number]
export type ArtifactKind = NonNullable<Schemas["ArtifactOutputContract"]["kind"]>
export type ArtifactInputContract = Camelized<Schemas["ArtifactInputContract"]>
export type ArtifactOutputContract = Camelized<Schemas["ArtifactOutputContract"]>
type GeneratedWorkflowArtifact = Camelized<Schemas["WorkflowArtifact_object_"]>
export type WorkflowArtifact<TPayload = unknown> = Omit<GeneratedWorkflowArtifact, "payload"> & { payload: TPayload }

type GeneratedWorkflowGraph = Camelized<Schemas["WorkflowGraphV1"]>
type GeneratedWorkflowNode = Camelized<Schemas["WorkflowNode"]>

export type WorkflowNode = Omit<GeneratedWorkflowNode, "config"> & { config: Record<string, unknown> }
export type WorkflowEdge = Camelized<Schemas["WorkflowEdge"]>
export type WorkflowGraph = Omit<GeneratedWorkflowGraph, "nodes" | "edges" | "metadata"> & {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  metadata: { layout: Record<string, { x: number; y: number }> }
}
type GeneratedAutomation = Camelized<Schemas["AutomationOut"]>
export type AutomationPreviewStage = {
  nodeId: string
  nodeType: string
  label: string
  category: "trigger" | "content" | "ai" | "validation" | "review" | "draft" | "publish" | "unknown"
  platforms: AutomationPlatform[]
  needsAttention: boolean
}
export type AutomationPlatform = "telegram" | "instagram" | "x" | "blog" | "draft" | "multi" | "unknown"
export type AutomationPreview = {
  version: number
  versionState: "active" | "draft"
  stages: AutomationPreviewStage[]
  outputPlatforms: AutomationPlatform[]
  valid: boolean | null
  runCount: number
  successRate: number | null
  lastRunAt: string | null
  lastOutcome: string | null
}
export type Automation = Omit<GeneratedAutomation, "preview"> & { preview?: AutomationPreview | null }
type GeneratedAutomationDetail = Camelized<Schemas["AutomationDetailOut"]>
type GeneratedAutomationVersion = Camelized<Schemas["AutomationVersionOut"]>
type GeneratedAutomationTemplate = Camelized<Schemas["AutomationTemplateOut"]>

export type AutomationDetail = Omit<GeneratedAutomationDetail, "draftVersion" | "activeVersion"> & {
  draftVersion: AutomationVersion | null
  activeVersion: AutomationVersion | null
}
export type AutomationPage = Camelized<Schemas["AutomationPageOut"]>
export type AutomationVersion = Omit<GeneratedAutomationVersion, "graph"> & { graph: WorkflowGraph }
type GeneratedAutomationVersionPage = Camelized<Schemas["AutomationVersionPageOut"]>
export type AutomationVersionPage = Omit<GeneratedAutomationVersionPage, "items"> & { items: AutomationVersion[] }
export type AutomationTemplate = Omit<GeneratedAutomationTemplate, "graphSeed"> & { graphSeed: WorkflowGraph }
export type AutomationNodeCatalog = Camelized<Schemas["AutomationNodeCatalogOut"]>
export type AutomationResourceCatalog = Camelized<Schemas["AutomationResourceCatalogOut"]>
export type AutomationResourceKind = "source" | "provider" | "prompt_version" | "editorial_profile" | "destination" | "collection"
type GeneratedAutomationResource = Camelized<Schemas["AutomationResourceOut"]>
type GeneratedAutomationResourceRequest = Camelized<Schemas["ResourceRequest"]>
export type AutomationResource = Omit<GeneratedAutomationResource, "kind"> & { kind: AutomationResourceKind }
export type AutomationResourceRequest = Omit<GeneratedAutomationResourceRequest, "kind"> & { kind: AutomationResourceKind }
export type GraphValidation = Camelized<Schemas["GraphValidationResult"]>
export type ValidationFinding = Camelized<Schemas["ValidationFinding"]>
export type AutomationNodeDefinition = Camelized<Schemas["NodeCatalogItemOut"]>
export type AutomationPortDefinition = Camelized<Schemas["PortCatalogOut"]>
type GeneratedAutomationRun = Camelized<Schemas["AutomationRunOut"]>
type GeneratedAutomationRunPage = Camelized<Schemas["AutomationRunPageOut"]>
export type AutomationNodeRun = Camelized<Schemas["AutomationNodeRunOut"]>
export type AutomationRun = Omit<GeneratedAutomationRun, "nodes"> & { nodes: AutomationNodeRun[] }
export type AutomationRunPage = Omit<GeneratedAutomationRunPage, "items"> & { items: AutomationRun[] }

export type AutomationListFilters = {
  limit?: number
  cursor?: string | null
  includeArchived?: boolean
}

export type AutomationCreateInput = {
  name: string
  description?: string | null
  graph: WorkflowGraph
  creationReason?: string
}

export type AutomationPatchInput = {
  expectedRevision: number
  name?: string
  description?: string | null
}

export type AutomationVersionInput = {
  expectedRevision: number
  graph: WorkflowGraph
  creationReason?: string
}

export type AutomationTemplateCreateInput = {
  name?: string | null
  description?: string | null
}

export type AutomationRunFilters = {
  limit?: number
  cursor?: string | null
  status?: string | null
  dryRun?: boolean | null
  dateFrom?: string | null
  dateTo?: string | null
  failedOnly?: boolean
}

export type AutomationRunStartInput = {
  versionNumber?: number | null
  dryRun?: boolean
  sourceMessageId?: number | null
  storyId?: string | null
  storyRevisionId?: string | null
}

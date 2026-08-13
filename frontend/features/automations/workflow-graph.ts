/**
 * Workflow Graph v1 editing surface.
 *
 * The implementation is split by responsibility — field policy, topology,
 * artifact contracts, config schema, edits and validation — and re-exported
 * here so call sites keep importing one module.
 */

export { isUnsafeWorkflowField } from "./workflow-field-policy"
export { catalogDefinition, orderedWorkflowNodes } from "./workflow-graph-topology"
export { type CompatibilityStatus, compatiblePortPairs, connectionCompatibility } from "./workflow-graph-contracts"
export {
  type JsonSchema,
  defaultConfig,
  normalizeWorkflowGraphForSave,
  resolveSchema,
  serializeWorkflowGraph,
  workflowResourceRequests,
} from "./workflow-config-schema"
export {
  type GraphEditResult,
  type WorkflowNodeActionState,
  connectWorkflowNodes,
  deleteWorkflowNode,
  duplicateWorkflowNode,
  insertWorkflowNode,
  moveWorkflowNode,
  updateNodeConfig,
  updateNodePosition,
  workflowNodeActionState,
} from "./workflow-graph-edits"
export { validateWorkflowClient } from "./workflow-graph-validation"

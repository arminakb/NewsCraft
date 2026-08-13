import { isIdentifierField, isTransientDuplicateField } from "./workflow-field-policy"
import { catalogDefinition } from "./workflow-graph-topology"

import type {
  AutomationNodeCatalog,
  AutomationNodeDefinition,
  AutomationResourceRequest,
  WorkflowGraph,
  WorkflowNode,
} from "./automation-types"

/**
 * JSON-Schema-driven node configuration: defaults, the save-boundary
 * normalization (including legacy alias migration) and the schema-aware clone
 * used when a node is duplicated.
 */

const legacyConfigAliases: Record<string, Record<string, string>> = {
  generate_content_pack: {
    brandProfileId: "editorialProfileId",
    brand_profile_id: "editorialProfileId",
  },
  new_source_item: {
    sourceId: "sourceIds",
    source_id: "sourceIds",
  },
  validate: {
    validators: "validatorIds",
    validator_ids: "validatorIds",
  },
  manual_package: {
    platform: "platforms",
  },
}

const resourceFields: Record<string, AutomationResourceRequest["kind"]> = {
  collectionId: "collection",
  sourceId: "source",
  sourceIds: "source",
  providerProfileId: "provider",
  editorialProfileId: "editorial_profile",
  promptTemplateVersionId: "prompt_version",
  promptVersionIds: "prompt_version",
  destinationId: "destination",
}

export type JsonSchema = {
  type?: string | string[]
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  anyOf?: JsonSchema[]
  properties?: Record<string, JsonSchema>
  additionalProperties?: boolean | JsonSchema
  items?: JsonSchema
  minItems?: number
  maxItems?: number
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  pattern?: string
  format?: string
}

export function resolveSchema(schema: JsonSchema): JsonSchema {
  return schema.anyOf?.find((item) => item.type !== "null") ?? schema
}

export function defaultConfig(definition: AutomationNodeDefinition): Record<string, unknown> {
  const schema = definition.configSchema as JsonSchema
  const properties = schema.properties ?? {}
  return Object.fromEntries(Object.entries(properties).flatMap(([key, value]) => {
    const field = resolveSchema(value)
    if (field.default !== undefined) return [[key, structuredClone(field.default)]]
    if (field.type === "array" && (field.minItems === undefined || field.minItems === 0)) return [[key, []]]
    if (field.type === "boolean") return [[key, false]]
    return []
  }))
}

/**
 * Rebuild the graph boundary from catalog-backed editable fields.
 * Artifact contracts and editor/runtime metadata belong to the catalog/UI,
 * never to WorkflowNode.config.
 */
export function normalizeWorkflowGraphForSave(graph: WorkflowGraph, catalog: AutomationNodeCatalog): WorkflowGraph {
  const layout = Object.fromEntries(
    Object.entries(graph.metadata?.layout ?? {}).flatMap(([nodeId, point]) => (
      point && Number.isFinite(point.x) && Number.isFinite(point.y)
        ? [[nodeId, { x: point.x, y: point.y }]]
        : []
    )),
  )
  return {
    schemaVersion: 1,
    entryNodeId: graph.entryNodeId,
    nodes: graph.nodes.map((node) => {
      const definition = catalogDefinition(catalog, node.type)
      const rawConfig = workflowNodeConfig(node)
      return {
        id: node.id,
        type: node.type,
        config: definition ? normalizeNodeConfig(node.type, rawConfig, definition.configSchema as JsonSchema) : structuredClone(rawConfig),
      }
    }),
    edges: graph.edges.map((edge) => ({
      sourceNodeId: edge.sourceNodeId,
      sourcePort: edge.sourcePort,
      targetNodeId: edge.targetNodeId,
      targetPort: edge.targetPort,
    })),
    outputNodeIds: [...graph.outputNodeIds],
    metadata: { layout },
  }
}

/** Alias kept explicit for save-request call sites and serialization tests. */
export const serializeWorkflowGraph = normalizeWorkflowGraphForSave

export function workflowResourceRequests(graph: WorkflowGraph): AutomationResourceRequest[] {
  const values = new Map<string, AutomationResourceRequest>()
  for (const node of graph.nodes) {
    for (const [field, kind] of Object.entries(resourceFields)) {
      const raw = node.config[field]
      const ids = Array.isArray(raw) ? raw : [raw]
      for (const id of ids) {
        if (typeof id !== "string" || !id) continue
        values.set(`${kind}:${id}`, { kind, id })
      }
    }
  }
  return [...values.values()].sort((a, b) => `${a.kind}:${a.id}`.localeCompare(`${b.kind}:${b.id}`))
}

/** Clone a node config for duplication, dropping transient and identifier fields. */
export function duplicateEditableConfig(config: Record<string, unknown>, schema: JsonSchema): Record<string, unknown> {
  const cloned = cloneEditableValue(config, resolveSchema(schema), "")
  return cloned && typeof cloned === "object" && !Array.isArray(cloned) ? cloned as Record<string, unknown> : {}
}

function cloneEditableValue(value: unknown, schema: JsonSchema, fieldName: string): unknown {
  if (isTransientDuplicateField(fieldName)) return undefined
  const resolved = resolveSchema(schema)
  if (Array.isArray(value)) {
    return value
      .map((item) => cloneEditableValue(item, resolved.items ? resolveSchema(resolved.items) : {}, fieldName))
      .filter((item) => item !== undefined)
  }
  if (!value || typeof value !== "object") {
    return makeDuplicatedIdentifier(value, fieldName)
  }
  if (!resolved.properties) return structuredClone(value)
  const output: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (!Object.prototype.hasOwnProperty.call(resolved.properties, key)) continue
    const cloned = cloneEditableValue(item, resolved.properties[key], key)
    if (cloned !== undefined) output[key] = cloned
  }
  return output
}

function makeDuplicatedIdentifier(value: unknown, fieldName: string): unknown {
  if (typeof value !== "string" || !isIdentifierField(fieldName)) return structuredClone(value)
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `${value}-copy-${suffix}`
}

function normalizeNodeConfig(nodeType: string, rawConfig: Record<string, unknown>, schema: JsonSchema): Record<string, unknown> {
  const source = applyLegacyConfigAliases(nodeType, rawConfig)
  const output: Record<string, unknown> = {}
  for (const [schemaKey, fieldSchema] of Object.entries(resolveSchema(schema).properties ?? {})) {
    const key = camelizeConfigKey(schemaKey)
    const sourceKey = findConfigKey(source, key)
    if (!sourceKey) continue
    const value = normalizeConfigValue(source[sourceKey], fieldSchema)
    if (value !== undefined) output[key] = value
  }
  return output
}

function normalizeConfigValue(value: unknown, schema: JsonSchema): unknown {
  if (value === undefined) return undefined
  if (value === null) return null
  const resolved = resolveSchema(schema)
  if (Array.isArray(value)) {
    return value.map((item) => normalizeConfigValue(item, resolved.items ?? {}))
  }
  if (!isRecord(value)) return structuredClone(value)
  if (resolved.properties) {
    const output: Record<string, unknown> = {}
    for (const [schemaKey, fieldSchema] of Object.entries(resolved.properties)) {
      const key = camelizeConfigKey(schemaKey)
      const sourceKey = findConfigKey(value, key)
      if (!sourceKey) continue
      const item = normalizeConfigValue(value[sourceKey], fieldSchema)
      if (item !== undefined) output[key] = item
    }
    return output
  }
  if (resolved.additionalProperties && typeof resolved.additionalProperties === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalizeConfigValue(item, resolved.additionalProperties as JsonSchema)]))
  }
  if (resolved.additionalProperties === false) return {}
  return structuredClone(value)
}

function applyLegacyConfigAliases(nodeType: string, config: Record<string, unknown>): Record<string, unknown> {
  const source = { ...config }
  for (const [alias, target] of Object.entries(legacyConfigAliases[nodeType] ?? {})) {
    if (!findConfigKey(source, target) && hasOwn(source, alias)) {
      const value = source[alias]
      source[target] = (target === "sourceIds" || target === "platforms") && typeof value === "string" ? [value] : value
    }
  }
  if (nodeType === "generate_content_pack") {
    if (!findConfigKey(source, "promptVersionIds")) {
      const legacyPromptId = firstConfigValue(source, ["promptTemplateVersionId", "promptVersionId"])
      if (typeof legacyPromptId === "string" && legacyPromptId) source.promptVersionIds = [legacyPromptId]
    }
    if (!findConfigKey(source, "promptChecksums")) {
      const checksum = firstConfigValue(source, ["promptChecksumSha256", "promptChecksum"])
      const configuredPromptIds = firstConfigValue(source, ["promptVersionIds"])
      const promptId = firstConfigValue(source, ["promptTemplateVersionId", "promptVersionId"])
        ?? (Array.isArray(configuredPromptIds) && configuredPromptIds.length === 1 ? configuredPromptIds[0] : undefined)
      if (typeof checksum === "string" && typeof promptId === "string" && promptId) source.promptChecksums = { [promptId]: checksum }
    }
  }
  return source
}

function workflowNodeConfig(node: WorkflowNode): Record<string, unknown> {
  const value = node as unknown as Record<string, unknown>
  if (hasOwn(value, "config") && isRecord(value.config)) return value.config
  return isRecord(value.configuration) ? value.configuration : {}
}

function firstConfigValue(source: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const actual = findConfigKey(source, key)
    if (actual) return source[actual]
  }
  return undefined
}

function findConfigKey(source: Record<string, unknown>, key: string) {
  const candidates = [key, camelizeConfigKey(key), snakeizeConfigKey(key)]
  return candidates.find((candidate) => hasOwn(source, candidate))
}

function camelizeConfigKey(key: string) {
  return key.replace(/_([a-z])/g, (_match, letter: string) => letter.toUpperCase())
}

function snakeizeConfigKey(key: string) {
  return key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
}

function hasOwn(value: Record<string, unknown>, key: string): key is string {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

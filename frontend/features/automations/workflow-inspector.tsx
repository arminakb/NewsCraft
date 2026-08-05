"use client"

import { ExternalLink } from "lucide-react"
import Link from "next/link"

import { ProviderBrandIcon } from "@/features/settings/provider-brand-icon"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"
import { getApiErrorMessage } from "@/lib/http"
import { cn } from "@/lib/utils"
import type { ArticleCollection } from "@/features/articles/types"
import type { SourceSummary } from "@/features/operations/ingestion-types"
import type { TelegramAutomationOptions } from "./telegram-types"

import type {
  AutomationNodeCatalog,
  AutomationNodeDefinition,
  AutomationResource,
  ValidationFinding,
  WorkflowEdge,
  WorkflowGraph,
} from "./automation-types"
import {
  catalogDefinition,
  connectWorkflowNodes,
  isUnsafeWorkflowField,
  type JsonSchema,
  resolveSchema,
  updateNodeConfig,
} from "./workflow-graph"
import { familyLabel, nodeIcon } from "./workflow-node-visual"

export function WorkflowInspector({
  graph,
  catalog,
  selectedNodeId,
  resources,
  collections,
  collectionsPending,
  collectionsError,
  onRetryCollections,
  sources,
  sourcesPending,
  sourcesError,
  onRetrySources,
  options,
  findings,
  onGraphChange,
  onRejected,
  showHeader = true,
  className,
}: {
  graph: WorkflowGraph
  catalog: AutomationNodeCatalog
  selectedNodeId: string | null
  resources: AutomationResource[]
  collections?: ArticleCollection[]
  collectionsPending?: boolean
  collectionsError?: unknown
  onRetryCollections?: () => void
  sources?: SourceSummary[]
  sourcesPending?: boolean
  sourcesError?: unknown
  onRetrySources?: () => void
  options?: TelegramAutomationOptions
  findings: ValidationFinding[]
  onGraphChange: (graph: WorkflowGraph) => void
  onRejected: (message: string) => void
  showHeader?: boolean
  className?: string
}) {
  const node = graph.nodes.find((item) => item.id === selectedNodeId)
  const definition = node ? catalogDefinition(catalog, node.type) : undefined
  if (!node || !definition) {
    return <div className="grid min-h-48 place-items-center p-5 text-center text-sm text-muted-foreground">Select a workflow step to inspect settings.</div>
  }
  const Icon = nodeIcon(definition.uiHints.icon)
  const schema = definition.configSchema as JsonSchema
  const properties = schema.properties ?? {}
  const nodeFindings = findings.filter((item) => item.nodeId === node.id)
  const update = (field: string, value: unknown, related?: Record<string, unknown>) => {
    onGraphChange(updateNodeConfig(graph, node.id, { ...node.config, [field]: value, ...related }))
  }

  return (
    <div className={cn("min-w-0 space-y-5 p-5", className)} aria-label={showHeader ? undefined : "Node settings"} aria-labelledby={showHeader ? "inspector-heading" : undefined}>
      {showHeader ? <div className="flex items-start gap-3 border-b border-border/60 pb-4">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg border bg-muted"><Icon className="size-5" aria-hidden="true" /></span>
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{familyLabel(definition.family)}</p>
          <h2 className="font-semibold" id="inspector-heading">{definition.displayName}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{definition.description}</p>
        </div>
      </div> : null}
      <div className="space-y-4">
        {Object.entries(properties).map(([field, fieldSchema]) => (
          <SchemaField
            definition={definition}
            field={field}
            findings={nodeFindings.filter((item) => item.fieldPath?.endsWith(field))}
            key={field}
            onChange={(value, related) => update(field, value, related)}
            options={options}
            resources={resources}
            collections={collections}
            collectionsPending={collectionsPending}
            collectionsError={collectionsError}
            onRetryCollections={onRetryCollections}
            sources={sources}
            sourcesPending={sourcesPending}
            sourcesError={sourcesError}
            onRetrySources={onRetrySources}
            schema={fieldSchema}
            value={node.config[field]}
          />
        ))}
        {!Object.keys(properties).length ? <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">This step has no editable settings.</p> : null}
      </div>
      <ConnectionFields graph={graph} catalog={catalog} nodeId={node.id} onGraphChange={onGraphChange} onRejected={onRejected} />
      {nodeFindings.length ? (
        <div className="space-y-2" aria-live="polite">
          <h3 className="text-sm font-semibold">Step validation</h3>
          {nodeFindings.map((finding, index) => (
            <div className="rounded-lg border border-destructive/25 bg-[var(--error-surface)] p-3 text-[13px]" key={`${finding.code}-${index}`}>
              <p className="font-medium text-destructive">{finding.message}</p>
              {finding.recoveryAction ? <p className="mt-1 text-muted-foreground">{finding.recoveryAction}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function SchemaField({
  definition,
  field,
  schema: rawSchema,
  value,
  resources,
  collections,
  collectionsPending,
  collectionsError,
  onRetryCollections,
  sources,
  sourcesPending,
  sourcesError,
  onRetrySources,
  options,
  findings,
  onChange,
}: {
  definition: AutomationNodeDefinition
  field: string
  schema: JsonSchema
  value: unknown
  resources: AutomationResource[]
  collections?: ArticleCollection[]
  collectionsPending?: boolean
  collectionsError?: unknown
  onRetryCollections?: () => void
  sources?: SourceSummary[]
  sourcesPending?: boolean
  sourcesError?: unknown
  onRetrySources?: () => void
  options?: TelegramAutomationOptions
  findings: ValidationFinding[]
  onChange: (value: unknown, related?: Record<string, unknown>) => void
}) {
  const schema = resolveSchema(rawSchema)
  const title = schema.title ?? humanize(field)
  const error = findings[0]
  const resourceKind = resourceKindForField(field)
  const selectedId = typeof value === "string" ? value : ""
  const selectedResource = resources.find((item) => item.id === selectedId && item.kind === resourceKind)
  const resourceOptions = resourceKind ? optionsForResource(resourceKind, options) : []
  const describedBy = error ? `${definition.type}-${field}-error` : undefined
  const inputId = `${definition.type}-${field}`

  if (isUnsafeWorkflowField(field)) return null
  if (field === "promptChecksumSha256" || field === "promptChecksums") {
    return (
      <FieldShell label={title} description="Pinned checksum is filled from selected saved prompt version." error={error}>
        <Input value={typeof value === "string" ? abbreviate(value) : "Not selected"} readOnly aria-readonly="true" />
      </FieldShell>
    )
  }
  if (field === "collectionId") {
    return (
      <CollectionField
        collections={collections ?? []}
        collectionsError={collectionsError}
        collectionsPending={collectionsPending === true}
        error={error}
        inputId={inputId}
        onChange={onChange}
        onRetryCollections={onRetryCollections}
        resource={selectedResource}
        schema={schema}
        selectedId={selectedId}
      />
    )
  }
  if (field === "sourceIds" && definition.type === "new_source_item") {
    return (
      <SourceMultiSelectField
        error={error}
        onChange={onChange}
        onRetrySources={onRetrySources}
        resources={resources}
        schema={schema}
        selected={Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []}
        sources={sources ?? []}
        sourcesError={sourcesError}
        sourcesPending={sourcesPending === true}
      />
    )
  }
  if (resourceKind && !Array.isArray(value) && field !== "sourceIds" && field !== "promptVersionIds") {
    return (
      <div className="grid gap-1.5 text-[13px] font-medium">
        <label htmlFor={inputId}>{title}</label>
        <Select id={inputId} value={selectedId} aria-describedby={describedBy} aria-invalid={Boolean(error)} onChange={(event) => {
          const id = event.target.value || null
          const related = field === "promptTemplateVersionId"
            ? { promptChecksumSha256: options?.promptTemplateVersions.find((item) => item.id === id)?.checksumSha256 ?? null }
            : undefined
          onChange(id, related)
        }}>
          <option value="">Not configured</option>
          {selectedId && !resourceOptions.some((item) => item.id === selectedId) ? <option value={selectedId}>Unavailable saved reference</option> : null}
          {resourceOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </Select>
        {selectedResource ? <ResourceReadiness resource={selectedResource} options={options} /> : <ManageResourceLink href={manageHref(resourceKind)}>Configure {resourceLabel(resourceKind)}</ManageResourceLink>}
        {schema.description ? <span className="text-xs font-normal text-muted-foreground">{schema.description}</span> : null}
        {error ? <span id={describedBy} className="text-xs font-normal text-destructive" role="alert">{error.message} {error.recoveryAction}</span> : null}
      </div>
    )
  }
  if (field === "sourceIds" || field === "promptVersionIds") {
    const kind = field === "sourceIds" ? "source" : "prompt_version"
    const selected = Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []
    const choices = optionsForResource(kind, options)
    return (
      <fieldset className="grid gap-1.5 text-[13px] font-medium">
        <legend>{title}</legend>
        <div className="space-y-1 rounded-lg border border-input p-2">
          {choices.length ? choices.map((item) => (
            <label className="flex min-h-11 items-center gap-2 rounded-md px-2 hover:bg-navigation-hover" key={item.id}>
              <Checkbox checked={selected.includes(item.id)} onChange={(event) => {
                const ids = event.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id)
                const related = field === "promptVersionIds"
                  ? { promptChecksums: Object.fromEntries(ids.map((id) => [id, options?.promptTemplateVersions.find((prompt) => prompt.id === id)?.checksumSha256]).filter((entry) => entry[1])) }
                  : undefined
                onChange(ids, related)
              }} />
              <span className="text-[13px]">{item.name}</span>
            </label>
          )) : <p className="p-2 text-xs text-muted-foreground">No saved resources available.</p>}
        </div>
        <ManageResourceLink href={manageHref(kind)}>Manage {resourceLabel(kind)}</ManageResourceLink>
        {schema.description ? <span className="text-xs font-normal text-muted-foreground">{schema.description}</span> : null}
        {error ? <span className="text-xs font-normal text-destructive" role="alert">{error.message} {error.recoveryAction}</span> : null}
      </fieldset>
    )
  }
  if (schema.enum?.length) {
    return <FieldShell label={title} description={schema.description} error={error}><Select value={String(value ?? schema.default ?? "")} aria-invalid={Boolean(error)} onChange={(event) => onChange(event.target.value)}>{schema.enum.map((item) => <option key={String(item)} value={String(item)}>{humanize(String(item))}</option>)}</Select></FieldShell>
  }
  if (schema.type === "boolean") {
    return <FieldShell label={title} description={schema.description} error={error}><span className="flex min-h-11 items-center gap-2 rounded-lg border border-input px-3"><Checkbox checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} /><span className="text-[13px]">Enabled</span></span></FieldShell>
  }
  if (schema.type === "integer" || schema.type === "number") {
    return <FieldShell label={title} description={schema.description} error={error}><Input type="number" min={schema.minimum} max={schema.maximum} value={typeof value === "number" ? value : schema.default as number ?? ""} aria-invalid={Boolean(error)} onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))} /></FieldShell>
  }
  if (schema.type === "array") {
    const list = Array.isArray(value) ? value.map(String) : []
    return <FieldShell label={title} description="Comma-separated values." error={error}><Textarea rows={3} value={list.join(", ")} onChange={(event) => onChange(event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} /></FieldShell>
  }
  if (schema.type === "object") {
    return <FieldShell label={title} description="Advanced structured policy stays as saved; NewsCraft never exposes raw JSON here." error={error}><Input readOnly value="Managed structured policy" aria-readonly="true" /></FieldShell>
  }
  return <FieldShell label={title} description={schema.description} error={error}><Input value={typeof value === "string" ? value : String(schema.default ?? "")} minLength={schema.minLength} maxLength={schema.maxLength} pattern={schema.pattern} aria-invalid={Boolean(error)} onChange={(event) => onChange(event.target.value || null)} /></FieldShell>
}

function CollectionField({
  collections,
  collectionsError,
  collectionsPending,
  error,
  inputId,
  onChange,
  onRetryCollections,
  resource,
  schema,
  selectedId,
}: {
  collections: ArticleCollection[]
  collectionsError?: unknown
  collectionsPending: boolean
  error?: ValidationFinding
  inputId: string
  onChange: (value: unknown, related?: Record<string, unknown>) => void
  onRetryCollections?: () => void
  resource?: AutomationResource
  schema: JsonSchema
  selectedId: string
}) {
  const describedBy = error ? `${inputId}-error` : undefined
  const selectedExists = collections.some((collection) => collection.id === selectedId)
  return (
    <div className="grid gap-1.5 text-[13px] font-medium">
      <label htmlFor={inputId}>Feed collection</label>
      {collectionsPending ? (
        <div className="flex min-h-11 items-center rounded-lg border border-input px-3 text-sm font-normal text-muted-foreground" role="status" aria-live="polite">Loading Feed collections…</div>
      ) : collectionsError ? (
        <div className="grid gap-2 rounded-lg border border-destructive/25 bg-[var(--error-surface)] p-3 font-normal text-destructive" role="alert">
          <span>{getApiErrorMessage(collectionsError)}</span>
          {onRetryCollections ? <Button className="min-h-11 w-fit" onClick={onRetryCollections} size="sm" type="button" variant="outline">Retry collections</Button> : null}
        </div>
      ) : collections.length === 0 ? (
        <div className="grid gap-2 rounded-lg border border-dashed border-border/80 p-3 font-normal text-muted-foreground" role="status">
          <span>No Feed collections yet. Create a Feed collection first.</span>
          <Link className="inline-flex min-h-11 w-fit items-center text-primary underline underline-offset-4" href="/feed">Create Feed collection<ExternalLink className="ml-1 size-3" aria-hidden="true" /></Link>
        </div>
      ) : (
        <Select
          id={inputId}
          value={selectedId}
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          onChange={(event) => onChange(event.target.value || null)}
        >
          <option value="">Select a Feed collection</option>
          {selectedId && !selectedExists ? <option value={selectedId}>Unavailable saved reference</option> : null}
          {collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
        </Select>
      )}
      {resource ? <ResourceReadiness resource={resource} /> : <ManageResourceLink href="/feed">Manage Feed collections</ManageResourceLink>}
      {selectedId && !selectedExists && !collectionsPending && !collectionsError ? <span className="text-xs font-normal text-destructive" role="alert">Selected Feed collection is unavailable. Choose another collection.</span> : null}
      {schema.description ? <span className="text-xs font-normal text-muted-foreground">{schema.description}</span> : null}
      {error ? <span id={describedBy} className="text-xs font-normal text-destructive" role="alert">{error.message} {error.recoveryAction}</span> : null}
    </div>
  )
}

function SourceMultiSelectField({
  error,
  onChange,
  onRetrySources,
  resources,
  schema,
  selected,
  sources,
  sourcesError,
  sourcesPending,
}: {
  error?: ValidationFinding
  onChange: (value: unknown, related?: Record<string, unknown>) => void
  onRetrySources?: () => void
  resources: AutomationResource[]
  schema: JsonSchema
  selected: string[]
  sources: SourceSummary[]
  sourcesError?: unknown
  sourcesPending: boolean
}) {
  const sourceResources = resources.filter((resource) => resource.kind === "source")
  const missingSelected = selected.filter((id) => !sources.some((source) => source.id === id))
  const selectedNotReady = sourceResources.filter((resource) => selected.includes(resource.id) && resource.state !== "ready")
  const toggle = (id: string, checked: boolean) => onChange(checked ? [...new Set([...selected, id])] : selected.filter((item) => item !== id))
  return (
    <fieldset className="grid gap-1.5 text-[13px] font-medium">
      <legend>Sources</legend>
      {sourcesPending ? (
        <div className="flex min-h-11 items-center rounded-lg border border-input px-3 text-sm font-normal text-muted-foreground" role="status" aria-live="polite">Loading sources…</div>
      ) : sourcesError ? (
        <div className="grid gap-2 rounded-lg border border-destructive/25 bg-[var(--error-surface)] p-3 font-normal text-destructive" role="alert">
          <span>{getApiErrorMessage(sourcesError)}</span>
          {onRetrySources ? <Button className="min-h-11 w-fit" onClick={onRetrySources} size="sm" type="button" variant="outline">Retry sources</Button> : null}
        </div>
      ) : sources.length === 0 ? (
        <div className="grid gap-2 rounded-lg border border-dashed border-border/80 p-3 font-normal text-muted-foreground" role="status">
          <span>No sources available. Add a source under Sources.</span>
          <Link className="inline-flex min-h-11 w-fit items-center text-primary underline underline-offset-4" href="/sources">Add a source under Sources<ExternalLink className="ml-1 size-3" aria-hidden="true" /></Link>
        </div>
      ) : (
        <div className="space-y-1 rounded-lg border border-input p-2">
          {missingSelected.map((id) => (
            <label className="flex min-h-11 items-center gap-2 rounded-md border border-destructive/25 bg-[var(--error-surface)] px-2" key={id}>
              <Checkbox checked onChange={(event) => toggle(id, event.target.checked)} />
              <span className="min-w-0 flex-1">Unavailable saved source</span>
              <StatusBadge tone="error">Deleted or unavailable</StatusBadge>
            </label>
          ))}
          {sources.map((source) => (
            <label className="flex min-h-11 items-center gap-2 rounded-md px-2 hover:bg-navigation-hover" key={source.id}>
              <Checkbox checked={selected.includes(source.id)} onChange={(event) => toggle(source.id, event.target.checked)} />
              <span className="min-w-0 flex-1 truncate">{source.name}</span>
              <span className="text-[11px] text-muted-foreground">{source.platform.replaceAll("_", " ")}</span>
              <StatusBadge tone={sourceStatusTone(source.status)}>{source.status}</StatusBadge>
            </label>
          ))}
        </div>
      )}
      {sourceResources.length && selected.length ? (
        <div className="grid gap-1">
          {selected.map((id) => {
            const resource = sourceResources.find((item) => item.id === id)
            return resource ? <ResourceReadiness key={id} resource={resource} /> : null
          })}
        </div>
      ) : <ManageResourceLink href="/sources">Manage sources</ManageResourceLink>}
      {selectedNotReady.length || missingSelected.length ? <span className="text-xs font-normal text-destructive" role="alert">One or more selected sources are disabled, deleted, or unavailable. Remove the invalid source or restore it under Sources.</span> : null}
      {schema.description ? <span className="text-xs font-normal text-muted-foreground">{schema.description}</span> : null}
      {error ? <span className="text-xs font-normal text-destructive" role="alert">{error.message} {error.recoveryAction}</span> : null}
    </fieldset>
  )
}

function FieldShell({ label, description, error, children }: { label: string; description?: string; error?: ValidationFinding; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5 text-[13px] font-medium">
      <span>{label}</span>
      {children}
      {description ? <span className="text-xs font-normal text-muted-foreground">{description}</span> : null}
      {error ? <span className="text-xs font-normal text-destructive" role="alert">{error.message} {error.recoveryAction}</span> : null}
    </label>
  )
}

function ConnectionFields({ graph, catalog, nodeId, onGraphChange, onRejected }: { graph: WorkflowGraph; catalog: AutomationNodeCatalog; nodeId: string; onGraphChange: (graph: WorkflowGraph) => void; onRejected: (message: string) => void }) {
  const edges = graph.edges.filter((edge) => edge.sourceNodeId === nodeId || edge.targetNodeId === nodeId)
  if (!edges.length) return null
  return (
    <fieldset className="space-y-3 border-t border-border/60 pt-4">
      <legend className="text-sm font-semibold">Connections</legend>
      <p className="text-xs text-muted-foreground">Keyboard alternative to drawing edges. Choose compatible output and input ports.</p>
      {edges.map((edge, index) => {
        const sourceNode = graph.nodes.find((node) => node.id === edge.sourceNodeId)
        const targetNode = graph.nodes.find((node) => node.id === edge.targetNodeId)
        const source = sourceNode ? catalogDefinition(catalog, sourceNode.type) : undefined
        const target = targetNode ? catalogDefinition(catalog, targetNode.type) : undefined
        const key = `${edge.sourceNodeId}-${edge.targetNodeId}-${index}`
        if (!sourceNode || !targetNode || !source || !target) {
          return <div className="rounded-lg border border-destructive/25 bg-[var(--error-surface)] p-3 text-xs text-destructive" key={key} role="alert">Saved connection references an unavailable step. Keep the draft and replace that step before activation.</div>
        }
        const replace = (patch: Partial<WorkflowEdge>) => {
          const without = { ...graph, edges: graph.edges.filter((item) => item !== edge) }
          const result = connectWorkflowNodes(without, catalog, { ...edge, ...patch })
          if (!result.graph) onRejected(result.error)
          else onGraphChange(result.graph)
        }
        return (
          <div className="grid gap-2 rounded-lg border border-border/60 p-3" key={key}>
            <p className="text-xs text-muted-foreground">{source.displayName} to {target.displayName}</p>
            <label className="grid gap-1 text-xs"><span>Output port</span><Select value={edge.sourcePort} onChange={(event) => replace({ sourcePort: event.target.value })}>{source.outputs.map((port) => <option value={port.name} key={port.name}>{humanize(port.name)}</option>)}</Select></label>
            <label className="grid gap-1 text-xs"><span>Input port</span><Select value={edge.targetPort} onChange={(event) => replace({ targetPort: event.target.value })}>{target.inputs.map((port) => <option value={port.name} key={port.name}>{humanize(port.name)}</option>)}</Select></label>
          </div>
        )
      })}
    </fieldset>
  )
}

function ResourceReadiness({ resource, options }: { resource: AutomationResource; options?: TelegramAutomationOptions }) {
  const provider = resource.kind === "provider" ? options?.aiProviderProfiles.find((item) => item.id === resource.id) : undefined
  return (
    <div className="flex min-h-11 flex-wrap items-center gap-2 rounded-lg border border-border/60 px-2.5">
      {provider ? <ProviderBrandIcon providerType={provider.providerType} name={provider.name} className="size-4" /> : null}
      <StatusBadge tone={readinessTone(resource.state)}>{humanize(resource.state)}</StatusBadge>
      <Link className="ml-auto inline-flex min-h-11 items-center gap-1 text-xs text-primary underline underline-offset-4" href={resource.manageHref}>Manage<ExternalLink className="size-3" aria-hidden="true" /></Link>
    </div>
  )
}

function ManageResourceLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link className="inline-flex min-h-11 items-center gap-1 text-xs font-normal text-primary underline underline-offset-4" href={href}>{children}<ExternalLink className="size-3" aria-hidden="true" /></Link>
}

function resourceKindForField(field: string): AutomationResource["kind"] | null {
  if (field === "collectionId") return "collection"
  if (field === "sourceId" || field === "sourceIds") return "source"
  if (field === "providerProfileId") return "provider"
  if (field === "editorialProfileId") return "editorial_profile"
  if (field === "promptTemplateVersionId" || field === "promptVersionIds") return "prompt_version"
  if (field === "destinationId") return "destination"
  return null
}

function optionsForResource(kind: AutomationResource["kind"], options?: TelegramAutomationOptions): Array<{ id: string; name: string }> {
  if (!options) return []
  if (kind === "source") return options.sources
  if (kind === "provider") return options.aiProviderProfiles
  if (kind === "editorial_profile") return options.brandProfiles
  if (kind === "destination") return options.destinations
  if (kind === "collection") return []
  return options.promptTemplateVersions.map((item) => ({ id: item.id, name: `Prompt version ${item.version}${item.isActive ? " · active" : ""}` }))
}

function manageHref(kind: AutomationResource["kind"]) {
  if (kind === "collection") return "/feed"
  if (kind === "source") return "/sources"
  if (kind === "provider") return "/settings?section=llm-providers"
  if (kind === "prompt_version") return "/settings?section=prompts"
  if (kind === "destination") return "/settings?section=telegram"
  return "/settings"
}

function resourceLabel(kind: AutomationResource["kind"]) {
  if (kind === "collection") return "Feed collections"
  return kind.replaceAll("_", " ")
}

function readinessTone(state: AutomationResource["state"]): StatusTone {
  if (state === "ready") return "success"
  if (state === "disabled" || state === "unavailable") return "error"
  return "warning"
}

function sourceStatusTone(status: SourceSummary["status"]): StatusTone {
  if (status === "healthy") return "success"
  if (status === "disabled" || status === "broken") return "error"
  if (status === "degraded") return "warning"
  return "neutral"
}

function humanize(value: string) {
  return value.replace(/([a-z])([A-Z])/g, "$1 $2").split("_").join(" ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function abbreviate(value: string) {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-8)}` : value
}

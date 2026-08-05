"use client"

import { AlertTriangle, X } from "lucide-react"
import { useMemo, useRef, useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

import type { ArticleCollection } from "@/features/articles/types"
import type { SourceSummary } from "@/features/operations/ingestion-types"
import type { TelegramAutomationOptions } from "./telegram-types"
import type { AutomationNodeCatalog, AutomationResource, ValidationFinding, WorkflowGraph } from "./automation-types"
import { catalogDefinition, deleteWorkflowNode, validateWorkflowClient } from "./workflow-graph"
import { WorkflowInspector } from "./workflow-inspector"
import { familyLabel, familyStyles, nodeIcon } from "./workflow-node-visual"

export function NodeCustomizeDialog({
  graph,
  catalog,
  nodeId,
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
  returnFocus,
  onSave,
  onClose,
  onRejected,
}: {
  graph: WorkflowGraph
  catalog: AutomationNodeCatalog
  nodeId: string
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
  returnFocus: HTMLElement | null
  onSave: (graph: WorkflowGraph) => void
  onClose: () => void
  onRejected: (message: string) => void
}) {
  const [draftGraph, setDraftGraph] = useState(() => structuredClone(graph))
  const [discardPrompt, setDiscardPrompt] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const node = draftGraph.nodes.find((item) => item.id === nodeId)
  const definition = node ? catalogDefinition(catalog, node.type) : undefined
  const dirty = useMemo(() => JSON.stringify(draftGraph) !== JSON.stringify(graph), [draftGraph, graph])
  const draftValidation = useMemo(() => validateWorkflowClient(draftGraph, catalog), [catalog, draftGraph])
  const displayedFindings = dirty ? draftValidation.findings : findings
  const blockingConfigFindings = draftValidation.findings.filter((finding) => (
    finding.severity === "error"
    && finding.nodeId === nodeId
    && (finding.fieldPath?.startsWith("config.") || finding.code === "node_config_invalid" || finding.code === "automation_resource_unavailable")
  ))

  const requestClose = () => {
    if (dirty) {
      setDiscardPrompt(true)
      return
    }
    close()
  }
  const close = () => {
    onClose()
    window.setTimeout(() => {
      const fallback = document.querySelector<HTMLElement>(`.react-flow__node[data-id="${nodeId}"]`)
      ;(returnFocus?.isConnected ? returnFocus : fallback)?.focus()
    }, 0)
  }
  const save = () => {
    const form = formRef.current
    if (!form?.checkValidity()) {
      form?.reportValidity()
      return
    }
    if (blockingConfigFindings.length) return
    onSave(draftGraph)
    close()
  }

  if (!node) return null
  if (!definition) {
    const nodeFindings = displayedFindings.filter((finding) => finding.nodeId === node.id)
    return (
      <Dialog open onOpenChange={(open) => { if (!open) close() }}>
        <DialogContent className="max-w-lg" finalFocus={() => returnFocus} initialFocus={closeButtonRef}>
          <DialogHeader>
            <DialogTitle>Unsupported saved step</DialogTitle>
            <DialogDescription>Node type <code>{node.type}</code> is no longer available in the server catalog. It was not replaced automatically.</DialogDescription>
          </DialogHeader>
          {nodeFindings.length ? <div className="mt-4 space-y-2" aria-live="polite">{nodeFindings.map((finding, index) => <Alert key={`${finding.code}-${index}`} tone="error" role="alert"><AlertDescription>{finding.message}{finding.recoveryAction ? ` ${finding.recoveryAction}` : ""}</AlertDescription></Alert>)}</div> : null}
          <DialogFooter className="mt-5">
            <Button onClick={close} ref={closeButtonRef} type="button" variant="ghost">Keep step</Button>
            <Button onClick={() => {
              const result = deleteWorkflowNode(draftGraph, catalog, node.id)
              if (!result.graph) onRejected(result.error)
              else { onSave(result.graph); close() }
            }} type="button" variant="destructive">Remove unsupported step</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )
  }
  const Icon = nodeIcon(definition.uiHints.icon)

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) requestClose()
      }}
    >
      <DialogContent
        className="flex h-[min(760px,calc(100dvh-2rem))] max-h-[calc(100dvh-2rem)] max-w-2xl flex-col overflow-hidden p-0"
        finalFocus={() => returnFocus}
        initialFocus={closeButtonRef}
      >
        <DialogHeader className="shrink-0 border-b border-border/60 px-5 py-4 pr-16">
          <div className="flex items-start gap-3">
            <span className={cn("grid size-11 shrink-0 place-items-center rounded-lg border", familyStyles[definition.family] ?? "bg-muted")}><Icon className="size-5" aria-hidden="true" /></span>
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{familyLabel(definition.family)} step</p>
              <DialogTitle>Customize {definition.displayName}</DialogTitle>
              <DialogDescription>{definition.description} Changes stay local until Save changes is selected.</DialogDescription>
            </div>
          </div>
        </DialogHeader>
        <Button
          aria-label="Close node customization"
          className="absolute right-3 top-3 z-10"
          onClick={requestClose}
          ref={closeButtonRef}
          size="icon"
          type="button"
          variant="ghost"
        >
          <X aria-hidden="true" />
        </Button>
        <form
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
          onSubmit={(event) => {
            event.preventDefault()
            save()
          }}
          ref={formRef}
        >
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            <WorkflowInspector
              catalog={catalog}
              findings={displayedFindings}
              graph={draftGraph}
              onGraphChange={(nextGraph) => {
                setDiscardPrompt(false)
                setDraftGraph(nextGraph)
              }}
              onRejected={onRejected}
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
              selectedNodeId={nodeId}
              showHeader={false}
            />
          </div>
          {blockingConfigFindings.length ? (
            <div className="shrink-0 px-5 pt-3" role="alert">
              <Alert tone="warning">
                <AlertDescription>Resolve configuration errors before saving this step.</AlertDescription>
              </Alert>
            </div>
          ) : null}
          {discardPrompt ? (
            <Alert className="mx-5 mt-3 shrink-0" tone="warning" role="alert">
              <AlertTriangle aria-hidden="true" />
              <AlertDescription>Discard unsaved node changes?</AlertDescription>
            </Alert>
          ) : null}
          <DialogFooter className="shrink-0 bg-popover px-5 py-4">
            {discardPrompt ? (
              <>
                <Button onClick={() => setDiscardPrompt(false)} type="button" variant="ghost">Keep editing</Button>
                <Button onClick={close} type="button" variant="destructive">Discard changes</Button>
              </>
            ) : (
              <>
                <Button onClick={requestClose} type="button" variant="ghost">Cancel</Button>
                <Button disabled={!dirty || blockingConfigFindings.length > 0} type="submit">Save changes</Button>
              </>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

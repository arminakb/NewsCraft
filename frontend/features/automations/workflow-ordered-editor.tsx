"use client"

import { ArrowDown, ArrowUp, Copy, Plus, Settings2, Trash2, TriangleAlert, X } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { StatusBadge } from "@/components/ui/status-badge"
import { cn } from "@/lib/utils"

import type { AutomationNodeCatalog, AutomationResource, GraphValidation, WorkflowGraph } from "./automation-types"
import {
  catalogDefinition,
  deleteWorkflowNode,
  duplicateWorkflowNode,
  type GraphEditResult,
  insertWorkflowNode,
  moveWorkflowNode,
  orderedWorkflowNodes,
  workflowNodeActionState,
} from "./workflow-graph"
import { configuredNodeLabel, familyLabel, familyStyles, nodeIcon } from "./workflow-node-visual"
import { NodePicker } from "./workflow-node-library"

export function WorkflowOrderedEditor({
  graph,
  catalog,
  validation,
  selectedNodeId,
  resources = [],
  onGraphChange,
  onSelectedNodeChange,
  onInspect,
  onRejected,
  className,
}: {
  graph: WorkflowGraph
  catalog: AutomationNodeCatalog
  validation: GraphValidation
  selectedNodeId: string | null
  resources?: AutomationResource[]
  onGraphChange: (graph: WorkflowGraph) => void
  onSelectedNodeChange: (nodeId: string | null) => void
  onInspect: (nodeId: string, returnFocus?: HTMLElement | null) => void
  onRejected: (message: string) => void
  className?: string
}) {
  const [addOpen, setAddOpen] = useState(false)
  const ordered = orderedWorkflowNodes(graph)
  const selectedIndex = ordered.findIndex((node) => node.id === selectedNodeId)

  const apply = (result: GraphEditResult, options: { selectNew?: boolean; clearNodeId?: string } = {}) => {
    if (!result.graph) { onRejected(result.error); return }
    onGraphChange(result.graph)
    if (options.selectNew && result.nodeId) onSelectedNodeChange(result.nodeId)
    else if (options.clearNodeId && selectedNodeId === options.clearNodeId) onSelectedNodeChange(null)
  }

  return (
    <div className={cn("min-w-0 space-y-3", className)} aria-label="Ordered workflow editor" role="region">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="font-semibold">Ordered editor</h2><p className="text-xs text-muted-foreground">Complete keyboard and touch alternative to canvas editing.</p></div>
        <Button variant="outline" onClick={() => setAddOpen(true)}><Plus aria-hidden="true" />Add next step</Button>
      </div>
      <ol className="space-y-2">
        {ordered.map((node, index) => {
          const definition = catalogDefinition(catalog, node.type)
          if (!definition) {
            const nodeFindings = validation.findings.filter((item) => item.nodeId === node.id)
            return (
              <li key={node.id}>
                {index > 0 ? <div className="mx-6 h-3 border-l border-dashed border-border" aria-hidden="true" /> : null}
                <article className={cn("rounded-xl border border-destructive/35 bg-[var(--error-surface)] p-3 shadow-xs", selectedNodeId === node.id && "ring-2 ring-destructive/25")} aria-label={`Step ${index + 1}: Unsupported saved step`} role="alert">
                  <div className="flex items-start gap-3">
                    <span className="grid size-11 shrink-0 place-items-center rounded-lg border border-destructive/35 text-destructive"><TriangleAlert className="size-5" aria-hidden="true" /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2"><span className="text-xs tabular-nums text-muted-foreground">Step {index + 1}</span><StatusBadge tone="error">Unsupported</StatusBadge></div>
                      <h3 className="mt-1 font-medium">Unsupported saved step</h3>
                      <p className="mt-0.5 text-xs text-muted-foreground">Node type <code>{node.type}</code> is no longer available in the server catalog. It was not replaced automatically.</p>
                      {nodeFindings.map((finding, findingIndex) => <p className="mt-2 text-xs text-destructive" key={`${finding.code}-${findingIndex}`}>{finding.message}{finding.recoveryAction ? ` ${finding.recoveryAction}` : ""}</p>)}
                    </div>
                  </div>
                  <div className="mt-3 flex justify-end border-t border-destructive/20 pt-2">
                    <Button variant="outline" onClick={() => apply(deleteWorkflowNode(graph, catalog, node.id), { clearNodeId: node.id })}>Remove unsupported step</Button>
                  </div>
                </article>
              </li>
            )
          }
          const Icon = nodeIcon(definition.uiHints.icon)
          const label = configuredNodeLabel(node, definition.displayName, resources)
          const hasError = validation.findings.some((item) => item.nodeId === node.id && item.severity === "error")
          const hasWarning = validation.findings.some((item) => item.nodeId === node.id && item.severity === "warning")
          const selected = selectedNodeId === node.id
          const actions = workflowNodeActionState(graph, catalog, node.id)
          const duplicateReasonId = `${node.id}-duplicate-disabled-reason`
          const deleteReasonId = `${node.id}-delete-disabled-reason`
          return (
            <li key={node.id}>
              {index > 0 ? <div className="mx-6 h-3 border-l border-dashed border-border" aria-hidden="true" /> : null}
              <article className={cn("rounded-xl border bg-card p-3 shadow-xs focus-within:ring-2 focus-within:ring-ring/35", selected && "border-primary/60 ring-2 ring-primary/15")} aria-label={`Step ${index + 1}: ${label}`}>
                <div className="flex items-start gap-3">
                  <button className={cn("grid size-11 shrink-0 place-items-center rounded-lg border focus-visible:ring-2 focus-visible:ring-ring/50", familyStyles[definition.family] ?? "bg-muted")} aria-label={`Select ${label}`} onClick={() => onSelectedNodeChange(node.id)} type="button"><Icon className="size-5" aria-hidden="true" /></button>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2"><span className="text-xs tabular-nums text-muted-foreground">Step {index + 1}</span><StatusBadge tone={hasError ? "error" : hasWarning ? "warning" : "neutral"}>{familyLabel(definition.family)}</StatusBadge></div>
                    <h3 className="mt-1 font-medium">{label}</h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">{definition.description}</p>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap justify-end gap-1 border-t border-border/50 pt-2">
                  <Button size="icon" variant="ghost" aria-label={`Move ${definition.displayName} up`} disabled={index <= 1} onClick={() => apply(moveWorkflowNode(graph, catalog, node.id, -1))}><ArrowUp aria-hidden="true" /></Button>
                  <Button size="icon" variant="ghost" aria-label={`Move ${definition.displayName} down`} disabled={index === 0 || index >= ordered.length - 2} onClick={() => apply(moveWorkflowNode(graph, catalog, node.id, 1))}><ArrowDown aria-hidden="true" /></Button>
                  {actions.duplicateReason ? <span className="sr-only" id={duplicateReasonId}>Duplicate unavailable: {actions.duplicateReason}</span> : null}
                  <Button size="icon" variant="ghost" aria-describedby={actions.duplicateReason ? duplicateReasonId : undefined} aria-label={`Duplicate ${definition.displayName}`} disabled={!actions.canDuplicate} onClick={() => apply(duplicateWorkflowNode(graph, catalog, node.id), { selectNew: true })} title={actions.duplicateReason ? `Duplicate unavailable: ${actions.duplicateReason}` : `Duplicate ${definition.displayName}`}><Copy aria-hidden="true" /></Button>
                  <Button size="icon" variant="ghost" aria-label={`Edit ${definition.displayName} settings`} onClick={(event) => { onSelectedNodeChange(node.id); onInspect(node.id, event.currentTarget) }}><Settings2 aria-hidden="true" /></Button>
                  {actions.deleteReason ? <span className="sr-only" id={deleteReasonId}>Delete unavailable: {actions.deleteReason}</span> : null}
                  <Button size="icon" variant="ghost" aria-describedby={actions.deleteReason ? deleteReasonId : undefined} aria-label={`Delete ${definition.displayName}`} disabled={!actions.canDelete} onClick={() => apply(deleteWorkflowNode(graph, catalog, node.id), { clearNodeId: node.id })} title={actions.deleteReason ? `Delete unavailable: ${actions.deleteReason}` : `Delete ${definition.displayName}`}><Trash2 aria-hidden="true" /></Button>
                </div>
              </article>
            </li>
          )
        })}
      </ol>
      <Sheet open={addOpen} onOpenChange={setAddOpen}>
        <SheetContent side="bottom">
          <div className="max-h-[85dvh] overflow-y-auto p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            <SheetHeader className="pr-12"><SheetTitle>Add next step</SheetTitle><SheetDescription>Steps come only from server node catalog. Choose insertion point first if needed.</SheetDescription></SheetHeader>
            <SheetClose aria-label="Close add step" className="absolute right-3 top-3 grid size-11 place-items-center rounded-lg hover:bg-navigation-hover"><X aria-hidden="true" /></SheetClose>
            <NodePicker
              allowEntry={!graph.nodes.length}
              catalog={catalog}
              afterNodeId={selectedIndex >= 0 ? ordered[selectedIndex].id : undefined}
              onAdd={(type) => {
                const result = insertWorkflowNode(graph, catalog, type, selectedIndex >= 0 ? ordered[selectedIndex].id : undefined)
                if (!result.graph) onRejected(result.error)
                else { onGraphChange(result.graph); onSelectedNodeChange(result.nodeId ?? null); setAddOpen(false) }
              }}
            />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}

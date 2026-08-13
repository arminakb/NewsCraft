"use client"

import { X } from "lucide-react"
import { useMemo, useRef } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { StatusBadge } from "@/components/ui/status-badge"

import type { AutomationNodeCatalog, ValidationFinding, WorkflowGraph } from "./automation-types"
import { catalogDefinition } from "./workflow-graph"

type WorkflowValidationDialogProps = {
  open: boolean
  findings: ValidationFinding[]
  graph: WorkflowGraph
  catalog: AutomationNodeCatalog
  returnFocus?: HTMLElement | null
  onOpenChange: (open: boolean) => void
  onSelectNode?: (nodeId: string) => void
}

type DisplayedFinding = {
  key: string
  finding: ValidationFinding
  context: string | null
}

type FindingGroup = {
  key: string
  label: string
  nodeId: string | null
  findings: DisplayedFinding[]
}

export function WorkflowValidationDialog({
  open,
  findings,
  graph,
  catalog,
  returnFocus,
  onOpenChange,
  onSelectNode,
}: WorkflowValidationDialogProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const groups = useMemo(() => groupFindings(findings, graph, catalog), [catalog, findings, graph])
  const issueLabel = findings.length === 1 ? "issue found" : "issues found"
  const issueSummary = `${findings.length} ${issueLabel}. Review each item before saving or activating this workflow.`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[calc(100dvh-2rem)] max-w-2xl flex-col overflow-hidden p-0"
        finalFocus={() => returnFocus}
        initialFocus={closeButtonRef}
      >
        <DialogHeader className="shrink-0 border-b border-border/60 px-5 py-4 pr-16">
          <DialogTitle>Needs attention</DialogTitle>
          <DialogDescription>{issueSummary}</DialogDescription>
        </DialogHeader>
        <Button
          aria-label="Close needs attention"
          className="absolute right-3 top-3"
          onClick={() => onOpenChange(false)}
          ref={closeButtonRef}
          size="icon"
          type="button"
          variant="ghost"
        >
          <X aria-hidden="true" />
        </Button>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-5">
          <div className="space-y-5">
            {groups.map((group, groupIndex) => {
              const headingId = `workflow-validation-group-${groupIndex}`
              return (
                <section aria-labelledby={headingId} key={group.key}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-semibold" data-validation-node={group.nodeId ?? undefined} id={headingId}>{group.label}</h3>
                    {group.nodeId && onSelectNode ? (
                      <Button
                        aria-label={`Select ${group.label}`}
                        className="min-h-11 min-[900px]:min-h-8"
                        onClick={() => {
                          onSelectNode(group.nodeId!)
                          onOpenChange(false)
                        }}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        Select node
                      </Button>
                    ) : null}
                  </div>
                  <ul className="mt-2 space-y-2">
                    {group.findings.map(({ context, finding, key }) => (
                      <li className="rounded-lg border border-border/70 bg-card p-3 shadow-xs" key={key}>
                        <StatusBadge tone={finding.severity === "error" ? "error" : "warning"}>
                          {finding.severity === "error" ? "Error" : "Warning"}
                        </StatusBadge>
                        <p className="mt-2 text-sm leading-5 text-foreground">{finding.message}</p>
                        {context ? <p className="mt-2 text-xs leading-5 text-muted-foreground"><span className="font-medium text-foreground">Context:</span> {context}</p> : null}
                        {finding.recoveryAction ? <p className="mt-1 text-xs leading-5 text-muted-foreground"><span className="font-medium text-foreground">Next:</span> {finding.recoveryAction}</p> : null}
                      </li>
                    ))}
                  </ul>
                </section>
              )
            })}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function groupFindings(findings: ValidationFinding[], graph: WorkflowGraph, catalog: AutomationNodeCatalog): FindingGroup[] {
  const groups = new Map<string, FindingGroup>()

  findings.forEach((finding, index) => {
    const node = finding.nodeId ? graph.nodes.find((item) => item.id === finding.nodeId) : undefined
    const edge = finding.edgeIndex !== null && finding.edgeIndex !== undefined ? graph.edges[finding.edgeIndex] : undefined
    const groupKey = node ? `node:${node.id}` : edge ? `edge:${finding.edgeIndex}` : "workflow"
    const group = groups.get(groupKey) ?? {
      key: groupKey,
      label: node ? nodeLabel(node.type, catalog) : edge ? "Workflow connection" : "Workflow",
      nodeId: node?.id ?? null,
      findings: [],
    }
    group.findings.push({
      key: `${finding.code}-${finding.nodeId ?? "workflow"}-${finding.edgeIndex ?? "none"}-${index}`,
      finding,
      context: findingContext(finding, edge, graph, catalog),
    })
    groups.set(groupKey, group)
  })

  return [...groups.values()]
}

function findingContext(finding: ValidationFinding, edge: WorkflowGraph["edges"][number] | undefined, graph: WorkflowGraph, catalog: AutomationNodeCatalog) {
  const context: string[] = []
  if (finding.fieldPath) context.push(`Field: ${humanizePath(finding.fieldPath)}`)
  if (edge) {
    const source = graph.nodes.find((node) => node.id === edge.sourceNodeId)
    const target = graph.nodes.find((node) => node.id === edge.targetNodeId)
    const sourceLabel = source ? nodeLabel(source.type, catalog) : "Unknown step"
    const targetLabel = target ? nodeLabel(target.type, catalog) : "Unknown step"
    context.push(`Connection: ${sourceLabel} (${humanizeIdentifier(edge.sourcePort)}) to ${targetLabel} (${humanizeIdentifier(edge.targetPort)})`)
  }
  return context.length ? context.join(" · ") : null
}

function nodeLabel(type: string, catalog: AutomationNodeCatalog) {
  return catalogDefinition(catalog, type)?.displayName ?? type
}

function humanizePath(path: string) {
  return path.split(".").map(humanizeIdentifier).join(" · ")
}

function humanizeIdentifier(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

"use client"

import { Search } from "lucide-react"
import { useMemo, useState } from "react"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

import type { AutomationNodeCatalog } from "./automation-types"
import { familyLabel, familyStyles, nodeIcon } from "./workflow-node-visual"

export const WORKFLOW_NODE_DRAG_TYPE = "application/x-newscraft-workflow-node"

export function WorkflowNodeLibrary({
  catalog,
  afterNodeId,
  allowEntry = false,
  issueCount,
  onAdd,
}: {
  catalog: AutomationNodeCatalog
  afterNodeId?: string
  allowEntry?: boolean
  issueCount: number
  onAdd: (type: string) => void
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border/60 px-3 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="font-semibold">Node library</h2>
          <span className="text-xs tabular-nums text-muted-foreground">{issueCount} {issueCount === 1 ? "issue" : "issues"}</span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">Node options will appear here when available.</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-4">
        <NodePicker
          allowEntry={allowEntry}
          catalog={catalog}
          afterNodeId={afterNodeId}
          onAdd={onAdd}
          emptyState={catalog.nodes.length === 0}
        />
      </div>
    </div>
  )
}

export function NodePicker({ allowEntry = false, catalog, afterNodeId, onAdd, emptyState = false }: {
  allowEntry?: boolean
  catalog: AutomationNodeCatalog
  afterNodeId?: string
  onAdd: (type: string) => void
  emptyState?: boolean
}) {
  const [search, setSearch] = useState("")
  const groups = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    const nodes = catalog.nodes.filter((item) => (
      (allowEntry || !item.entry)
      && item.runtimeStatus !== "unavailable"
      && (!query || `${item.displayName} ${item.description} ${item.family}`.toLocaleLowerCase().includes(query))
    ))
    return nodes.reduce((grouped, item) => {
      const values = grouped.get(item.family) ?? []
      values.push(item)
      grouped.set(item.family, values)
      return grouped
    }, new Map<string, typeof nodes>())
  }, [allowEntry, catalog.nodes, search])

  if (emptyState) {
    return (
      <div className="py-3">
        <div aria-live="polite" className="rounded-lg border border-dashed border-border/70 px-4 py-8 text-center" role="status">
          <p className="text-sm font-medium">No nodes available</p>
          <p className="mt-1 text-sm text-muted-foreground">Node definitions will appear here when they are ready to add.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4 py-3">
      <label className="grid gap-1.5 text-[13px] font-medium">
        <span>Search nodes</span>
        <span className="relative block">
          <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" onChange={(event) => setSearch(event.target.value)} placeholder="Search steps" type="search" value={search} />
        </span>
      </label>
      {[...groups.entries()].map(([family, definitions]) => (
        <section aria-labelledby={`node-family-${family}`} key={family}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground" id={`node-family-${family}`}>{familyLabel(family)}</h3>
          <div className="grid grid-cols-2 gap-2" data-node-library-grid>
            {definitions.map((definition) => {
              const Icon = nodeIcon(definition.uiHints.icon)
              return (
                <button
                  aria-description={definition.description}
                  className="group flex min-h-24 cursor-grab flex-col items-center justify-center gap-2 rounded-lg border border-border/60 bg-card px-2 py-3 text-center shadow-xs transition-[border-color,background-color,box-shadow] duration-150 ease-out hover:border-primary/45 hover:bg-navigation-hover hover:shadow-sm active:cursor-grabbing focus-visible:ring-2 focus-visible:ring-ring/50 motion-reduce:transition-none"
                  draggable
                  key={definition.type}
                  onClick={() => onAdd(definition.type)}
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = "copy"
                    event.dataTransfer.setData(WORKFLOW_NODE_DRAG_TYPE, definition.type)
                    event.dataTransfer.setData("text/plain", definition.type)
                  }}
                  title={definition.description}
                  type="button"
                >
                  <span className={cn("grid size-10 shrink-0 place-items-center rounded-lg border transition-transform duration-150 ease-out group-hover:-translate-y-0.5 motion-reduce:transition-none", familyStyles[definition.family] ?? "bg-muted")}><Icon className="size-5" aria-hidden="true" /></span>
                  <span className="line-clamp-2 min-h-8 text-[13px] font-medium leading-4">{definition.displayName}</span>
                </button>
              )
            })}
          </div>
        </section>
      ))}
      {!groups.size ? <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">No matching steps.</p> : null}
      {afterNodeId ? <p className="text-xs text-muted-foreground">New step follows selected step when ports are compatible.</p> : null}
    </div>
  )
}

"use client"

import "@xyflow/react/dist/style.css"

import {
  Background,
  BackgroundVariant,
  BaseEdge,
  ConnectionLineType,
  Controls,
  getSmoothStepPath,
  getStraightPath,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type EdgeProps,
  type Node,
  type NodeChange,
  type NodeProps,
  type NodeTypes,
  type EdgeTypes,
  type ReactFlowInstance,
} from "@xyflow/react"
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react"

import { useTheme } from "@/components/providers/theme-provider"
import { StatusBadge } from "@/components/ui/status-badge"
import { cn } from "@/lib/utils"

import type { AutomationNodeCatalog, AutomationResource, GraphValidation, WorkflowGraph } from "./automation-types"
import { catalogDefinition, connectWorkflowNodes, deleteWorkflowNode, duplicateWorkflowNode, updateNodePosition } from "./workflow-graph"
import { alignWorkflowNodePosition, WORKFLOW_EDGE_ALIGNMENT_TOLERANCE, WORKFLOW_SNAP_GRID, workflowEdgeRouting } from "./workflow-layout"
import { NodeContextMenu, type NodeContextMenuState } from "./node-context-menu"
import { WORKFLOW_NODE_DRAG_TYPE } from "./workflow-node-library"
import { configuredNodeLabel, familyLabel, familyStyles, nodeIcon } from "./workflow-node-visual"

type CanvasNodeData = {
  label: string
  description: string
  family: string
  icon: unknown
  inputs: string[]
  outputs: string[]
  errorCount: number
}
type CanvasNode = Node<CanvasNodeData, "newscraft">

const WorkflowCanvasNode = memo(function WorkflowCanvasNode({ data, dragging, selected }: NodeProps<CanvasNode>) {
  const Icon = nodeIcon(data.icon)
  return (
    <div className={cn("nc-workflow-node-card w-60 cursor-grab rounded-xl border bg-card text-card-foreground shadow-sm transition-[border-color,box-shadow,transform] duration-150 ease-out active:cursor-grabbing motion-reduce:transition-none", dragging ? "scale-[1.015] border-primary/70 shadow-lg" : selected ? "border-primary shadow-md ring-2 ring-primary/20" : "border-border/70 hover:border-primary/45 hover:shadow-md")}>
      {data.inputs.map((port, index) => <Handle aria-label={`Input port ${port}`} className="nc-workflow-handle !size-4 !border-[3px] !border-card !bg-primary-solid" id={port} key={port} position={Position.Left} role="img" style={{ top: `${((index + 1) / (data.inputs.length + 1)) * 100}%` }} type="target" />)}
      <div className="flex min-h-28 items-start gap-3 p-3.5">
        <span className={cn("grid size-10 shrink-0 place-items-center rounded-lg border", familyStyles[data.family] ?? "bg-muted")}><Icon className="size-5" aria-hidden="true" /></span>
        <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-1.5"><span className="text-xs uppercase tracking-wide text-muted-foreground">{familyLabel(data.family)}</span>{data.errorCount ? <StatusBadge tone="error">{data.errorCount}</StatusBadge> : null}</div><p className="mt-1 text-sm font-semibold leading-5">{data.label}</p><p className="mt-1 line-clamp-2 text-xs leading-4 text-muted-foreground">{data.description}</p></div>
      </div>
      {data.outputs.map((port, index) => <Handle aria-label={`Output port ${port}`} className="nc-workflow-handle !size-4 !border-[3px] !border-card !bg-primary-solid" id={port} key={port} position={Position.Right} role="img" style={{ top: `${((index + 1) / (data.outputs.length + 1)) * 100}%` }} type="source" />)}
    </div>
  )
})

const WorkflowEdge = memo(function WorkflowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, markerStart, interactionWidth, style }: EdgeProps) {
  const routing = workflowEdgeRouting(sourceY, targetY, WORKFLOW_EDGE_ALIGNMENT_TOLERANCE)
  const [path] = routing === "straight"
    ? getStraightPath({ sourceX, sourceY, targetX, targetY })
    : getSmoothStepPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, borderRadius: 8, offset: 16, stepPosition: 0.5 })

  return <BaseEdge className={`nc-workflow-edge nc-workflow-edge-${routing}`} id={id} interactionWidth={interactionWidth ?? 24} markerEnd={markerEnd} markerStart={markerStart} path={path} style={style} />
})

const nodeTypes = { newscraft: WorkflowCanvasNode } satisfies NodeTypes
const edgeTypes = { workflow: WorkflowEdge } satisfies EdgeTypes

export function WorkflowCanvas({ graph, catalog, validation, selectedNodeId, resources = [], onAddNode, onGraphChange, onSelectedNodeChange, onCustomizeNode, onRejected }: { graph: WorkflowGraph; catalog: AutomationNodeCatalog; validation: GraphValidation; selectedNodeId: string | null; resources?: AutomationResource[]; onAddNode: (type: string, position: { x: number; y: number }) => void; onGraphChange: (graph: WorkflowGraph) => void; onSelectedNodeChange: (nodeId: string | null) => void; onCustomizeNode: (nodeId: string, returnFocus: HTMLElement | null) => void; onRejected: (message: string) => void }) {
  const { theme } = useTheme()
  const canvasRef = useRef<HTMLDivElement>(null)
  const flowRef = useRef<ReactFlowInstance<CanvasNode, Edge> | null>(null)
  const [contextMenu, setContextMenu] = useState<NodeContextMenuState | null>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const showPressedSelection = (event: MouseEvent) => {
      const node = (event.target as Element).closest<HTMLElement>(".react-flow__node")
      if (!node || !canvas.contains(node)) return
      canvas.querySelectorAll<HTMLElement>(".react-flow__node.selected").forEach((element) => element.classList.remove("selected"))
      node.classList.add("selected")
    }
    canvas.addEventListener("click", showPressedSelection, { capture: true })
    return () => canvas.removeEventListener("click", showPressedSelection, { capture: true })
  }, [])
  const baseNodes = useMemo<CanvasNode[]>(() => graph.nodes.map((node, index) => {
    const definition = catalogDefinition(catalog, node.type)
    const point = graph.metadata.layout[node.id] ?? { x: 80 + index * 280, y: 120 }
    const label = configuredNodeLabel(node, definition?.displayName ?? node.type, resources)
    const resourceError = node.type === "collection_article_added"
      ? resources.some((resource) => resource.kind === "collection" && resource.id === node.config.collectionId && resource.state !== "ready") ? 1 : 0
      : node.type === "new_source_item"
        ? resources.some((resource) => resource.kind === "source" && Array.isArray(node.config.sourceIds) && node.config.sourceIds.includes(resource.id) && resource.state !== "ready") ? 1 : 0
        : 0
    return {
      id: node.id,
      type: "newscraft",
      position: point,
      selected: false,
      ariaLabel: `${label}, ${definition ? familyLabel(definition.family) : "unknown"} step`,
      data: {
        label,
        description: definition?.description ?? "Unknown server node",
        family: definition?.family ?? "unknown",
        icon: definition?.uiHints.icon,
        inputs: definition?.inputs.map((port) => port.name) ?? [],
        outputs: definition?.outputs.map((port) => port.name) ?? [],
        errorCount: validation.findings.filter((item) => item.nodeId === node.id && item.severity === "error").length + resourceError,
      },
    }
  }), [catalog, graph, resources, validation.findings])
  const controlledNodes = useMemo(
    () => baseNodes.map((node) => node.id === selectedNodeId ? { ...node, selected: true } : node),
    [baseNodes, selectedNodeId],
  )
  const [nodes, setNodes] = useState(controlledNodes)
  const nodesRef = useRef(nodes)
  useEffect(() => setNodes(controlledNodes), [controlledNodes])
  useEffect(() => { nodesRef.current = nodes }, [nodes])
  const edges = useMemo<Edge[]>(() => graph.edges.map((edge, index) => ({
    id: `edge-${index}-${edge.sourceNodeId}-${edge.targetNodeId}`,
    source: edge.sourceNodeId,
    sourceHandle: edge.sourcePort,
    target: edge.targetNodeId,
    targetHandle: edge.targetPort,
    type: "workflow",
    animated: false,
    focusable: true,
    interactionWidth: 24,
    ariaLabel: `${edge.sourceNodeId} output ${edge.sourcePort} to ${edge.targetNodeId} input ${edge.targetPort}`,
  })), [graph.edges])

  const onNodesChange = (changes: NodeChange<CanvasNode>[]) => {
    let next = graph
    const acceptedChanges: NodeChange<CanvasNode>[] = []
    for (const change of changes) {
      if (change.type === "select" && change.selected) onSelectedNodeChange(change.id)
      let acceptedChange = change
      if (change.type === "position" && change.position) {
        const alignment = alignWorkflowNodePosition(change.id, change.position, nodesRef.current)
        acceptedChange = { ...change, position: alignment.position }
        if (change.dragging !== true) {
          next = updateNodePosition(next, change.id, alignment.position)
        }
      }
      if (change.type === "remove") {
        const result = deleteWorkflowNode(next, catalog, change.id)
        if (!result.graph) onRejected(result.error)
        else { next = result.graph; acceptedChanges.push(change) }
      } else {
        acceptedChanges.push(acceptedChange)
      }
    }
    setNodes((current) => {
      const updated = applyNodeChanges(acceptedChanges, current)
      nodesRef.current = updated
      return updated
    })
    if (next !== graph) onGraphChange(next)
  }
  const onEdgesChange = (changes: EdgeChange<Edge>[]) => {
    const removed = new Set(changes.filter((change) => change.type === "remove").map((change) => change.id))
    if (!removed.size) return
    onGraphChange({ ...graph, edges: graph.edges.filter((edge, index) => !removed.has(`edge-${index}-${edge.sourceNodeId}-${edge.targetNodeId}`)) })
  }
  const connectionResult = (connection: Connection | Edge) => connection.source && connection.target && connection.sourceHandle && connection.targetHandle
    ? connectWorkflowNodes(graph, catalog, { sourceNodeId: connection.source, sourcePort: connection.sourceHandle, targetNodeId: connection.target, targetPort: connection.targetHandle })
    : { error: "Choose both source and target ports." as const }
  const closeContextMenu = useCallback(() => setContextMenu(null), [])
  const selectNodeImmediately = (nodeId: string | null) => {
    document.querySelectorAll<HTMLElement>(".react-flow__node.selected").forEach((element) => element.classList.remove("selected"))
    if (nodeId) document.querySelector<HTMLElement>(`.react-flow__node[data-id="${nodeId}"]`)?.classList.add("selected")
  }

  return (
    <div className="relative h-full min-h-[520px] w-full overflow-hidden bg-background min-[900px]:min-h-0" aria-label="Workflow canvas" ref={canvasRef}>
      <ReactFlow
        ariaLabelConfig={{ "controls.ariaLabel": "Workflow canvas controls", "minimap.ariaLabel": "Workflow overview" }}
        autoPanOnNodeFocus
        colorMode={theme ?? "light"}
        edges={edges}
        edgeTypes={edgeTypes}
        edgesFocusable
        fitView
        connectionRadius={32}
        isValidConnection={(connection) => !connectionResult(connection).error}
        nodeTypes={nodeTypes}
        nodes={nodes}
        nodesFocusable
        onConnect={(connection) => { const result = connectionResult(connection); if (!result.graph) onRejected(result.error); else onGraphChange(result.graph) }}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_event, node) => {
          selectNodeImmediately(node.id)
          setNodes((current) => current.map((item) => ({ ...item, selected: item.id === node.id })))
          onSelectedNodeChange(node.id)
        }}
        onNodeContextMenu={(event, node) => {
          event.preventDefault()
          selectNodeImmediately(node.id)
          setNodes((current) => current.map((item) => ({ ...item, selected: item.id === node.id })))
          onSelectedNodeChange(node.id)
          const returnFocus = document.querySelector<HTMLElement>(`.react-flow__node[data-id="${node.id}"]`)
          const definition = catalogDefinition(catalog, graph.nodes.find((item) => item.id === node.id)?.type ?? "")
          const menuWidth = 192
          const menuHeight = 140
          const gutter = 8
          setContextMenu({
            nodeId: node.id,
            nodeLabel: node.data.label,
            x: Math.max(gutter, Math.min(event.clientX, window.innerWidth - menuWidth - gutter)),
            y: Math.max(gutter, Math.min(event.clientY, window.innerHeight - menuHeight - gutter)),
            returnFocus,
            canDuplicate: Boolean(definition && !definition.entry && !definition.terminal),
            canDelete: Boolean(definition && !definition.entry && !definition.terminal),
          })
        }}
        onNodeDragStart={() => closeContextMenu()}
        onNodesChange={onNodesChange}
        onPaneClick={() => { closeContextMenu(); selectNodeImmediately(null); setNodes((current) => current.map((item) => ({ ...item, selected: false }))); onSelectedNodeChange(null) }}
        onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy" }}
        onDrop={(event) => {
          event.preventDefault()
          const type = event.dataTransfer.getData(WORKFLOW_NODE_DRAG_TYPE) || event.dataTransfer.getData("text/plain")
          const instance = flowRef.current
          if (!type || !instance) return
          onAddNode(type, instance.screenToFlowPosition({ x: event.clientX, y: event.clientY }))
        }}
        onInit={(instance) => { flowRef.current = instance }}
        connectionLineStyle={{ stroke: "var(--primary)", strokeWidth: 2 }}
        connectionLineType={ConnectionLineType.SmoothStep}
        defaultEdgeOptions={{ animated: false, markerEnd: { type: MarkerType.ArrowClosed }, type: "workflow" }}
        elevateEdgesOnSelect
        fitViewOptions={{ maxZoom: 1.1, padding: 0.2 }}
        maxZoom={1.75}
        minZoom={0.25}
        panOnScroll
        selectionOnDrag
        snapGrid={WORKFLOW_SNAP_GRID}
        snapToGrid
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {contextMenu ? (
        <NodeContextMenu
          menu={contextMenu}
          onClose={closeContextMenu}
          onCustomize={(nodeId, returnFocus) => {
            closeContextMenu()
            onCustomizeNode(nodeId, returnFocus)
          }}
          onDuplicate={(nodeId) => {
            const result = duplicateWorkflowNode(graph, catalog, nodeId)
            if (!result.graph) onRejected(result.error)
            else {
              onGraphChange(result.graph)
              onSelectedNodeChange(result.nodeId ?? null)
            }
          }}
          onDelete={(nodeId) => {
            const result = deleteWorkflowNode(graph, catalog, nodeId)
            if (!result.graph) onRejected(result.error)
            else {
              onGraphChange(result.graph)
              onSelectedNodeChange(null)
            }
          }}
        />
      ) : null}
    </div>
  )
}

export default WorkflowCanvas

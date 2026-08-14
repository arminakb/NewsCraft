import { useReducer } from "react"

import type { WorkflowGraph } from "./automation-types"

type EditorState = {
  graph: WorkflowGraph
  savedGraph: WorkflowGraph
  past: WorkflowGraph[]
  future: WorkflowGraph[]
  selectedNodeId: string | null
}

type EditorAction =
  | { type: "commit"; graph: WorkflowGraph; selectedNodeId?: string | null }
  | { type: "select"; nodeId: string | null }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "saved"; graph: WorkflowGraph }
  | { type: "reload"; graph: WorkflowGraph }

export function useWorkflowEditorState(initialGraph: WorkflowGraph) {
  return useReducer(reducer, initialGraph, initializeEditorState)
}

export function emptyWorkflowGraph(): WorkflowGraph {
  return {
    schemaVersion: 1,
    entryNodeId: "",
    nodes: [],
    edges: [],
    outputNodeIds: [],
    metadata: { layout: {} },
  }
}

export function workflowIsDirty(state: EditorState) {
  return JSON.stringify(state.graph) !== JSON.stringify(state.savedGraph)
}

function reducer(state: EditorState, action: EditorAction): EditorState {
  if (action.type === "select") return action.nodeId === state.selectedNodeId ? state : { ...state, selectedNodeId: action.nodeId }
  if (action.type === "commit") {
    if (JSON.stringify(action.graph) === JSON.stringify(state.graph)) return state
    return {
      ...state,
      graph: action.graph,
      past: [...state.past.slice(-49), state.graph],
      future: [],
      selectedNodeId: action.selectedNodeId === undefined ? state.selectedNodeId : action.selectedNodeId,
    }
  }
  if (action.type === "undo" && state.past.length) {
    return {
      ...state,
      graph: state.past.at(-1)!,
      past: state.past.slice(0, -1),
      future: [state.graph, ...state.future.slice(0, 49)],
    }
  }
  if (action.type === "redo" && state.future.length) {
    return {
      ...state,
      graph: state.future[0],
      past: [...state.past.slice(-49), state.graph],
      future: state.future.slice(1),
    }
  }
  // The server canonicalizes the graph it stores (node/edge ordering, JSONB key
  // order), so the echo is the new editor truth: adopting it for both graphs
  // keeps the dirty comparison honest. Saving is disabled while the mutation is
  // pending, so no in-flight edit can be dropped here.
  if (action.type === "saved") return { ...state, graph: action.graph, savedGraph: action.graph }
  if (action.type === "reload") {
    return { graph: action.graph, savedGraph: action.graph, past: [], future: [], selectedNodeId: action.graph.entryNodeId }
  }
  return state
}

export type { EditorAction, EditorState }

function initializeEditorState(initialGraph: WorkflowGraph): EditorState {
  const graph = initialGraph
  return {
    graph,
    savedGraph: graph,
    past: [],
    future: [],
    selectedNodeId: graph.entryNodeId || null,
  }
}

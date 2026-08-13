"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import dynamic from "next/dynamic"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { AlertTriangle, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
import type { StatusTone } from "@/components/ui/status-badge"
import { ApiError, getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"

import { getArticleCollections } from "@/features/articles/api"
import { getSources } from "@/features/operations/ingestion-api"
import { getTelegramAutomationOptions } from "./telegram-api"
import {
  activateAutomation,
  createAutomation,
  createAutomationVersion,
  getAutomation,
  getAutomationNodeCatalog,
  getAutomationResourceCatalog,
  pauseAutomation,
  resumeAutomation,
  validateAutomationVersion,
} from "./automation-api"
import type { AutomationDetail, AutomationResource, AutomationVersion, GraphValidation, WorkflowGraph } from "./automation-types"
import { useWorkflowEditorState, workflowIsDirty } from "./workflow-editor-state"
import { insertWorkflowNode, normalizeWorkflowGraphForSave, updateNodePosition, validateWorkflowClient, workflowResourceRequests } from "./workflow-graph"
import { NodeCustomizeDialog } from "./node-customize-dialog"
import { WorkflowNodeLibrary } from "./workflow-node-library"
import { WorkflowOrderedEditor } from "./workflow-ordered-editor"
import { WorkflowToolbar } from "./workflow-toolbar"
import { WorkflowValidationDialog } from "./workflow-validation-dialog"

const WorkflowCanvas = dynamic(() => import("./workflow-canvas"), {
  ssr: false,
  loading: () => <LoadingState className="m-4 min-h-[480px]" title="Loading visual canvas…" />,
})

const AutomationTestStudio = dynamic(() => import("./automation-test-studio"), {
  ssr: false,
  loading: () => <LoadingState className="m-4" title="Loading Test Studio…" />,
})

const AutomationVersionHistory = dynamic(() => import("./automation-version-history"), {
  ssr: false,
  loading: () => null,
})

const structuralCodes = new Set([
  "edge_cardinality_invalid",
  "edge_port_invalid",
  "graph_cycle",
  "graph_entry_invalid",
  "graph_output_invalid",
  "graph_unreachable_node",
  "node_config_invalid",
  "node_type_unsupported",
])

const MESSAGE_DISMISS_MIN_MS = 3_000
const MESSAGE_DISMISS_MAX_MS = 10_000
const MESSAGE_DISMISS_BASE_MS = 1_500
const MESSAGE_DISMISS_PER_CHARACTER_MS = 40

type EditorMessage = { tone: "error" | "success" | "warning"; text: string }

function messageDismissDelay(text: string) {
  return Math.min(
    MESSAGE_DISMISS_MAX_MS,
    Math.max(MESSAGE_DISMISS_MIN_MS, MESSAGE_DISMISS_BASE_MS + text.trim().length * MESSAGE_DISMISS_PER_CHARACTER_MS),
  )
}

export function AutomationBuilder({ automationId }: { automationId: string }) {
  const detail = useQuery({ queryKey: queryKeys.automation(automationId), queryFn: ({ signal }) => getAutomation(automationId, signal) })
  const catalog = useQuery({ queryKey: queryKeys.automationNodeCatalog, queryFn: ({ signal }) => getAutomationNodeCatalog(signal) })
  if (detail.isPending || catalog.isPending) return <section className="nc-page"><LoadingState title="Loading workflow editor…" /></section>
  if (detail.isError) return <section className="nc-page"><ErrorState title="Workflow unavailable" description={getApiErrorMessage(detail.error)} action={<Button variant="outline" onClick={() => void detail.refetch()}>Retry workflow</Button>} /></section>
  if (catalog.isError) return <section className="nc-page"><ErrorState title="Node catalog unavailable" description={getApiErrorMessage(catalog.error)} action={<Button variant="outline" onClick={() => void catalog.refetch()}>Retry catalog</Button>} /></section>
  const version = detail.data.draftVersion ?? detail.data.activeVersion
  if (!version) return <section className="nc-page"><ErrorState title="Workflow has no editable version" description="Create a draft from a template or restore a prior version." /></section>
  return <AutomationBuilderReady automation={detail.data} catalog={catalog.data} initialVersion={version} key={version.id} />
}

function AutomationBuilderReady({ automation, catalog, initialVersion }: { automation: AutomationDetail; catalog: Awaited<ReturnType<typeof getAutomationNodeCatalog>>; initialVersion: AutomationVersion }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const initialGraph = useMemo(() => normalizeWorkflowGraphForSave(initialVersion.graph, catalog), [catalog, initialVersion.graph])
  const [state, dispatch] = useWorkflowEditorState(initialGraph)
  const dirty = workflowIsDirty(state)
  const releaseDirty = useDirtyNavigation(dirty, "Discard unsaved workflow changes?")
  const [revision, setRevision] = useState(automation.revision)
  const [versionNumber, setVersionNumber] = useState(initialVersion.version)
  const [currentVersion, setCurrentVersion] = useState(initialVersion)
  const [lifecycle, setLifecycle] = useState(automation.lifecycle)
  const [serverValidation, setServerValidation] = useState<GraphValidation | null>(() => validationFromVersion(initialVersion))
  const [message, setMessage] = useState<EditorMessage | null>(null)
  const [conflictOpen, setConflictOpen] = useState(false)
  const [orderedOpen, setOrderedOpen] = useState(false)
  const [customizeNode, setCustomizeNode] = useState<{ nodeId: string; returnFocus: HTMLElement | null } | null>(null)
  const [testOpen, setTestOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [attentionOpen, setAttentionOpen] = useState(false)
  const [desktopCanvas, setDesktopCanvas] = useState(false)
  const attentionTriggerRef = useRef<HTMLButtonElement>(null)
  const clientValidation = useMemo(() => validateWorkflowClient(state.graph, catalog), [catalog, state.graph])
  const currentValidation = dirty ? clientValidation : serverValidation ?? clientValidation
  const requests = useMemo(() => workflowResourceRequests(state.graph), [state.graph])
  const resources = useQuery({
    queryKey: queryKeys.automationResourceCatalog(automation.id, requests),
    queryFn: ({ signal }) => getAutomationResourceCatalog(requests, automation.id, signal),
  })
  const options = useQuery({ queryKey: queryKeys.telegramOptions, queryFn: getTelegramAutomationOptions })
  const collectionNodeSelected = state.graph.nodes.some((node) => node.id === state.selectedNodeId && node.type === "collection_article_added")
  const collections = useQuery({
    queryKey: queryKeys.articleCollections,
    queryFn: ({ signal }) => getArticleCollections(signal),
    enabled: collectionNodeSelected,
  })
  const sourceTriggerSelected = state.graph.nodes.some((node) => node.type === "new_source_item")
  const sources = useQuery({
    queryKey: queryKeys.sources,
    queryFn: ({ signal }) => getSources(signal),
    enabled: sourceTriggerSelected,
  })
  const saveBlocked = clientValidation.findings.some((item) => structuralCodes.has(item.code))
  const resourceBlocked = resources.isPending || resources.isError || Boolean(resources.data?.resources.some((resource) => resource.state !== "ready"))
  const readiness = editorReadiness(currentValidation, resources.data?.resources, resources.isPending, resources.isError)

  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)")
    const sync = () => setDesktopCanvas(media.matches)
    sync()
    media.addEventListener("change", sync)
    return () => media.removeEventListener("change", sync)
  }, [])

  useEffect(() => {
    if (window.location.hash === "#test-studio") setTestOpen(true)
  }, [])

  useEffect(() => {
    if (!message) return
    const timeoutId = window.setTimeout(() => {
      setMessage((current) => current === message ? null : current)
    }, messageDismissDelay(message.text))
    return () => window.clearTimeout(timeoutId)
  }, [message])

  const showMessage = (tone: EditorMessage["tone"], text: string) => setMessage({ tone, text })

  const saveMutation = useMutation({
    mutationFn: (graph: WorkflowGraph) => createAutomationVersion(automation.id, { expectedRevision: revision, graph, creationReason: "workflow builder save" }, key("save"), catalog),
    onSuccess: async (version) => {
      dispatch({ type: "saved", graph: normalizeWorkflowGraphForSave(version.graph, catalog) })
      setRevision((value) => value + 1)
      setVersionNumber(version.version)
      setCurrentVersion(version)
      setServerValidation(validationFromVersion(version))
      showMessage("success", `Draft version ${version.version} saved.`)
      await queryClient.invalidateQueries({ queryKey: ["automations"] })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) setConflictOpen(true)
      else showMessage("error", getApiErrorMessage(error))
    },
  })
  const validationMutation = useMutation({
    mutationFn: () => validateAutomationVersion(automation.id, versionNumber),
    onSuccess: (validation) => { setServerValidation(validation); showMessage(validation.valid ? "success" : "warning", validation.valid ? "Server validation passed." : "Server validation found issues. Review highlighted steps.") },
    onError: (error) => showMessage("error", getApiErrorMessage(error)),
  })
  const lifecycleMutation = useMutation({
    mutationFn: async () => lifecycle === "active" ? pauseAutomation(automation.id, revision) : lifecycle === "paused" ? resumeAutomation(automation.id, revision) : activateAutomation(automation.id, revision, key("activate")),
    onSuccess: async (updated) => { setLifecycle(updated.lifecycle); setRevision(updated.revision); showMessage("success", `Workflow is ${updated.lifecycle}.`); await queryClient.invalidateQueries({ queryKey: ["automations"] }) },
    onError: (error) => showMessage("error", getApiErrorMessage(error)),
  })
  const copyMutation = useMutation({
    mutationFn: () => createAutomation({ name: `${automation.name} conflict copy`, description: automation.description, graph: state.graph, creationReason: "conflict recovery copy" }, key("conflict-copy"), catalog),
    onSuccess: async (copy) => { releaseDirty(); await queryClient.invalidateQueries({ queryKey: ["automations"] }); router.push(`/automations/${copy.id}`) },
    onError: (error) => showMessage("error", getApiErrorMessage(error)),
  })

  const commit = (graph: WorkflowGraph, selectedNodeId?: string | null) => {
    dispatch({ type: "commit", graph, selectedNodeId })
    setServerValidation((value) => value ? { ...value, graphHash: `${value.graphHash}:stale` } : null)
  }
  const reject = (text: string) => showMessage("warning", text)
  const openCustomize = (nodeId?: string, returnFocus: HTMLElement | null = document.activeElement instanceof HTMLElement ? document.activeElement : null) => {
    const selectedId = nodeId ?? state.selectedNodeId
    if (!selectedId) { reject("Select a workflow step to customize."); return }
    dispatch({ type: "select", nodeId: selectedId })
    setCustomizeNode({ nodeId: selectedId, returnFocus })
  }
  const addNode = (type: string, position?: { x: number; y: number }) => {
    const result = insertWorkflowNode(state.graph, catalog, type, state.selectedNodeId)
    if (!result.graph) reject(result.error)
    else {
      const graph = position && result.nodeId ? updateNodePosition(result.graph, result.nodeId, position) : result.graph
      commit(graph, result.nodeId)
    }
  }
  const pending = saveMutation.isPending || validationMutation.isPending || lifecycleMutation.isPending
  const lifecycleAction: "Activate" | "Pause" | "Resume" = lifecycle === "active" ? "Pause" : lifecycle === "paused" ? "Resume" : "Activate"

  return (
    <section className="relative flex min-h-dvh min-w-0 flex-col bg-background min-[900px]:h-dvh min-[900px]:min-h-0 min-[900px]:overflow-hidden" aria-labelledby="automations-heading">
      <WorkflowToolbar
        dirty={dirty}
        lifecycle={{ label: humanize(lifecycle), tone: lifecycleTone(lifecycle) }}
        lifecycleAction={lifecycleAction}
        lifecycleDisabled={pending || dirty || (lifecycle !== "active" && resourceBlocked) || lifecycle === "archived" || (lifecycle !== "active" && serverValidation?.valid !== true)}
        lifecyclePending={lifecycleMutation.isPending}
        onLifecycleAction={() => lifecycleMutation.mutate()}
        onOpenAttention={() => setAttentionOpen(true)}
        onOpenHistory={() => setHistoryOpen(true)}
        onOpenOrderedEditor={() => setOrderedOpen(true)}
        onOpenTestStudio={() => setTestOpen(true)}
        onRedo={() => dispatch({ type: "redo" })}
        onSave={() => saveMutation.mutate(state.graph)}
        onUndo={() => dispatch({ type: "undo" })}
        onValidate={() => validationMutation.mutate()}
        pending={pending}
        readiness={readiness}
        attentionTriggerRef={attentionTriggerRef}
        redoDisabled={!state.future.length}
        saveDisabled={pending || !dirty || saveBlocked}
        savePending={saveMutation.isPending}
        title={automation.name}
        undoDisabled={!state.past.length}
        validationPending={validationMutation.isPending}
        versionNumber={versionNumber}
      />
      <div className="relative flex min-h-0 flex-1 flex-col">
        {message ? (
          <Alert
            className={cn(
              "absolute left-1/2 top-3 z-20 w-fit max-w-[min(40rem,calc(100%-1.5rem))] min-w-0 -translate-x-1/2 p-1.5 shadow-md motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200 motion-reduce:animate-none",
              message.tone === "error" && "border-[#001F54] bg-[#001F54] text-white forced-colors:border-[CanvasText] forced-colors:bg-[Canvas] forced-colors:text-[CanvasText]",
            )}
            tone={message.tone}
            role={message.tone === "error" ? "alert" : "status"}
            aria-atomic="true"
          >
            <div className="flex min-w-0 items-start justify-between gap-3">
              <AlertDescription className={cn("mt-0 min-w-0 flex-1 break-words whitespace-normal", message.tone === "error" && "text-white forced-colors:text-[CanvasText]")} dir="auto">
                {message.text}
              </AlertDescription>
              <Button
                aria-label="Dismiss workflow message"
                className={cn(
                  "min-h-11 min-w-11 min-[900px]:min-h-11 min-[900px]:min-w-11",
                  message.tone === "error" && "text-white/90 hover:bg-white/15 hover:text-white active:bg-white/20 focus-visible:border-white focus-visible:ring-white/80 forced-colors:text-[ButtonText]",
                )}
                onClick={() => setMessage(null)}
                size="icon"
                type="button"
                variant="ghost"
              >
                <X aria-hidden="true" />
              </Button>
            </div>
          </Alert>
        ) : null}
        <div className="min-h-0 flex-1 min-[768px]:grid min-[768px]:grid-cols-[minmax(0,1fr)] min-[1024px]:grid-cols-[272px_minmax(0,1fr)]">
          <aside className="hidden min-h-0 border-r border-border/60 bg-muted/20 min-[1024px]:block" aria-label="Node library">
            <WorkflowNodeLibrary allowEntry={!state.graph.nodes.length} catalog={catalog} afterNodeId={state.selectedNodeId ?? undefined} onAdd={addNode} />
          </aside>
          <div className="min-h-0 min-w-0 overflow-y-auto bg-muted/20 p-3 min-[768px]:overflow-hidden min-[768px]:p-0">
            {desktopCanvas ? (
              <WorkflowCanvas graph={state.graph} catalog={catalog} resources={resources.data?.resources ?? []} validation={clientValidation} selectedNodeId={state.selectedNodeId} onAddNode={addNode} onGraphChange={commit} onSelectedNodeChange={(nodeId) => dispatch({ type: "select", nodeId })} onCustomizeNode={openCustomize} onRejected={reject} />
            ) : (
              <WorkflowOrderedEditor className="mx-auto max-w-2xl" graph={state.graph} catalog={catalog} resources={resources.data?.resources ?? []} validation={clientValidation} selectedNodeId={state.selectedNodeId} onGraphChange={commit} onSelectedNodeChange={(nodeId) => dispatch({ type: "select", nodeId })} onInspect={openCustomize} onRejected={reject} />
            )}
          </div>
        </div>
        {testOpen ? (
          <section className="absolute inset-x-3 bottom-3 z-20 flex max-h-[min(72%,44rem)] flex-col overflow-hidden rounded-xl border border-border/70 bg-card shadow-lg" id="test-studio" aria-labelledby="test-studio-heading">
            <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border/60 px-4 py-2">
              <h2 className="font-semibold" id="test-studio-heading">Test Studio</h2>
              <div className="flex items-center gap-2">
                <Link className={buttonVariants({ variant: "outline", size: "sm" })} href={`/automations/runs?automationId=${automation.id}`}>View all runs</Link>
                <Button aria-label="Close Test Studio" onClick={() => setTestOpen(false)} size="icon" variant="ghost"><X aria-hidden="true" /></Button>
              </div>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
              <AutomationTestStudio automationId={automation.id} versionNumber={versionNumber} graph={state.graph} dirty={dirty} validated={serverValidation?.valid === true} onValidation={(validation) => setServerValidation(validation)} onRunStarted={(runId) => showMessage("success", `Dry run ${runId} accepted from version ${versionNumber}.`)} />
            </div>
          </section>
        ) : null}
      </div>

      <Sheet open={orderedOpen} onOpenChange={setOrderedOpen}>
        <SheetContent side="right" className="max-w-2xl">
          <div className="h-full overflow-y-auto p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"><SheetHeader className="pr-12"><SheetTitle>Ordered workflow editor</SheetTitle><SheetDescription>Same canonical graph, no drag required.</SheetDescription></SheetHeader><SheetClose aria-label="Close ordered editor" className="absolute right-3 top-3 grid size-11 place-items-center rounded-lg hover:bg-navigation-hover"><X aria-hidden="true" /></SheetClose><WorkflowOrderedEditor className="mt-5" graph={state.graph} catalog={catalog} resources={resources.data?.resources ?? []} validation={clientValidation} selectedNodeId={state.selectedNodeId} onGraphChange={commit} onSelectedNodeChange={(nodeId) => dispatch({ type: "select", nodeId })} onInspect={openCustomize} onRejected={reject} /></div>
        </SheetContent>
      </Sheet>
      {customizeNode ? <NodeCustomizeDialog key={customizeNode.nodeId} graph={state.graph} catalog={catalog} nodeId={customizeNode.nodeId} resources={resources.data?.resources ?? []} collections={collections.data} collectionsPending={collections.isPending} collectionsError={collections.error} onRetryCollections={() => void collections.refetch()} sources={sources.data} sourcesPending={sources.isPending} sourcesError={sources.error} onRetrySources={() => void sources.refetch()} options={options.data} findings={(dirty ? clientValidation : serverValidation ?? clientValidation).findings} returnFocus={customizeNode.returnFocus} onSave={commit} onClose={() => setCustomizeNode(null)} onRejected={reject} /> : null}
      {attentionOpen ? <WorkflowValidationDialog catalog={catalog} findings={currentValidation.findings} graph={state.graph} onOpenChange={setAttentionOpen} onSelectNode={(nodeId) => dispatch({ type: "select", nodeId })} open returnFocus={attentionTriggerRef.current} /> : null}
      <Dialog open={conflictOpen} onOpenChange={setConflictOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Workflow changed on server</DialogTitle><DialogDescription>Draft was not overwritten. Reload latest server version or preserve current graph as new inactive copy.</DialogDescription></DialogHeader>
          <Alert tone="warning"><AlertTriangle aria-hidden="true" className="sr-only" /><AlertTitle>No silent overwrite</AlertTitle><AlertDescription>Current unsaved graph remains in this editor until you choose.</AlertDescription></Alert>
          <DialogFooter>
            <DialogClose className={buttonVariants({ variant: "ghost" })}>Keep editing</DialogClose>
            <Button variant="outline" onClick={() => void getAutomation(automation.id).then((latest) => { const version = latest.draftVersion ?? latest.activeVersion; if (!version) return; dispatch({ type: "reload", graph: normalizeWorkflowGraphForSave(version.graph, catalog) }); setRevision(latest.revision); setVersionNumber(version.version); setCurrentVersion(version); setServerValidation(validationFromVersion(version)); setConflictOpen(false) })}>Reload server draft</Button>
            <Button disabled={copyMutation.isPending || saveBlocked} onClick={() => copyMutation.mutate()}>{copyMutation.isPending ? "Copying…" : "Create recovery copy"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {historyOpen ? <AutomationVersionHistory open={historyOpen} onOpenChange={setHistoryOpen} automationId={automation.id} activeVersionId={automation.activeVersionId} draftVersionId={currentVersion.id} currentVersion={currentVersion} expectedRevision={revision} onRestored={(version) => { dispatch({ type: "reload", graph: normalizeWorkflowGraphForSave(version.graph, catalog) }); setRevision((value) => value + 1); setVersionNumber(version.version); setCurrentVersion(version); setServerValidation(validationFromVersion(version)); showMessage("success", `Version ${version.version} restored as new draft.`) }} /> : null}
    </section>
  )
}

function validationFromVersion(version: AutomationVersion): GraphValidation | null {
  const value = version.validationSummary as Partial<GraphValidation>
  return typeof value.valid === "boolean" && Array.isArray(value.findings) && typeof value.graphHash === "string"
    ? value as GraphValidation
    : null
}

function editorReadiness(validation: GraphValidation | null, resources: AutomationResource[] | undefined, pending: boolean, error = false): { label: string; tone: StatusTone; issueCount: number } {
  const issueCount = validation?.findings.length ?? 0
  if (issueCount) return { label: "Needs attention", tone: validation?.findings.some((item) => item.severity === "error") ? "error" : "warning", issueCount }
  if (pending) return { label: "Checking readiness", tone: "warning", issueCount: 0 }
  if (error) return { label: "Resource check failed", tone: "error", issueCount: 0 }
  const blocked = resources?.find((resource) => resource.state !== "ready")
  if (blocked) return { label: humanize(blocked.state), tone: blocked.state === "unavailable" || blocked.state === "disabled" ? "error" : "warning", issueCount: 0 }
  if (!validation) return { label: "Validate draft", tone: "warning", issueCount: 0 }
  return validation.valid ? { label: "Ready", tone: "success", issueCount: 0 } : { label: "Validate draft", tone: "warning", issueCount: 0 }
}

function lifecycleTone(lifecycle: AutomationDetail["lifecycle"]): StatusTone {
  if (lifecycle === "active") return "success"
  if (lifecycle === "paused") return "warning"
  return "neutral"
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function key(action: string) {
  return `workflow-${action}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`
}

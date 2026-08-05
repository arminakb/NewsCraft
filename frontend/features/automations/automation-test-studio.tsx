"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FlaskConical, LoaderCircle, ShieldCheck } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useMemo, useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
import { getArticles } from "@/features/articles/api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

import { getAutomationRun, startAutomationRun, validateAutomationVersion } from "./automation-api"
import { AutomationRunDetail } from "./automation-run-detail"
import { isTerminalRun } from "./automation-run-state"
import type { GraphValidation, WorkflowGraph } from "./automation-types"

export default function AutomationTestStudio({
  automationId,
  versionNumber,
  graph,
  dirty,
  validated,
  onValidation,
  onRunStarted,
}: {
  automationId: string
  versionNumber: number
  graph: WorkflowGraph
  dirty: boolean
  validated: boolean
  onValidation: (validation: GraphValidation) => void
  onRunStarted: (runId: string) => void
}) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const runId = searchParams.get("runId")
  const trigger = graph.nodes.find((node) => node.id === graph.entryNodeId)
  const manual = trigger?.type === "manual"
  const telegram = trigger?.type === "telegram_new_item"
  const [storyId, setStoryId] = useState("")
  const [sourceMessageId, setSourceMessageId] = useState("")
  const [message, setMessage] = useState<{ tone: "error" | "success" | "warning"; title: string; text: string } | null>(null)
  const feed = useQuery({
    queryKey: ["articles", "automation-test-studio", { limit: 20 }],
    queryFn: ({ signal }) => getArticles({ sort: "newest", limit: 20 }, signal),
    enabled: manual,
    staleTime: 30_000,
  })
  const storyOptions = useMemo(() => {
    const byId = new Map<string, string>()
    for (const article of feed.data?.items ?? []) {
      for (const story of article.coverage.stories) byId.set(story.id, story.title)
    }
    return [...byId].map(([id, title]) => ({ id, title }))
  }, [feed.data])
  const run = useQuery({
    queryKey: runId ? queryKeys.automationRun(runId) : ["automation-runs", "none"],
    queryFn: ({ signal }) => getAutomationRun(runId as string, signal),
    enabled: Boolean(runId),
    refetchInterval: (query) => query.state.data && !isTerminalRun(query.state.data.status) ? 2_000 : false,
    refetchIntervalInBackground: false,
  })
  const validation = useMutation({
    mutationFn: () => validateAutomationVersion(automationId, versionNumber),
    onSuccess: (result) => {
      onValidation(result)
      setMessage({
        tone: result.valid ? "success" : "warning",
        title: result.valid ? "Version validated" : "Validation needs attention",
        text: result.valid ? `Persisted version ${versionNumber} is ready for dry run.` : `${result.findings.length} persisted validation finding${result.findings.length === 1 ? "" : "s"}.`,
      })
    },
    onError: (error) => setMessage({ tone: "error", title: "Validation failed", text: getApiErrorMessage(error) }),
  })
  const dryRun = useMutation({
    mutationFn: () => startAutomationRun(
      automationId,
      {
        versionNumber,
        dryRun: true,
        ...(manual && storyId ? { storyId } : {}),
        ...(telegram && sourceMessageId ? { sourceMessageId: Number(sourceMessageId) } : {}),
      },
      idempotencyKey(),
    ),
    onSuccess: async (created) => {
      onRunStarted(created.id)
      queryClient.setQueryData(queryKeys.automationRun(created.id), created)
      await queryClient.invalidateQueries({ queryKey: queryKeys.automationRuns(automationId) })
      const next = new URLSearchParams(searchParams.toString())
      next.set("runId", created.id)
      router.replace(`${pathname}?${next.toString()}#test-studio`, { scroll: false })
      setMessage({ tone: "success", title: "Durable dry run accepted", text: `Run ${created.id.slice(0, 8)} started from exact persisted version ${versionNumber}.` })
    },
    onError: (error) => setMessage({ tone: "error", title: "Dry run not started", text: getApiErrorMessage(error) }),
  })
  const invalidSourceMessage = Boolean(sourceMessageId) && (!Number.isInteger(Number(sourceMessageId)) || Number(sourceMessageId) < 1)

  return (
    <div className="flex flex-col gap-4" aria-label="Test Studio controls">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.55fr)]">
        <Card size="sm">
          <CardHeader>
            <CardTitle>Safe persisted input</CardTitle>
            <CardDescription>Test Studio starts saved version {versionNumber}. Unsaved graph and credentials never enter request.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {manual ? (
              <div className="flex flex-col gap-1.5 text-[13px] font-medium">
                <label htmlFor="test-studio-story">Feed story</label>
                <Select id="test-studio-story" aria-describedby="test-studio-story-help" value={storyId} onChange={(event) => setStoryId(event.target.value)} disabled={feed.isPending || feed.isError}>
                  <option value="">Use Story revision saved in workflow</option>
                  {storyOptions.map((story) => <option key={story.id} value={story.id}>{story.title}</option>)}
                </Select>
                <span id="test-studio-story-help" className="text-xs font-normal text-muted-foreground">Optional override resolves latest immutable revision for selected Story.</span>
              </div>
            ) : null}
            {feed.isError ? <p className="text-sm text-destructive" role="alert">Feed inputs unavailable. Saved workflow input remains usable.</p> : null}
            {telegram ? (
              <div className="flex flex-col gap-1.5 text-[13px] font-medium">
                <label htmlFor="test-studio-source-message">Telegram source message ID</label>
                <Input id="test-studio-source-message" aria-describedby="test-studio-source-message-help" value={sourceMessageId} onChange={(event) => setSourceMessageId(event.target.value)} inputMode="numeric" pattern="[0-9]*" aria-invalid={invalidSourceMessage} placeholder="Optional exact message" />
                {invalidSourceMessage ? <span id="test-studio-source-message-help" className="text-xs font-normal text-destructive" role="alert">Enter positive integer message ID.</span> : <span id="test-studio-source-message-help" className="text-xs font-normal text-muted-foreground">Leave empty for source adapter default fixture.</span>}
              </div>
            ) : null}
            {!manual && !telegram ? <p className="text-sm text-muted-foreground">Saved trigger supplies deterministic input. No additional input accepted.</p> : null}
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Test mode</CardTitle>
            <CardDescription>Unsupported partial-run, retry-node, and output comparison actions stay hidden.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <Button variant="outline" disabled={dirty || validation.isPending || dryRun.isPending} onClick={() => validation.mutate()}>{validation.isPending ? <LoaderCircle data-icon="inline-start" className="animate-spin" aria-hidden="true" /> : <ShieldCheck data-icon="inline-start" aria-hidden="true" />}{validation.isPending ? "Validating…" : "Validate only"}</Button>
            <Button disabled={dirty || !validated || invalidSourceMessage || validation.isPending || dryRun.isPending} onClick={() => dryRun.mutate()}>{dryRun.isPending ? <LoaderCircle data-icon="inline-start" className="animate-spin" aria-hidden="true" /> : <FlaskConical data-icon="inline-start" aria-hidden="true" />}{dryRun.isPending ? "Starting…" : "Start full dry run"}</Button>
            {dirty ? <p className="text-xs text-muted-foreground">Save draft before testing persisted version.</p> : !validated ? <p className="text-xs text-muted-foreground">Run Validate only before full dry run.</p> : null}
          </CardContent>
        </Card>
      </div>

      {message ? <Alert tone={message.tone} role={message.tone === "error" ? "alert" : "status"}><div><AlertTitle>{message.title}</AlertTitle><AlertDescription>{message.text}</AlertDescription></div></Alert> : null}
      {run.isPending && runId ? <LoadingState title="Loading persisted run…" /> : null}
      {run.isError ? <ErrorState title="Run unavailable" description={getApiErrorMessage(run.error)} action={<Button variant="outline" onClick={() => void run.refetch()}>Retry run</Button>} /> : null}
      {run.data ? <AutomationRunDetail run={run.data} /> : null}
    </div>
  )
}

function idempotencyKey() {
  return `workflow-dry-run-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`
}

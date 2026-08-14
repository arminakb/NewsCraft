"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useState } from "react"

import { useDateTime } from "@/components/providers/date-time-provider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox, Radio } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { PageHeader } from "@/components/ui/page-header"
import { Select } from "@/components/ui/select"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { StatusBadge } from "@/components/ui/status-badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  backfillTelegramRoute, dryRunTelegramRoute, getTelegramAutomationOptions, getTelegramDispatches,
  getTelegramRoute, pauseTelegramRoute, resumeTelegramRoute, updateTelegramRoutePromptPolicy,
} from "@/features/automations/telegram-api"
import type { TelegramAutomationOptions, TelegramRoute } from "@/features/automations/telegram-types"
import { getApiErrorMessage } from "@/lib/http"
import { formatInTimeZone, zonedLocalDateTimeToUtc } from "@/lib/date-time"
import { queryKeys } from "@/lib/query-keys"
import { DispatchResearchOutcome } from "@/features/automations/research-outcome"
import { cursorTone, dispatchTone } from "@/features/automations/automation-run-state"

export function RouteDetail({ routeId }: { routeId: string }) {
  const { timezone } = useDateTime()
  const queryClient = useQueryClient()
  const [sourceMessageId, setSourceMessageId] = useState("")
  const [backfillMode, setBackfillMode] = useState<"count" | "since">("count")
  const [count, setCount] = useState("20")
  const [since, setSince] = useState("")
  const [actionState, setActionState] = useState<{ tone: "success" | "error"; message: string } | null>(null)
  const routeQuery = useQuery({ queryKey: queryKeys.telegramRoute(routeId), queryFn: () => getTelegramRoute(routeId) })
  const dispatchesQuery = useQuery({ queryKey: queryKeys.telegramDispatches(routeId), queryFn: () => getTelegramDispatches(routeId) })
  const optionsQuery = useQuery({ queryKey: queryKeys.telegramOptions, queryFn: getTelegramAutomationOptions })
  const updateRouteTruth = (route: Awaited<ReturnType<typeof getTelegramRoute>>) => queryClient.setQueryData(queryKeys.telegramRoute(routeId), route)
  const refreshRouteList = () => queryClient.invalidateQueries({ queryKey: queryKeys.telegramRoutes, exact: true })
  const pauseMutation = useMutation({ mutationFn: () => pauseTelegramRoute(routeId), onMutate: () => setActionState(null), onSuccess: async (route) => { updateRouteTruth(route); setActionState({ tone: "success", message: "Route paused." }); await refreshRouteList() }, onError: (error) => setActionState({ tone: "error", message: getApiErrorMessage(error) }) })
  const resumeMutation = useMutation({ mutationFn: () => resumeTelegramRoute(routeId), onMutate: () => setActionState(null), onSuccess: async (route) => { updateRouteTruth(route); setActionState({ tone: "success", message: "Route resumed." }); await refreshRouteList() }, onError: (error) => setActionState({ tone: "error", message: getApiErrorMessage(error) }) })
  const dryRunMutation = useMutation({
    mutationFn: () => dryRunTelegramRoute(routeId, { sourceMessageId: sourceMessageId ? Number(sourceMessageId) : null }),
    onMutate: () => setActionState(null),
    onSuccess: async (result) => {
      setActionState({ tone: "success", message: `Dry run queued as durable job ${result.job.jobId}.` })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramDispatches(routeId) }),
        queryClient.invalidateQueries({ queryKey: ["telegram", "drafts"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ])
    },
    onError: (error) => setActionState({ tone: "error", message: getApiErrorMessage(error) }),
  })
  const sinceUtc = zonedLocalDateTimeToUtc(since, timezone)
  const backfillMutation = useMutation({
    mutationFn: () => backfillTelegramRoute(routeId, backfillMode === "count" ? { count: Number(count) } : { since: sinceUtc! }),
    onMutate: () => setActionState(null),
    onSuccess: async (result) => {
      setActionState({ tone: "success", message: `Backfill queued as durable job ${result.job.jobId}.` })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramDispatches(routeId) }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ])
    },
    onError: (error) => setActionState({ tone: "error", message: getApiErrorMessage(error) }),
  })
  const route = routeQuery.data
  const destination = optionsQuery.data?.destinations.find((item) => item.id === route?.destinationId)
  const actionPending = pauseMutation.isPending || resumeMutation.isPending || dryRunMutation.isPending || backfillMutation.isPending
  const sourceMessageNumber = sourceMessageId === "" ? null : Number(sourceMessageId)
  const sourceMessageValid = sourceMessageNumber === null || (Number.isInteger(sourceMessageNumber) && sourceMessageNumber > 0)
  const countNumber = Number(count)
  const countValid = Number.isInteger(countNumber) && countNumber >= 1 && countNumber <= 100
  const sinceValid = since !== "" && sinceUtc !== null

  if (routeQuery.isPending) return <section className="nc-page"><LoadingState title="Loading route…" /></section>
  if (routeQuery.isError) {
    return (
      <section className="nc-page">
        <ErrorState
          dir="auto"
          title="Automation route unavailable"
          description={getApiErrorMessage(routeQuery.error)}
          action={<Button variant="outline" onClick={() => void routeQuery.refetch()}>Retry route</Button>}
        />
      </section>
    )
  }
  if (!route) return null
  const cursorStatus = String(route.cursorState.status ?? "unknown")
  const readiness = routeReadiness({
    enabled: route.enabled,
    paused: Boolean(route.pausedAt),
    cursorStatus,
    destinationHealth: destination?.healthStatus,
    destinationPending: optionsQuery.isPending,
    destinationFailed: optionsQuery.isError,
  })

  return (
    <section className="nc-page" aria-labelledby="route-heading">
      <PageHeader
        title={route.name}
        titleId="route-heading"
        description="Live route state and bounded operator actions."
        actions={<>
          <Link
            className={buttonVariants({ variant: "outline" })}
            href={`/automations/telegram/${routeId}/history`}
          >
            Open durable route history
          </Link>
          <Button variant="outline" disabled={actionPending} onClick={() => route.pausedAt ? resumeMutation.mutate() : pauseMutation.mutate()}>{route.pausedAt ? "Resume route" : "Pause route"}</Button>
        </>}
      />
      <Card role="region" aria-label="Route readiness" size="sm">
        <CardHeader className="border-b">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Route readiness</CardTitle>
            <StatusBadge tone={readiness.ready ? "success" : "warning"}>{readiness.label}</StatusBadge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Next action</p>
            <p>{readiness.nextAction}</p>
          </div>
          {optionsQuery.isError ? (
            <Alert tone="warning" role="alert" dir="auto">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <AlertTitle>Destination health request failed</AlertTitle>
                  <AlertDescription>{getApiErrorMessage(optionsQuery.error)}</AlertDescription>
                </div>
                <Button size="sm" variant="outline" onClick={() => void optionsQuery.refetch()}>Retry destination health</Button>
              </div>
            </Alert>
          ) : null}
        </CardContent>
      </Card>

      <details className="rounded-lg border border-border/50 bg-card p-4 shadow-sm">
        <summary className="cursor-pointer font-medium">Advanced route details</summary>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Card size="sm"><CardHeader><CardTitle>Cursor and schedule</CardTitle></CardHeader><CardContent className="space-y-2"><StatusBadge tone={cursorTone(cursorStatus)}>{labelValue(cursorStatus)}</StatusBadge><p>{route.cursorState.lastMessageId == null ? "Last message not available" : `Last message ${route.cursorState.lastMessageId}`}</p><KeyValue label="Next poll" value={route.nextPollAt ? formatInTimeZone(route.nextPollAt, timezone) : "Not scheduled"} /><KeyValue label="Last poll" value={route.lastPolledAt ? formatInTimeZone(route.lastPolledAt, timezone) : "Not polled"} /></CardContent></Card>
          <Card size="sm"><CardHeader><CardTitle>Policy</CardTitle></CardHeader><CardContent className="space-y-2"><KeyValue label="Prompt updates" value={labelValue(route.promptPolicy)} /><KeyValue label="Publishing" value={labelValue(route.publishingPolicy)} /><KeyValue label="Research" value={labelValue(route.researchMode)} /><KeyValue label="Research provider" value={route.contentFilters.researchProviderProfileId ? optionsQuery.data?.aiProviderProfiles.find((item) => item.id === route.contentFilters.researchProviderProfileId)?.name ?? "Configured profile" : "Not selected"} /><KeyValue label="Access" value={labelValue(route.accessMode)} /><KeyValue label="Media" value={labelValue(route.mediaPolicy)} /><KeyValue label="Polling" value={`${route.pollIntervalSeconds} seconds`} /><KeyValue label="Retry limit" value={`${route.retryPolicy.maxAttempts} attempts`} /><KeyValue label="Quiet hours" value={route.quietHours ? `${route.quietHours.start}–${route.quietHours.end} (${route.quietHours.timezone})` : "Not configured"} /></CardContent></Card>
          <Card size="sm"><CardHeader><CardTitle>Destination health</CardTitle></CardHeader><CardContent className="space-y-2"><StatusBadge tone={destination?.healthStatus === "healthy" ? "success" : optionsQuery.isPending ? "warning" : "error"}>{destination ? labelValue(destination.healthStatus) : optionsQuery.isPending ? "Checking" : "Destination not configured"}</StatusBadge><p className="text-muted-foreground">{destination?.name ?? "Destination details unavailable"}</p></CardContent></Card>
        </div>
      </details>

      {optionsQuery.data ? (
        <details className="rounded-lg border border-border/50 bg-card p-4 shadow-sm">
          <summary className="cursor-pointer font-medium">Edit automation settings</summary>
          <div className="mt-4">
            <PromptPolicyControl
              key={`${route.promptPolicy}:${route.promptTemplateVersionId}`}
              route={route}
              options={optionsQuery.data}
              onUpdated={(updated) => {
                updateRouteTruth(updated)
                setActionState({ tone: "success", message: "Prompt update policy changed." })
              }}
            />
          </div>
        </details>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Dry run</CardTitle></CardHeader><CardContent className="space-y-3"><label className="grid gap-1"><span>Source message ID (optional)</span><Input type="number" min={1} step={1} value={sourceMessageId} onChange={(e) => setSourceMessageId(e.target.value)} aria-invalid={!sourceMessageValid} /></label>{!sourceMessageValid ? <div role="alert" className="text-destructive">Source message ID must be a positive integer.</div> : null}<p className="text-sm text-muted-foreground">Dry runs always force review and never auto-publish.</p><Button disabled={actionPending || !sourceMessageValid} onClick={() => dryRunMutation.mutate()}>Run dry run</Button></CardContent></Card>
        <Card><CardHeader><CardTitle>Bounded backfill</CardTitle></CardHeader><CardContent className="space-y-3"><fieldset className="space-y-2"><legend className="font-medium">Backfill bound</legend><label className="me-4 inline-flex min-h-11 items-center gap-2"><Radio name="bound" checked={backfillMode === "count"} onChange={() => setBackfillMode("count")} /><span>Count bound</span></label><label className="inline-flex min-h-11 items-center gap-2"><Radio name="bound" checked={backfillMode === "since"} onChange={() => setBackfillMode("since")} />Since date</label></fieldset><label className="grid gap-1"><span>Message count</span><Input type="number" min={1} max={100} step={1} disabled={backfillMode !== "count"} value={count} onChange={(e) => setCount(e.target.value)} aria-invalid={backfillMode === "count" && !countValid} /></label>{backfillMode === "count" && !countValid ? <div role="alert" className="text-destructive">Message count must be an integer from 1 to 100.</div> : null}<label className="grid gap-1"><span>Since date and time ({timezone})</span><Input type="datetime-local" disabled={backfillMode !== "since"} value={since} onChange={(e) => setSince(e.target.value)} aria-invalid={backfillMode === "since" && !sinceValid} /></label><Button disabled={actionPending || (backfillMode === "since" ? !sinceValid : !countValid)} onClick={() => backfillMutation.mutate()}>Queue backfill</Button></CardContent></Card>
      </div>
      {actionState ? <Alert tone={actionState.tone} role={actionState.tone === "error" ? "alert" : "status"} aria-label="Latest route action" dir="auto"><AlertDescription>{actionState.message}</AlertDescription></Alert> : null}

      <Card size="sm">
        <CardHeader className="border-b"><CardTitle>Dispatch history</CardTitle></CardHeader>
        <CardContent className="px-0">
          {dispatchesQuery.data?.length ? (
            <Table className="min-w-[760px]">
              <TableHeader><TableRow><TableHead>Message</TableHead><TableHead>Status</TableHead><TableHead>Research</TableHead><TableHead>Failure</TableHead><TableHead>Revision / publish job</TableHead></TableRow></TableHeader>
              <TableBody>
                {dispatchesQuery.data.map((dispatch) => (
                  <TableRow key={dispatch.id}>
                    <TableCell className="tabular-nums">{dispatch.sourceMessageIds.length ? dispatch.sourceMessageIds.join(", ") : "—"}</TableCell>
                    <TableCell><StatusBadge tone={dispatchTone(dispatch.status)}>{labelValue(dispatch.status)}</StatusBadge></TableCell>
                    <TableCell><DispatchResearchOutcome dispatch={dispatch} researchMode={route.researchMode} /></TableCell>
                    <TableCell className="max-w-60 whitespace-normal" dir="auto">{dispatch.errorMessage ?? "—"}</TableCell>
                    <TableCell className="max-w-72 whitespace-normal">{dispatch.variantRevisionId ? <Link className="text-primary underline underline-offset-4" href={`/review/${dispatch.variantRevisionId}`}>Review revision {dispatch.variantRevisionId}</Link> : dispatch.publishJobId ? <span className="break-all font-mono text-xs">Publish job {dispatch.publishJobId}</span> : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
          {dispatchesQuery.isPending ? <LoadingState className="m-3" title="Loading dispatch history…" /> : null}
          {dispatchesQuery.isError ? <ErrorState className="m-3" dir="auto" title="Dispatch history unavailable" description={getApiErrorMessage(dispatchesQuery.error)} action={<Button variant="outline" onClick={() => void dispatchesQuery.refetch()}>Retry dispatch history</Button>} /> : null}
          {dispatchesQuery.isSuccess && !dispatchesQuery.data.length ? <EmptyState className="m-3" title="No dispatches yet" description="Run a dry run or wait for the next scheduled poll." /> : null}
        </CardContent>
      </Card>
    </section>
  )
}

function PromptPolicyControl({
  route,
  options,
  onUpdated,
}: {
  route: TelegramRoute
  options: TelegramAutomationOptions
  onUpdated: (route: TelegramRoute) => void
}) {
  const [policy, setPolicy] = useState(route.promptPolicy)
  const [versionId, setVersionId] = useState(route.promptTemplateVersionId)
  const [confirmed, setConfirmed] = useState(false)
  const mutation = useMutation({
    mutationFn: () => updateTelegramRoutePromptPolicy(route.id, {
      promptPolicy: policy,
      promptTemplateVersionId: policy === "pinned" ? versionId : null,
      confirmChange: confirmed,
    }),
    onSuccess: onUpdated,
  })
  const changed = policy !== route.promptPolicy || (policy === "pinned" && versionId !== route.promptTemplateVersionId)
  return (
    <Card>
      <CardHeader><CardTitle>Prompt update policy</CardTitle></CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-sm font-medium">
          <span>Mode</span>
          <Select value={policy} disabled={mutation.isPending} onChange={(event) => { setPolicy(event.target.value as TelegramRoute["promptPolicy"]); setConfirmed(false) }}>
            <option value="follow_active">Follow active prompt</option>
            <option value="pinned">Pinned version</option>
          </Select>
        </label>
        <label className="grid gap-1 text-sm font-medium">
          <span>Pinned version</span>
          <Select value={versionId} disabled={mutation.isPending || policy !== "pinned"} onChange={(event) => { setVersionId(event.target.value); setConfirmed(false) }}>
            {options.promptTemplateVersions.map((item) => <option key={item.id} value={item.id}>Version {item.version}{item.isActive ? " · active" : ""}</option>)}
          </Select>
        </label>
        <p className="text-sm text-muted-foreground md:col-span-2">
          Follow active resolves once per job. Pinned keeps exact selected version. Existing queued jobs retain stored version and checksum.
        </p>
        {changed ? <label className="flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm md:col-span-2"><Checkbox checked={confirmed} disabled={mutation.isPending} onChange={(event) => setConfirmed(event.target.checked)} />Confirm this changes prompt selection for future jobs</label> : null}
        {mutation.isError ? <Alert tone="error" role="alert" dir="auto" className="md:col-span-2"><AlertDescription>{getApiErrorMessage(mutation.error)}</AlertDescription></Alert> : null}
        <Button className="w-fit" disabled={!changed || !confirmed || mutation.isPending || (policy === "pinned" && !versionId)} onClick={() => mutation.mutate()}>
          {mutation.isPending ? "Saving policy" : "Save prompt policy"}
        </Button>
      </CardContent>
    </Card>
  )
}

function KeyValue({ label, value }: { label: string; value: string }) { return <div><p className="text-xs text-muted-foreground">{label}</p><p className="break-words tabular-nums">{value}</p></div> }
function labelValue(value: string) {
  if (value === "public_html") return "Public HTML"
  return value.split("_").map((part) => part[0]?.toUpperCase() + part.slice(1)).join(" ")
}
function routeReadiness({
  enabled,
  paused,
  cursorStatus,
  destinationHealth,
  destinationPending,
  destinationFailed,
}: {
  enabled: boolean
  paused: boolean
  cursorStatus: string
  destinationHealth?: string
  destinationPending: boolean
  destinationFailed: boolean
}) {
  if (!enabled) return { ready: false, label: "Activation required", nextAction: "Activate this route before expecting new stories." }
  if (paused) return { ready: false, label: "Paused", nextAction: "Resume the route when collection should continue." }
  if (destinationFailed) return { ready: false, label: "Health unavailable", nextAction: "Retry the destination health check before publishing." }
  if (destinationPending) return { ready: false, label: "Checking", nextAction: "Wait for destination readiness to finish." }
  if (!destinationHealth) return { ready: false, label: "Blocked", nextAction: "Configure a Telegram destination for this route." }
  if (destinationHealth !== "healthy") return { ready: false, label: "Destination blocked", nextAction: "Repair and verify the Telegram destination." }
  if (cursorStatus !== "ready") return { ready: false, label: "Initializing", nextAction: "Wait for the activation boundary to finish, then run a dry run." }
  return { ready: true, label: "Ready", nextAction: "Run a dry run for a safe end-to-end check, or leave the route collecting." }
}

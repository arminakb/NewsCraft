"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  backfillTelegramRoute, dryRunTelegramRoute, getTelegramAutomationOptions, getTelegramDispatches,
  getTelegramRoute, pauseTelegramRoute, resumeTelegramRoute,
} from "@/features/automations/telegram-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { DispatchResearchOutcome } from "@/features/automations/research-outcome"

const inputClass = "h-10 w-full rounded-lg border border-input bg-background px-3 text-sm"

export function RouteDetail({ routeId }: { routeId: string }) {
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
  const backfillMutation = useMutation({
    mutationFn: () => backfillTelegramRoute(routeId, backfillMode === "count" ? { count: Number(count) } : { since: new Date(since).toISOString() }),
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
  const sinceValid = since !== "" && Number.isFinite(new Date(since).getTime())

  if (routeQuery.isPending) return <div role="status" className="p-6">Loading route</div>
  if (routeQuery.isError) return <div role="alert" dir="auto" className="p-6">{getApiErrorMessage(routeQuery.error)}</div>
  if (!route) return null
  const cursorStatus = String(route.cursorState.status ?? "unknown")

  return (
    <section className="min-w-0 space-y-4 p-4 md:p-6" aria-labelledby="route-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 id="route-heading" className="text-2xl font-semibold">{route.name}</h1>
          <p className="text-muted-foreground">Live route state and bounded operator actions.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            className="inline-flex min-h-11 items-center rounded-lg border bg-background px-3 text-sm font-medium hover:bg-muted min-[900px]:min-h-0"
            href={`/automations/${routeId}/history`}
          >
            Open durable route history
          </Link>
          <Button variant="outline" disabled={actionPending} onClick={() => route.pausedAt ? resumeMutation.mutate() : pauseMutation.mutate()}>{route.pausedAt ? "Resume route" : "Pause route"}</Button>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card><CardHeader><CardTitle>Cursor and schedule</CardTitle></CardHeader><CardContent className="space-y-2"><Badge>{labelValue(cursorStatus)}</Badge><p>{route.cursorState.lastMessageId == null ? "Last message not available" : `Last message ${route.cursorState.lastMessageId}`}</p><KeyValue label="Next poll" value={route.nextPollAt ? formatDate(route.nextPollAt) : "Not scheduled"} /><KeyValue label="Last poll" value={route.lastPolledAt ? formatDate(route.lastPolledAt) : "Not polled"} /></CardContent></Card>
        <Card><CardHeader><CardTitle>Policy</CardTitle></CardHeader><CardContent className="space-y-2"><KeyValue label="Publishing" value={labelValue(route.publishingPolicy)} /><KeyValue label="Research" value={labelValue(route.researchMode)} /><KeyValue label="Research provider" value={route.contentFilters.researchProviderProfileId ? optionsQuery.data?.aiProviderProfiles.find((item) => item.id === route.contentFilters.researchProviderProfileId)?.name ?? "Configured profile" : "Not selected"} />{route.researchMode === "manual" ? <Link href="/inbox" className="inline-flex text-primary underline">Research more</Link> : null}<KeyValue label="Access" value={labelValue(route.accessMode)} /><KeyValue label="Media" value={labelValue(route.mediaPolicy)} /><KeyValue label="Polling" value={`${route.pollIntervalSeconds} seconds`} /><KeyValue label="Retry limit" value={`${route.retryPolicy.maxAttempts} attempts`} /><KeyValue label="Quiet hours" value={route.quietHours ? `${route.quietHours.start}–${route.quietHours.end} (${route.quietHours.timezone})` : "Not configured"} /></CardContent></Card>
        <Card><CardHeader><CardTitle>Destination health</CardTitle></CardHeader><CardContent className="space-y-2">{optionsQuery.isError ? <><div role="alert" dir="auto" className="text-red-700">Destination health request failed: {getApiErrorMessage(optionsQuery.error)}</div><Button variant="outline" onClick={() => void optionsQuery.refetch()}>Retry destination health</Button></> : <><p>{destination ? labelValue(destination.healthStatus) : optionsQuery.isPending ? "Checking" : "Destination not configured"}</p><p className="text-muted-foreground">{destination?.name ?? "Destination details unavailable"}</p></>}</CardContent></Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Dry run</CardTitle></CardHeader><CardContent className="space-y-3"><label className="grid gap-1"><span>Source message ID (optional)</span><input className={inputClass} type="number" min={1} step={1} value={sourceMessageId} onChange={(e) => setSourceMessageId(e.target.value)} aria-invalid={!sourceMessageValid} /></label>{!sourceMessageValid ? <div role="alert" className="text-red-700">Source message ID must be a positive integer.</div> : null}<p className="text-sm text-muted-foreground">Dry runs always force review and never auto-publish.</p><Button disabled={actionPending || !sourceMessageValid} onClick={() => dryRunMutation.mutate()}>Run dry run</Button></CardContent></Card>
        <Card><CardHeader><CardTitle>Bounded backfill</CardTitle></CardHeader><CardContent className="space-y-3"><fieldset className="space-y-2"><legend className="font-medium">Backfill bound</legend><label className="me-4 inline-flex gap-2"><input type="radio" name="bound" checked={backfillMode === "count"} onChange={() => setBackfillMode("count")} /><span>Count bound</span></label><label className="inline-flex gap-2"><input type="radio" name="bound" checked={backfillMode === "since"} onChange={() => setBackfillMode("since")} />Since date</label></fieldset><label className="grid gap-1"><span>Message count</span><input className={inputClass} type="number" min={1} max={100} step={1} disabled={backfillMode !== "count"} value={count} onChange={(e) => setCount(e.target.value)} aria-invalid={backfillMode === "count" && !countValid} /></label>{backfillMode === "count" && !countValid ? <div role="alert" className="text-red-700">Message count must be an integer from 1 to 100.</div> : null}<label className="grid gap-1"><span>Since date and time</span><input className={inputClass} type="datetime-local" disabled={backfillMode !== "since"} value={since} onChange={(e) => setSince(e.target.value)} aria-invalid={backfillMode === "since" && !sinceValid} /></label><Button disabled={actionPending || (backfillMode === "since" ? !sinceValid : !countValid)} onClick={() => backfillMutation.mutate()}>Queue backfill</Button></CardContent></Card>
      </div>
      {actionState ? <div role={actionState.tone === "error" ? "alert" : "status"} aria-label="Latest route action" dir="auto" className={actionState.tone === "error" ? "text-red-700" : "text-green-700"}>{actionState.message}</div> : null}

      <Card><CardHeader><CardTitle>Dispatch history</CardTitle></CardHeader><CardContent className="px-0"><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-start text-sm"><thead><tr className="border-b"><th className="p-3 text-start">Message</th><th className="p-3 text-start">Status</th><th className="p-3 text-start">Research</th><th className="p-3 text-start">Failure</th><th className="p-3 text-start">Revision / publish job</th></tr></thead><tbody>{dispatchesQuery.data?.map((dispatch) => <tr key={dispatch.id} className="border-b last:border-0"><td className="p-3">{dispatch.sourceMessageIds.length ? dispatch.sourceMessageIds.join(", ") : "—"}</td><td className="p-3">{labelValue(dispatch.status)}</td><td className="p-3"><DispatchResearchOutcome dispatch={dispatch} researchMode={route.researchMode} /></td><td className="p-3" dir="auto">{dispatch.errorMessage ?? "—"}</td><td className="p-3">{dispatch.variantRevisionId ? <Link className="underline" href={`/review/${dispatch.variantRevisionId}`}>Review revision {dispatch.variantRevisionId}</Link> : dispatch.publishJobId ? <span className="break-all">Publish job {dispatch.publishJobId}</span> : "—"}</td></tr>)}</tbody></table></div>{dispatchesQuery.isPending ? <div role="status" className="p-4">Loading dispatch history</div> : null}{dispatchesQuery.isError ? <div role="alert" dir="auto" className="p-4">{getApiErrorMessage(dispatchesQuery.error)}</div> : null}{dispatchesQuery.isSuccess && !dispatchesQuery.data.length ? <p className="p-4 text-muted-foreground">No dispatches yet</p> : null}</CardContent></Card>
    </section>
  )
}

function KeyValue({ label, value }: { label: string; value: string }) { return <div><p className="text-xs text-muted-foreground">{label}</p><p>{value}</p></div> }
function labelValue(value: string) {
  if (value === "public_html") return "Public HTML"
  return value.split("_").map((part) => part[0]?.toUpperCase() + part.slice(1)).join(" ")
}
function formatDate(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) }

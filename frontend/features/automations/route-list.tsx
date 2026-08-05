"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { useDateTime } from "@/components/providers/date-time-provider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { PageHeader } from "@/components/ui/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"
import { getTelegramAutomationOptions, getTelegramRoutes } from "@/features/automations/telegram-api"
import { getApiErrorMessage } from "@/lib/http"
import { formatInTimeZone } from "@/lib/date-time"
import { queryKeys } from "@/lib/query-keys"

export function RouteList() {
  const { timezone } = useDateTime()
  const routesQuery = useQuery({ queryKey: queryKeys.telegramRoutes, queryFn: getTelegramRoutes })
  const optionsQuery = useQuery({ queryKey: queryKeys.telegramOptions, queryFn: getTelegramAutomationOptions })
  return (
    <section className="nc-page" aria-labelledby="automations-heading">
      <PageHeader
        title="Telegram automations"
        titleId="automations-heading"
        description="Monitor route policy, cursor progress, health, and operator actions."
        actions={<Link className={buttonVariants()} href="/automations/telegram/new">New automation</Link>}
      />
      {routesQuery.isPending ? <LoadingState title="Loading automations…" /> : null}
      {routesQuery.isError ? (
        <ErrorState
          dir="auto"
          title="Automations could not be loaded"
          description={getApiErrorMessage(routesQuery.error)}
          action={<Button variant="outline" onClick={() => void routesQuery.refetch()}>Retry automations</Button>}
        />
      ) : null}
      {optionsQuery.isError ? (
        <Alert tone="warning" role="alert" dir="auto">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <AlertTitle>Destination health unavailable</AlertTitle>
              <AlertDescription>{getApiErrorMessage(optionsQuery.error)}</AlertDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => void optionsQuery.refetch()}>Retry destination health</Button>
          </div>
        </Alert>
      ) : null}
      {routesQuery.isSuccess && !routesQuery.data.length ? <EmptyState title="No Telegram automations yet" description="Create an automation to connect a source with a verified destination." /> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {routesQuery.data?.map((route) => {
          const cursorStatus = String(route.cursorState.status ?? "unknown")
          const destination = optionsQuery.data?.destinations.find((item) => item.id === route.destinationId)
          const routeState = route.pausedAt ? "Paused" : route.enabled ? "Active" : "Inactive"
          return <Card key={route.id} size="sm">
            <CardHeader className="border-b"><CardTitle><Link className="underline-offset-4 hover:underline" href={`/automations/telegram/${route.id}`}>{route.name}</Link></CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <StatusBadge tone={cursorTone(cursorStatus)}>{labelValue(cursorStatus)}</StatusBadge>
                <StatusBadge tone={routeState === "Active" ? "success" : routeState === "Paused" ? "warning" : "neutral"}>{routeState}</StatusBadge>
                <StatusBadge tone="info">{labelValue(route.publishingPolicy)}</StatusBadge>
              </div>
              <dl className="grid gap-3 text-[13px] sm:grid-cols-2">
                <Metric label="Last message" value={route.cursorState.lastMessageId == null ? "Not available" : String(route.cursorState.lastMessageId)} />
                <Metric label="Next poll" value={route.nextPollAt ? formatDate(route.nextPollAt, timezone) : "Not scheduled"} />
                <Metric label="Destination health" value={destination ? labelValue(destination.healthStatus) : optionsQuery.isPending ? "Checking" : optionsQuery.isError ? "Health request failed" : "Destination not configured"} />
                <Metric label="Last poll" value={route.lastPolledAt ? formatDate(route.lastPolledAt, timezone) : "Not polled"} />
              </dl>
              <Link className={buttonVariants({ variant: "outline" })} href={`/automations/telegram/${route.id}`}>Open route</Link>
            </CardContent>
          </Card>
        })}
      </div>
    </section>
  )
}

function labelValue(value: string) { return value.split("_").map((part) => part[0]?.toUpperCase() + part.slice(1)).join(" ") }
function formatDate(value: string, timezone: string) {
  return formatInTimeZone(value, timezone)
}
function cursorTone(value: string): StatusTone {
  if (value === "ready") return "success"
  if (["failed", "error"].includes(value)) return "error"
  if (["initializing", "checking"].includes(value)) return "warning"
  return "neutral"
}
function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="break-words font-medium tabular-nums">{value}</dd></div>
}

"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getTelegramAutomationOptions, getTelegramRoutes } from "@/features/automations/telegram-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function RouteList() {
  const routesQuery = useQuery({ queryKey: queryKeys.telegramRoutes, queryFn: getTelegramRoutes })
  const optionsQuery = useQuery({ queryKey: queryKeys.telegramOptions, queryFn: getTelegramAutomationOptions })
  return (
    <section className="min-w-0 space-y-4 p-4 md:p-6" aria-labelledby="automations-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 id="automations-heading" className="text-2xl font-semibold">Telegram automations</h1><p className="text-muted-foreground">Monitor route policy, cursor progress, health, and operator actions.</p></div>
        <Link className={buttonVariants()} href="/automations/new">New automation</Link>
      </div>
      {routesQuery.isPending ? <div role="status">Loading automations</div> : null}
      {routesQuery.isError ? <div role="alert" dir="auto">{getApiErrorMessage(routesQuery.error)}</div> : null}
      {optionsQuery.isError ? <div className="flex flex-wrap items-center gap-3" role="alert" dir="auto"><span>Destination health request failed: {getApiErrorMessage(optionsQuery.error)}</span><Button variant="outline" onClick={() => void optionsQuery.refetch()}>Retry destination health</Button></div> : null}
      {routesQuery.isSuccess && !routesQuery.data.length ? <div className="rounded-xl border p-8 text-center text-muted-foreground">No Telegram automations yet</div> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {routesQuery.data?.map((route) => {
          const cursorStatus = String(route.cursorState.status ?? "unknown")
          const destination = optionsQuery.data?.destinations.find((item) => item.id === route.destinationId)
          return <Card key={route.id}>
            <CardHeader><CardTitle><Link className="hover:underline" href={`/automations/${route.id}`}>{route.name}</Link></CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2"><Badge>{labelValue(cursorStatus)}</Badge><Badge variant="outline">{route.pausedAt ? "Paused" : route.enabled ? "Active" : "Inactive"}</Badge><Badge variant="outline">{labelValue(route.publishingPolicy)}</Badge></div>
              <dl className="grid grid-cols-2 gap-2 text-sm"><div><dt className="text-muted-foreground">Last message</dt><dd>{route.cursorState.lastMessageId == null ? "Not available" : String(route.cursorState.lastMessageId)}</dd></div><div><dt className="text-muted-foreground">Next poll</dt><dd>{route.nextPollAt ? formatDate(route.nextPollAt) : "Not scheduled"}</dd></div><div><dt className="text-muted-foreground">Destination health</dt><dd>{destination ? labelValue(destination.healthStatus) : optionsQuery.isPending ? "Checking" : optionsQuery.isError ? "Health request failed" : "Destination not configured"}</dd></div><div><dt className="text-muted-foreground">Last poll</dt><dd>{route.lastPolledAt ? formatDate(route.lastPolledAt) : "Not polled"}</dd></div></dl>
              <Link className={buttonVariants({ variant: "outline" })} href={`/automations/${route.id}`}>Open route</Link>
            </CardContent>
          </Card>
        })}
      </div>
    </section>
  )
}

function labelValue(value: string) { return value.split("_").map((part) => part[0]?.toUpperCase() + part.slice(1)).join(" ") }
function formatDate(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) }

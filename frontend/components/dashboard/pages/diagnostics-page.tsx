"use client"

import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, CheckCircle2, CircleHelp, XCircle } from "lucide-react"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getDiagnostics } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"

const healthIcon = {
  ok: CheckCircle2,
  healthy: CheckCircle2,
  partial: AlertTriangle,
  failed: XCircle,
  unknown: CircleHelp,
}

export function DiagnosticsPage() {
  const diagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnostics,
    queryFn: getDiagnostics,
  })
  const diagnostics = diagnosticsQuery.data

  return (
    <OperationsPageFrame title="Diagnostics" subtitle="Check backend health, source health, and operational warnings.">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card className="rounded-md py-0" size="sm">
          <CardHeader className="border-b px-3 py-3">
            <CardTitle className="text-base">System checks</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 p-3">
            {Object.entries(diagnostics?.checks ?? {}).map(([name, status]) => {
              const Icon = healthIcon[status as keyof typeof healthIcon] ?? CircleHelp
              return (
                <div key={name} className="flex items-center justify-between rounded-md border px-3 py-2">
                  <span className="font-medium">{name}</span>
                  <Badge variant="outline" className="h-6 gap-1 rounded-md">
                    <Icon className="size-3" aria-hidden="true" />
                    {status}
                  </Badge>
                </div>
              )
            })}
          </CardContent>
        </Card>
        <Card className="rounded-md py-0" size="sm">
          <CardHeader className="border-b px-3 py-3">
            <CardTitle className="text-base">Source health</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 p-3">
            {Object.entries(diagnostics?.sourceHealth ?? {}).map(([status, count]) => (
              <div key={status} className="rounded-md border p-3">
                <div className="text-xs capitalize text-muted-foreground">{status}</div>
                <div className="mt-1 text-2xl tabular-nums">{count}</div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <Card className="rounded-md py-0" size="sm">
        <CardHeader className="border-b px-3 py-3">
          <CardTitle className="text-base">Problem sources</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="divide-y">
            {(diagnostics?.problemSources ?? []).map((source) => (
              <div key={String(source.id ?? source.name)} className="grid grid-cols-[minmax(180px,1fr)_120px_minmax(160px,2fr)] gap-3 px-3 py-3 text-sm">
                <span className="font-medium">{String(source.name ?? source.id ?? "Unknown source")}</span>
                <span>{String(source.status ?? source.health_status ?? "unknown")}</span>
                <span className="text-muted-foreground">{String(source.error ?? source.last_error ?? source.reason ?? "-")}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </OperationsPageFrame>
  )
}

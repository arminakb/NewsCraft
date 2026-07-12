"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, CheckCircle2, ChevronRight, Play, XCircle } from "lucide-react"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { getIngestRuns, runIngest } from "@/lib/api-client"
import { formatNumber } from "@/lib/format"
import { queryKeys } from "@/lib/query-keys"
import type { IngestionRunSummary } from "@/lib/types"
import { cn } from "@/lib/utils"

const runPresentation = {
  succeeded: { Icon: CheckCircle2, iconClass: "text-emerald-600", progressClass: "[&_[data-slot=progress-indicator]]:bg-primary" },
  partial: { Icon: AlertTriangle, iconClass: "text-amber-500", progressClass: "[&_[data-slot=progress-indicator]]:bg-amber-500" },
  failed: { Icon: XCircle, iconClass: "text-red-600", progressClass: "[&_[data-slot=progress-indicator]]:bg-red-500" },
}

export function RunsPage({
  initialRuns = [],
  enableQueries = true,
}: {
  initialRuns?: IngestionRunSummary[]
  enableQueries?: boolean
}) {
  const queryClient = useQueryClient()
  const runsQuery = useQuery({
    queryKey: queryKeys.runs,
    queryFn: getIngestRuns,
    placeholderData: initialRuns,
    enabled: enableQueries,
  })
  const ingestMutation = useMutation({
    mutationFn: () => runIngest({}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.runs }),
  })
  const runs = runsQuery.data ?? initialRuns

  return (
    <OperationsPageFrame
      enableQueries={enableQueries}
      title="Ingestion Runs"
      subtitle="Track manual and scheduled ingestion activity."
      actions={
        <Button className="h-9 gap-2" onClick={() => ingestMutation.mutate()} disabled={ingestMutation.isPending}>
          <Play className="size-4" aria-hidden="true" />
          {ingestMutation.isPending ? "Running" : "Run ingest"}
        </Button>
      }
    >
      <RunsList runs={runs} />
    </OperationsPageFrame>
  )
}

function RunsList({ runs }: { runs: IngestionRunSummary[] }) {
  return (
    <Card role="region" aria-label="Ingestion runs" className="rounded-md py-0" size="sm">
      <CardHeader className="border-b px-3 py-3"><CardTitle className="text-base">Ingestion runs</CardTitle></CardHeader>
      <CardContent className="px-0">
        <div className="overflow-x-auto">
          <div className="min-w-[620px] divide-y">
            {runs.length ? runs.map((run) => {
              const display = runPresentation[run.status]
              return (
                <div key={run.id} className="grid grid-cols-[28px_minmax(110px,1fr)_1.2fr_42px_48px_72px_28px] items-center gap-3 px-3 py-3 text-sm">
                  <display.Icon className={cn("size-5", display.iconClass)} aria-hidden="true" />
                  <div className="min-w-0"><div className="truncate font-medium">{run.label}</div><div className="text-xs text-muted-foreground">{run.scope}</div></div>
                  <Progress value={run.progress} className={cn("min-w-28", display.progressClass)} />
                  <span className="text-right text-xs tabular-nums">{run.progress}%</span>
                  <span className="text-right text-xs tabular-nums">{run.duration}</span>
                  <span className="text-right text-xs tabular-nums">{formatNumber(run.items)} items</span>
                  <ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" />
                </div>
              )
            }) : <div className="px-3 py-8 text-center text-sm text-muted-foreground">No ingestion runs yet</div>}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

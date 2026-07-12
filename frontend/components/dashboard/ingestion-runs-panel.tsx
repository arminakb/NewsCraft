import { AlertTriangle, CheckCircle2, ChevronRight, XCircle } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { IngestionRunSummary } from "@/lib/types"

const statusIcon = {
  succeeded: CheckCircle2,
  partial: AlertTriangle,
  failed: XCircle,
}

const statusClass = {
  succeeded: "text-emerald-600",
  partial: "text-amber-500",
  failed: "text-red-600",
}

const progressClass = {
  succeeded: "[&_[data-slot=progress-indicator]]:bg-primary",
  partial: "[&_[data-slot=progress-indicator]]:bg-amber-500",
  failed: "[&_[data-slot=progress-indicator]]:bg-red-500",
}

export function IngestionRunsPanel({ runs }: { runs: IngestionRunSummary[] }) {
  return (
    <Card role="region" aria-label="Ingestion runs" className="rounded-md py-0" size="sm">
      <CardHeader className="border-b px-3 py-3">
        <CardTitle className="text-base">
          Ingestion runs <span className="font-normal text-muted-foreground">(latest)</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-0">
        <div className="overflow-x-auto">
          <div className="min-w-[620px] divide-y">
            {runs.length ? (
              runs.map((run) => {
                const Icon = statusIcon[run.status]
                return (
                  <div key={run.id} className="grid grid-cols-[28px_minmax(110px,1fr)_1.2fr_42px_48px_72px_28px] items-center gap-3 px-3 py-3 text-sm">
                    <Icon className={cn("size-5", statusClass[run.status])} aria-hidden="true" />
                    <div className="min-w-0">
                      <div className="truncate font-medium">{run.label}</div>
                      <div className="text-xs text-muted-foreground">{run.scope}</div>
                    </div>
                    <Progress value={run.progress} className={cn("min-w-28", progressClass[run.status])} />
                    <span className="text-right text-xs tabular-nums">{run.progress}%</span>
                    <span className="text-right text-xs tabular-nums">{run.duration}</span>
                    <span className="text-right text-xs tabular-nums">{formatNumber(run.items)} items</span>
                    <ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" />
                  </div>
                )
              })
            ) : (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">No ingestion runs yet</div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

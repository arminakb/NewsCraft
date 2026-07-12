"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Play } from "lucide-react"

import { IngestionRunsPanel } from "@/components/dashboard/ingestion-runs-panel"
import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Button } from "@/components/ui/button"
import { getIngestRuns, runIngest } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { IngestionRunSummary } from "@/lib/types"

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
      <IngestionRunsPanel runs={runs} />
    </OperationsPageFrame>
  )
}

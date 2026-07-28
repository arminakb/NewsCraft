"use client"

import { useQuery } from "@tanstack/react-query"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Button } from "@/components/ui/button"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
import { fetchOperationsDiagnostics } from "@/features/operations/api"
import { DiagnosticsDashboard } from "@/features/operations/diagnostics-dashboard"
import { getApiErrorMessage } from "@/lib/http"
import { operationsQueryKeys } from "@/lib/query-keys"

export default function Page() {
  const diagnosticsQuery = useQuery({
    queryKey: operationsQueryKeys.diagnostics,
    queryFn: fetchOperationsDiagnostics,
  })

  return (
    <OperationsPageFrame
      title="Diagnostics"
      subtitle="Inspect persisted runtime health, durable queue truth, and operator attention."
    >
      {diagnosticsQuery.isPending ? (
        <LoadingState aria-label="Loading operational diagnostics" title="Loading operational diagnostics…" />
      ) : null}
      {diagnosticsQuery.isError ? (
        <ErrorState
          dir="auto"
          title="Diagnostics unavailable"
          description={getApiErrorMessage(diagnosticsQuery.error, "Operational diagnostics could not be loaded")}
          action={<Button onClick={() => diagnosticsQuery.refetch()} size="sm" variant="outline">Retry diagnostics</Button>}
        />
      ) : null}
      {diagnosticsQuery.data ? <DiagnosticsDashboard snapshot={diagnosticsQuery.data} /> : null}
    </OperationsPageFrame>
  )
}

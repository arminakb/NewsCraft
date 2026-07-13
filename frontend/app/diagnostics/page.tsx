"use client"

import { useQuery } from "@tanstack/react-query"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Button } from "@/components/ui/button"
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
        <p aria-label="Loading operational diagnostics" className="p-6 text-center text-muted-foreground" role="status">
          Loading operational diagnostics…
        </p>
      ) : null}
      {diagnosticsQuery.isError ? (
        <div className="space-y-3 rounded-md border border-red-200 bg-red-50 p-4" dir="auto" role="alert">
          <p>{getApiErrorMessage(diagnosticsQuery.error, "Operational diagnostics could not be loaded")}</p>
          <Button onClick={() => diagnosticsQuery.refetch()} size="sm" variant="outline">
            Retry diagnostics
          </Button>
        </div>
      ) : null}
      {diagnosticsQuery.data ? <DiagnosticsDashboard snapshot={diagnosticsQuery.data} /> : null}
    </OperationsPageFrame>
  )
}

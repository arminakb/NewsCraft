"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Button } from "@/components/ui/button"
import { fetchRetentionPolicy } from "@/features/operations/api"
import { RetentionSettings } from "@/features/settings/retention-settings"
import { getApiErrorMessage } from "@/lib/http"
import { operationsQueryKeys } from "@/lib/query-keys"

export default function Page() {
  const queryClient = useQueryClient()
  const policyQuery = useQuery({
    queryKey: operationsQueryKeys.retentionPolicy,
    queryFn: fetchRetentionPolicy,
  })

  return (
    <OperationsPageFrame
      title="Retention"
      subtitle="Preview and confirm bounded cleanup without exposing or submitting client-selected record IDs."
    >
      {policyQuery.isPending ? (
        <p aria-label="Loading retention settings" className="p-6 text-center text-muted-foreground" role="status">
          Loading retention settings…
        </p>
      ) : null}
      {policyQuery.isError ? (
        <div className="space-y-3 rounded-md border border-red-200 bg-red-50 p-4">
          <DirectionBoundary as="div" className="text-red-700" direction="auto" role="alert">
            {getApiErrorMessage(policyQuery.error, "Retention settings could not be loaded")}
          </DirectionBoundary>
          <Button onClick={() => void policyQuery.refetch()} size="sm" variant="outline">
            Retry retention settings
          </Button>
        </div>
      ) : null}
      {policyQuery.data ? (
        <RetentionSettings
          onPolicySaved={(policy) => {
            queryClient.setQueryData(operationsQueryKeys.retentionPolicy, policy)
          }}
          policy={policyQuery.data}
        />
      ) : null}
    </OperationsPageFrame>
  )
}

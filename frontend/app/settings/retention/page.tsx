"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Button } from "@/components/ui/button"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
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
        <LoadingState aria-label="Loading retention settings" title="Loading retention settings…" />
      ) : null}
      {policyQuery.isError ? (
        <ErrorState
          dir="auto"
          title="Retention settings unavailable"
          description={getApiErrorMessage(policyQuery.error, "Retention settings could not be loaded")}
          action={<Button onClick={() => void policyQuery.refetch()} size="sm" variant="outline">Retry retention settings</Button>}
        />
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

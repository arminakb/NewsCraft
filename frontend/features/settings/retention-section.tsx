"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
import { fetchRetentionPolicy } from "@/features/operations/api"
import { getApiErrorMessage } from "@/lib/http"
import { operationsQueryKeys } from "@/lib/query-keys"
import { SettingsSection } from "./content-settings-primitives"
import { RetentionSettings } from "./retention-settings"

export function RetentionSection() {
  const queryClient = useQueryClient()
  const policyQuery = useQuery({
    queryKey: operationsQueryKeys.retentionPolicy,
    queryFn: fetchRetentionPolicy,
  })

  return (
    <SettingsSection
      id="retention"
      icon={Trash2}
      title="Retention"
      description="Control how long operational payloads, jobs, attempts, exports, and unreferenced media remain available before bounded cleanup."
    >
      {policyQuery.isPending ? (
        <LoadingState aria-label="Loading retention settings" title="Loading retention settings…" />
      ) : null}
      {policyQuery.isError ? (
        <ErrorState
          dir="auto"
          title="Retention settings unavailable"
          description={getApiErrorMessage(policyQuery.error, "Retention settings could not be loaded")}
          action={
            <Button onClick={() => void policyQuery.refetch()} size="sm" variant="outline">
              Retry retention settings
            </Button>
          }
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
    </SettingsSection>
  )
}

"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Pause, Play, ShieldCheck } from "lucide-react"
import { useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getAutomationControl, updateAutomationControl } from "@/features/control/api"
import type { AutomationControl, AutomationControlPatch } from "@/features/control/types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function GlobalControls() {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [outcome, setOutcome] = useState<string | null>(null)
  const controlQuery = useQuery({
    queryKey: queryKeys.automationControl,
    queryFn: getAutomationControl,
  })
  const mutation = useMutation({
    mutationFn: (patch: AutomationControlPatch) => updateAutomationControl(patch),
    onSuccess: async (control) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.automationControl }),
        queryClient.invalidateQueries({ queryKey: queryKeys.jobSummary }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ])
      queryClient.setQueryData(queryKeys.automationControl, control)
      const title = control.globalPause
        ? "Automation paused"
        : control.dryRun
          ? "Dry run enabled"
          : "Automation controls updated"
      setOutcome(`${title} at ${formatOutcomeTime(control.updatedAt)}`)
      pushNotice({ tone: "success", title, message: "The persisted control state was updated." })
    },
    onError: (error) => {
      pushNotice({ tone: "error", title: "Control update failed", message: getApiErrorMessage(error) })
    },
  })

  const runMutation = (patch: AutomationControlPatch) => {
    setOutcome(null)
    mutation.mutate(patch)
  }

  if (controlQuery.isPending) {
    return (
      <Card size="sm">
        <CardContent role="status" aria-label="Checking automation controls" className="p-4 text-muted-foreground">
          Checking automation controls
        </CardContent>
      </Card>
    )
  }

  if (controlQuery.isError || !controlQuery.data) {
    return (
      <Card size="sm">
        <CardContent className="space-y-3 p-4">
          <div role="alert" dir="auto" className="text-red-700 dark:text-red-300">
            {getApiErrorMessage(controlQuery.error, "Automation control request failed")}
          </div>
          <Button variant="outline" onClick={() => void controlQuery.refetch()}>
            Retry controls
          </Button>
        </CardContent>
      </Card>
    )
  }

  const control = controlQuery.data
  return (
    <Card size="sm" aria-label="Automation controls">
      <CardHeader className="border-b">
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-4" aria-hidden="true" />
          Automation controls
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant={control.globalPause ? "default" : "outline"}
            disabled={mutation.isPending}
            onClick={() =>
              runMutation(
                control.globalPause
                  ? { globalPause: false }
                  : { globalPause: true, pauseReason: "Paused from Newsroom" }
              )
            }
          >
            {control.globalPause ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}
            {control.globalPause ? "Resume automations" : "Pause automations"}
          </Button>
          <label className="inline-flex min-h-11 items-center gap-2 rounded-md border px-3">
            <input
              type="checkbox"
              role="switch"
              aria-label={`Dry run is ${control.dryRun ? "on" : "off"}`}
              checked={control.dryRun}
              disabled={mutation.isPending}
              onChange={() => runMutation({ dryRun: !control.dryRun })}
            />
            Dry run
          </label>
          <span className={control.globalPause ? "text-amber-700 dark:text-amber-300" : "text-emerald-700 dark:text-emerald-300"}>
            {control.globalPause ? control.pauseReason ?? "Paused" : "Active"}
          </span>
        </div>
        {mutation.isError ? (
          <div role="alert" dir="auto" className="text-sm text-red-700 dark:text-red-300">
            {getApiErrorMessage(mutation.error, "Automation control update failed")}
          </div>
        ) : null}
        {outcome ? (
          <div role="status" aria-label="Latest control outcome" className="text-sm text-muted-foreground">
            {outcome}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function formatOutcomeTime(value: string) {
  const match = value.match(/T(\d{2}:\d{2}:\d{2})/)
  return match?.[1] ?? value
}

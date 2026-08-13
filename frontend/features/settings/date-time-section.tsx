"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Clock3 } from "lucide-react"
import { useEffect, useId, useMemo, useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
import {
  getDateTimeSettings,
  updateDateTimeSettings,
} from "@/features/settings/date-time-api"
import {
  DEFAULT_TIME_ZONE,
  getSupportedTimeZones,
  isValidTimeZone,
  timeZoneLabel,
} from "@/lib/date-time"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

import { SettingsSection } from "./content-settings-primitives"

export function DateTimeSection() {
  const queryClient = useQueryClient()
  const inputId = useId()
  const listId = `${inputId}-timezones`
  const options = useMemo(getSupportedTimeZones, [])
  const query = useQuery({
    queryKey: queryKeys.dateTimeSettings,
    queryFn: getDateTimeSettings,
  })
  const [draft, setDraft] = useState(DEFAULT_TIME_ZONE)
  const [touched, setTouched] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const savedTimezone = query.data?.timezone ?? DEFAULT_TIME_ZONE
  const valid = isValidTimeZone(draft)
  const dirty = draft !== savedTimezone
  const changed = valid && dirty
  useDirtyNavigation(dirty, "Discard unsaved Date & Time changes?")

  useEffect(() => {
    setDraft(query.data?.timezone ?? DEFAULT_TIME_ZONE)
    setTouched(false)
  }, [query.data?.timezone])

  const mutation = useMutation({
    mutationFn: updateDateTimeSettings,
    onMutate: () => {
      setSuccess(null)
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.dateTimeSettings, saved)
      setDraft(saved.timezone)
      setTouched(false)
      setSuccess(`Timezone saved as ${timeZoneLabel(saved.timezone)}.`)
    },
  })

  return (
    <SettingsSection
      id="date-time"
      icon={Clock3}
      title="Date & Time"
      description="Choose the IANA timezone used for every operator-facing timestamp and local scheduling field. Canonical records remain stored in UTC."
    >
      {query.isPending ? (
        <LoadingState aria-label="Loading Date & Time settings" title="Loading Date & Time settings…" />
      ) : null}
      {query.isError ? (
        <ErrorState
          dir="auto"
          title="Date & Time settings unavailable"
          description={getApiErrorMessage(query.error, "Date & Time settings could not be loaded")}
          action={
            <Button onClick={() => void query.refetch()} size="sm" variant="outline">
              Retry Date & Time settings
            </Button>
          }
        />
      ) : null}
      {query.data ? (
        <div className="max-w-2xl space-y-4 rounded-md border bg-card p-4">
          <div className="space-y-1.5">
            <label className="block font-medium" htmlFor={inputId}>
              Application timezone
            </label>
            <Input
              aria-describedby={`${inputId}-help${touched && !valid ? ` ${inputId}-error` : ""}`}
              aria-invalid={touched && !valid}
              autoComplete="off"
              disabled={mutation.isPending}
              id={inputId}
              list={listId}
              onBlur={() => setTouched(true)}
              onChange={(event) => {
                setDraft(event.target.value)
                setTouched(true)
                setSuccess(null)
                mutation.reset()
              }}
              placeholder="Search IANA timezones…"
              spellCheck={false}
              value={draft}
            />
            <datalist id={listId}>
              {options.map((timezone) => (
                <option key={timezone} value={timezone}>{timeZoneLabel(timezone)}</option>
              ))}
            </datalist>
            <p className="text-xs text-muted-foreground" id={`${inputId}-help`}>
              Search by region or city, then save a valid identifier such as Asia/Tehran.
            </p>
            {touched && !valid ? (
              <p className="text-xs text-destructive" id={`${inputId}-error`} role="alert">
                Select a valid IANA timezone identifier.
              </p>
            ) : null}
            {valid ? (
              <p className="text-sm font-medium" aria-live="polite">
                {timeZoneLabel(draft)}
              </p>
            ) : null}
          </div>

          <Button
            disabled={!changed || mutation.isPending}
            onClick={() => mutation.mutate(draft)}
            type="button"
          >
            {mutation.isPending ? "Saving timezone…" : "Save timezone"}
          </Button>

          {success ? (
            <Alert role="status" tone="success">
              <AlertDescription>{success}</AlertDescription>
            </Alert>
          ) : null}
          {mutation.isError ? (
            <Alert dir="auto" role="alert" tone="error">
              <AlertDescription>
                {getApiErrorMessage(mutation.error, "Timezone could not be saved")}
              </AlertDescription>
            </Alert>
          ) : null}
        </div>
      ) : null}
    </SettingsSection>
  )
}

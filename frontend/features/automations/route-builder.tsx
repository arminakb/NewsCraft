"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { PageHeader } from "@/components/ui/page-header"
import { Select } from "@/components/ui/select"
import { LoadingState } from "@/components/ui/state-panel"
import {
  createTelegramRoute,
  createTelegramSource,
  getTelegramAutomationOptions,
} from "@/features/automations/telegram-api"
import type { TelegramRouteInput } from "@/features/automations/telegram-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

type FormState = {
  name: string
  sourceName: string
  channelRef: string
  accessMode: "public_html" | "mtproto_user"
  apiIdRef: string
  apiHashRef: string
  sessionRef: string
  destinationId: string
  brandProfileId: string
  promptPolicy: "" | "pinned" | "follow_active"
  promptTemplateVersionId: string
  aiProviderProfileId: string
  researchMode: "off" | "manual" | "auto_if_incomplete"
  researchProviderProfileId: string
  mediaPolicy: "preserve" | "omit" | "replace_manually"
  publishingPolicy: "review_required" | "auto_publish"
  pollIntervalSeconds: number
  confirmAutoPublish: boolean
}

const initialForm: FormState = {
  name: "",
  sourceName: "",
  channelRef: "",
  accessMode: "public_html",
  apiIdRef: "",
  apiHashRef: "",
  sessionRef: "",
  destinationId: "",
  brandProfileId: "",
  promptPolicy: "pinned",
  promptTemplateVersionId: "",
  aiProviderProfileId: "",
  researchMode: "off",
  researchProviderProfileId: "",
  mediaPolicy: "preserve",
  publishingPolicy: "review_required",
  pollIntervalSeconds: 300,
  confirmAutoPublish: false,
}

const secretPattern = "[A-Z][A-Z0-9_]{2,127}"

export function RouteBuilder({ onCreated }: { onCreated?: (routeId: string) => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialForm)
  const [outcome, setOutcome] = useState("")
  const optionsQuery = useQuery({
    queryKey: queryKeys.telegramOptions,
    queryFn: getTelegramAutomationOptions,
  })
  const options = optionsQuery.data
  const generationProfiles = options?.aiProviderProfiles.filter((item) => item.capabilities.generation) ?? []
  const researchProfiles = options?.aiProviderProfiles.filter((item) => item.capabilities.research) ?? []
  const choose = (value: string, fallback: string | undefined) => value || fallback || ""
  const activePrompt = options?.promptTemplateVersions.find((item) => item.isActive)

  const mutation = useMutation({
    mutationFn: async () => {
      if (!form.promptPolicy) throw new Error("Choose how this route follows prompt changes.")
      const source = await createTelegramSource({
        name: form.sourceName,
        channelRef: form.channelRef,
        accessMode: form.accessMode,
        languageHint: "fa",
        ...(form.accessMode === "mtproto_user" ? {
          apiIdSecretRef: form.apiIdRef,
          apiHashSecretRef: form.apiHashRef,
          sessionSecretRef: form.sessionRef,
        } : {}),
      })
      const routeInput: TelegramRouteInput = {
        name: form.name,
        sourceId: source.id,
        destinationId: choose(form.destinationId, options?.destinations[0]?.id),
        brandProfileId: choose(form.brandProfileId, options?.brandProfiles[0]?.id),
        promptTemplateVersionId: form.promptPolicy === "follow_active"
          ? (activePrompt?.id ?? "")
          : choose(form.promptTemplateVersionId, options?.promptTemplateVersions[0]?.id),
        promptPolicy: form.promptPolicy,
        aiProviderProfileId: choose(form.aiProviderProfileId, generationProfiles[0]?.id),
        accessMode: form.accessMode,
        researchMode: form.researchMode,
        contentFilters: { includeTerms: [], excludeTerms: [], minTextCharacters: 1, requireMedia: false, ...(form.researchMode === "off" ? {} : { researchProviderProfileId: choose(form.researchProviderProfileId, researchProfiles[0]?.id) }) },
        mediaPolicy: form.mediaPolicy,
        attributionPolicy: "preserve",
        customFooter: null,
        publishingPolicy: form.publishingPolicy,
        pollIntervalSeconds: form.pollIntervalSeconds,
        quietHours: null,
        retryPolicy: { maxAttempts: 3, baseDelaySeconds: 30, maxDelaySeconds: 1800 },
        confirmAutoPublish: form.confirmAutoPublish,
      }
      const route = await createTelegramRoute(routeInput)
      return route
    },
    onSuccess: async (route) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramSources }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramRoutes, exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      setOutcome("Automation created. Activate it after the owning workers report current capability status.")
      onCreated?.(route.id)
    },
  })

  const autoUnconfirmed = form.publishingPolicy === "auto_publish" && !form.confirmAutoPublish
  const mtprotoIncomplete = form.accessMode === "mtproto_user" && !(form.apiIdRef && form.apiHashRef && form.sessionRef)
  const optionsIncomplete = !options?.destinations.length || !options.brandProfiles.length || !options.promptTemplateVersions.length || !generationProfiles.length
  const researchProfileMissing = form.researchMode !== "off" && !choose(form.researchProviderProfileId, researchProfiles[0]?.id)
  const promptPolicyMissing = !form.promptPolicy || (form.promptPolicy === "follow_active" && !activePrompt)

  return (
    <section className="nc-page mx-auto w-full max-w-4xl" aria-labelledby="route-builder-heading">
      <PageHeader
        title="New Telegram automation"
        titleId="route-builder-heading"
        description="Connect a source and destination with conservative, review-first defaults."
      />
      <ol aria-label="Automation setup steps" className="grid gap-2 text-sm sm:grid-cols-3">
        <li className="nc-panel p-3"><strong className="text-[13px]">1. Source</strong><br /><span className="text-xs text-muted-foreground">Name the route and Telegram channel.</span></li>
        <li className="nc-panel p-3"><strong className="text-[13px]">2. Destination</strong><br /><span className="text-xs text-muted-foreground">Choose a verified newsroom destination.</span></li>
        <li className="nc-panel p-3"><strong className="text-[13px]">3. Review policy</strong><br /><span className="text-xs text-muted-foreground">Confirm how drafts reach editors.</span></li>
      </ol>
      {optionsQuery.isPending ? <LoadingState title="Loading safe configuration options…" /> : null}
      {optionsQuery.isError ? (
        <Alert tone="error" role="alert" dir="auto">
          <div>
            <AlertTitle>Configuration options unavailable</AlertTitle>
            <AlertDescription>{getApiErrorMessage(optionsQuery.error)}</AlertDescription>
          </div>
        </Alert>
      ) : null}
      {options ? (
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setOutcome(""); mutation.mutate() }}>
          <Card>
            <CardHeader><CardTitle>Steps 1–2 · Source and destination</CardTitle></CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <Field label="Automation name" required><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Source name" required><Input required value={form.sourceName} onChange={(e) => setForm({ ...form, sourceName: e.target.value })} /></Field>
              <Field label="Source channel" required><Input required value={form.channelRef} onChange={(e) => setForm({ ...form, channelRef: e.target.value })} /></Field>
              <details className="rounded-lg border p-3 md:col-span-2">
                <summary className="cursor-pointer font-medium">Advanced source access</summary>
                <div className="mt-4 grid gap-4 md:grid-cols-2">
                  <Field label="Access mode">
                    <Select value={form.accessMode} onChange={(e) => setForm({ ...form, accessMode: e.target.value as FormState["accessMode"] })}>
                      <option value="public_html">Public HTML</option><option value="mtproto_user">MTProto user session</option>
                    </Select>
                  </Field>
                  {form.accessMode === "mtproto_user" ? (
                    <div className="grid gap-4 md:col-span-2 md:grid-cols-3">
                      <EnvironmentField label="API ID environment variable" value={form.apiIdRef} onChange={(apiIdRef) => setForm({ ...form, apiIdRef })} />
                      <EnvironmentField label="API hash environment variable" value={form.apiHashRef} onChange={(apiHashRef) => setForm({ ...form, apiHashRef })} />
                      <EnvironmentField label="Session environment variable" value={form.sessionRef} onChange={(sessionRef) => setForm({ ...form, sessionRef })} />
                    </div>
                  ) : null}
                </div>
              </details>
              <div className="grid gap-2 md:col-span-2">
                <Field label="Telegram destination">
                  <Select
                    required
                    value={choose(form.destinationId, options.destinations[0]?.id)}
                    onChange={(event) => setForm({ ...form, destinationId: event.target.value })}
                  >
                    {options.destinations.length ? null : <option value="">No ready destinations</option>}
                    {options.destinations.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </Select>
                </Field>
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
                  <span>
                    {options.destinations.length
                      ? "Only enabled, healthy destinations with administrator access are available."
                      : "Create and verify a destination before building an automation."}
                  </span>
                  <Link
                    className={buttonVariants({ variant: "outline", size: "sm" })}
                    href="/settings/content#telegram-destinations"
                  >
                    Manage destinations
                  </Link>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Step 3 · Review policy</CardTitle></CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <Field label="Brand"><Select value={choose(form.brandProfileId, options.brandProfiles[0]?.id)} onChange={(e) => setForm({ ...form, brandProfileId: e.target.value })}>{options.brandProfiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Field>
              <Field label="Prompt update policy">
                <Select required value={form.promptPolicy} onChange={(e) => setForm({ ...form, promptPolicy: e.target.value as FormState["promptPolicy"], promptTemplateVersionId: "" })}>
                  <option value="">Choose a policy</option>
                  <option value="follow_active">Follow active prompt</option>
                  <option value="pinned">Pin one immutable version</option>
                </Select>
              </Field>
              <Field label="Prompt version">
                <Select
                  disabled={form.promptPolicy !== "pinned"}
                  value={form.promptPolicy === "follow_active" ? (activePrompt?.id ?? "") : choose(form.promptTemplateVersionId, options.promptTemplateVersions[0]?.id)}
                  onChange={(e) => setForm({ ...form, promptTemplateVersionId: e.target.value })}
                >
                  {options.promptTemplateVersions.map((item) => <option key={item.id} value={item.id}>Prompt version {item.version}{item.isActive ? " · active" : ""}</option>)}
                </Select>
                <span className="text-xs font-normal text-muted-foreground">
                  {form.promptPolicy === "follow_active"
                    ? "Each new job resolves the active version once and stores its exact checksum."
                    : form.promptPolicy === "pinned"
                      ? "Jobs keep using this version after another version becomes active."
                      : "Choose whether future jobs follow activations or remain pinned."}
                </span>
              </Field>
              <Field label="AI provider"><Select value={choose(form.aiProviderProfileId, generationProfiles[0]?.id)} onChange={(e) => setForm({ ...form, aiProviderProfileId: e.target.value })}>{generationProfiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Field>
              <Field label="Research mode"><Select value={form.researchMode} onChange={(e) => setForm({ ...form, researchMode: e.target.value as FormState["researchMode"], researchProviderProfileId: e.target.value === "off" ? "" : form.researchProviderProfileId })}><option value="off">Off</option><option value="manual">Manual</option><option value="auto_if_incomplete">Automatic if incomplete</option></Select></Field>
              {form.researchMode !== "off" ? <Field label="Research provider"><Select value={choose(form.researchProviderProfileId, researchProfiles[0]?.id)} onChange={(e) => setForm({ ...form, researchProviderProfileId: e.target.value })}><option value="">Select an available research profile</option>{researchProfiles.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.defaultModel ?? "default model"}</option>)}</Select></Field> : null}
              <Field label="Media policy"><Select value={form.mediaPolicy} onChange={(e) => setForm({ ...form, mediaPolicy: e.target.value as FormState["mediaPolicy"] })}><option value="preserve">Preserve</option><option value="omit">Omit</option><option value="replace_manually">Replace manually</option></Select></Field>
              <Field label="Publishing policy"><Select value={form.publishingPolicy} onChange={(e) => setForm({ ...form, publishingPolicy: e.target.value as FormState["publishingPolicy"], confirmAutoPublish: false })}><option value="review_required">Review required</option><option value="auto_publish">Automatic publish</option></Select></Field>
              <details className="rounded-lg border p-3 md:col-span-2">
                <summary className="cursor-pointer font-medium">Advanced timing</summary>
                <div className="mt-4 max-w-sm">
                  <Field label="Poll interval in seconds" required><Input required min={60} max={86400} type="number" value={form.pollIntervalSeconds} onChange={(e) => setForm({ ...form, pollIntervalSeconds: Number(e.target.value) })} /></Field>
                </div>
              </details>
              {form.publishingPolicy === "auto_publish" ? (
                <label className="flex min-h-11 items-start gap-2 rounded-lg border border-warning/30 bg-[var(--warning-surface)] p-3 md:col-span-2"><Checkbox className="mt-0.5" checked={form.confirmAutoPublish} onChange={(e) => setForm({ ...form, confirmAutoPublish: e.target.checked })} /><span><strong>Confirm automatic publishing</strong><br /><span className="text-sm text-muted-foreground">Approved content can be sent without another operator action.</span></span></label>
              ) : null}
            </CardContent>
          </Card>
          {mutation.isError ? <Alert tone="error" role="alert" dir="auto"><AlertDescription>{getApiErrorMessage(mutation.error)}</AlertDescription></Alert> : null}
          {outcome ? <Alert tone="success" role="status" aria-label="Automation creation outcome"><AlertDescription>{outcome}</AlertDescription></Alert> : null}
          <Button size="lg" type="submit" disabled={mutation.isPending || autoUnconfirmed || mtprotoIncomplete || optionsIncomplete || researchProfileMissing || promptPolicyMissing}>{mutation.isPending ? "Creating" : "Create automation"}</Button>
        </form>
      ) : null}
    </section>
  )
}

function Field({ label, required = false, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return <label className="grid min-w-0 gap-1.5 text-sm font-medium"><span className={required ? "after:ms-1 after:text-destructive after:content-['*']" : undefined}>{label}</span>{children}</label>
}

function EnvironmentField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <Field label={label} required><span className="text-xs font-normal text-muted-foreground">Environment variable name</span><Input aria-label={label} required pattern={secretPattern} autoComplete="off" value={value} onChange={(e) => onChange(e.target.value)} /></Field>
}

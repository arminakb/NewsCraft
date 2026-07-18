"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  createTelegramDestination,
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
  destinationName: string
  targetRef: string
  botTokenRef: string
  brandProfileId: string
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
  destinationName: "",
  targetRef: "",
  botTokenRef: "",
  brandProfileId: "",
  promptTemplateVersionId: "",
  aiProviderProfileId: "",
  researchMode: "off",
  researchProviderProfileId: "",
  mediaPolicy: "preserve",
  publishingPolicy: "review_required",
  pollIntervalSeconds: 300,
  confirmAutoPublish: false,
}

const fieldClass = "h-10 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-sm"
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

  const mutation = useMutation({
    mutationFn: async () => {
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
      const destinationResult = await createTelegramDestination({
        name: form.destinationName,
        targetRef: form.targetRef,
        secretRef: form.botTokenRef,
        allowAutoPublish: form.publishingPolicy === "auto_publish",
      })
      const destination = destinationResult.destination
      const routeInput: TelegramRouteInput = {
        name: form.name,
        sourceId: source.id,
        destinationId: destination.id,
        brandProfileId: choose(form.brandProfileId, options?.brandProfiles[0]?.id),
        promptTemplateVersionId: choose(form.promptTemplateVersionId, options?.promptTemplateVersions[0]?.id),
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
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramDestinations }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramRoutes, exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      setOutcome("Automation created. Activate it after the owning workers report current capability status.")
      onCreated?.(route.id)
    },
  })

  const autoUnconfirmed = form.publishingPolicy === "auto_publish" && !form.confirmAutoPublish
  const mtprotoIncomplete = form.accessMode === "mtproto_user" && !(form.apiIdRef && form.apiHashRef && form.sessionRef)
  const optionsIncomplete = !options?.brandProfiles.length || !options.promptTemplateVersions.length || !generationProfiles.length
  const researchProfileMissing = form.researchMode !== "off" && !choose(form.researchProviderProfileId, researchProfiles[0]?.id)

  return (
    <section className="mx-auto w-full max-w-4xl space-y-4 p-4 md:p-6" aria-labelledby="route-builder-heading">
      <div>
        <h1 id="route-builder-heading" className="text-2xl font-semibold">New Telegram automation</h1>
        <p className="text-muted-foreground">Connect a source and destination with review-first newsroom defaults.</p>
      </div>
      {optionsQuery.isPending ? <div role="status">Loading safe configuration options</div> : null}
      {optionsQuery.isError ? <div role="alert" dir="auto">{getApiErrorMessage(optionsQuery.error)}</div> : null}
      {options ? (
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setOutcome(""); mutation.mutate() }}>
          <Card>
            <CardHeader><CardTitle>Source and destination</CardTitle></CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <Field label="Automation name"><input required className={fieldClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Source name"><input required className={fieldClass} value={form.sourceName} onChange={(e) => setForm({ ...form, sourceName: e.target.value })} /></Field>
              <Field label="Source channel"><input required className={fieldClass} value={form.channelRef} onChange={(e) => setForm({ ...form, channelRef: e.target.value })} /></Field>
              <Field label="Access mode">
                <select className={fieldClass} value={form.accessMode} onChange={(e) => setForm({ ...form, accessMode: e.target.value as FormState["accessMode"] })}>
                  <option value="public_html">Public HTML</option><option value="mtproto_user">MTProto user session</option>
                </select>
              </Field>
              {form.accessMode === "mtproto_user" ? (
                <div className="grid gap-4 md:col-span-2 md:grid-cols-3">
                  <EnvironmentField label="API ID environment variable" value={form.apiIdRef} onChange={(apiIdRef) => setForm({ ...form, apiIdRef })} />
                  <EnvironmentField label="API hash environment variable" value={form.apiHashRef} onChange={(apiHashRef) => setForm({ ...form, apiHashRef })} />
                  <EnvironmentField label="Session environment variable" value={form.sessionRef} onChange={(sessionRef) => setForm({ ...form, sessionRef })} />
                </div>
              ) : null}
              <Field label="Destination name"><input required className={fieldClass} value={form.destinationName} onChange={(e) => setForm({ ...form, destinationName: e.target.value })} /></Field>
              <Field label="Destination target"><input required className={fieldClass} value={form.targetRef} onChange={(e) => setForm({ ...form, targetRef: e.target.value })} /></Field>
              <EnvironmentField label="Bot token environment variable" value={form.botTokenRef} onChange={(botTokenRef) => setForm({ ...form, botTokenRef })} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Editorial policy</CardTitle></CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <Field label="Brand"><select className={fieldClass} value={choose(form.brandProfileId, options.brandProfiles[0]?.id)} onChange={(e) => setForm({ ...form, brandProfileId: e.target.value })}>{options.brandProfiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
              <Field label="Prompt version"><select className={fieldClass} value={choose(form.promptTemplateVersionId, options.promptTemplateVersions[0]?.id)} onChange={(e) => setForm({ ...form, promptTemplateVersionId: e.target.value })}>{options.promptTemplateVersions.map((item) => <option key={item.id} value={item.id}>Prompt version {item.version}</option>)}</select></Field>
              <Field label="AI provider"><select className={fieldClass} value={choose(form.aiProviderProfileId, generationProfiles[0]?.id)} onChange={(e) => setForm({ ...form, aiProviderProfileId: e.target.value })}>{generationProfiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
              <Field label="Research mode"><select className={fieldClass} value={form.researchMode} onChange={(e) => setForm({ ...form, researchMode: e.target.value as FormState["researchMode"], researchProviderProfileId: e.target.value === "off" ? "" : form.researchProviderProfileId })}><option value="off">Off</option><option value="manual">Manual</option><option value="auto_if_incomplete">Automatic if incomplete</option></select></Field>
              {form.researchMode !== "off" ? <Field label="Research provider"><select className={fieldClass} value={choose(form.researchProviderProfileId, researchProfiles[0]?.id)} onChange={(e) => setForm({ ...form, researchProviderProfileId: e.target.value })}><option value="">Select an available research profile</option>{researchProfiles.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.providerType} · {item.defaultModel ?? "default model"}</option>)}</select></Field> : null}
              <Field label="Media policy"><select className={fieldClass} value={form.mediaPolicy} onChange={(e) => setForm({ ...form, mediaPolicy: e.target.value as FormState["mediaPolicy"] })}><option value="preserve">Preserve</option><option value="omit">Omit</option><option value="replace_manually">Replace manually</option></select></Field>
              <Field label="Publishing policy"><select className={fieldClass} value={form.publishingPolicy} onChange={(e) => setForm({ ...form, publishingPolicy: e.target.value as FormState["publishingPolicy"], confirmAutoPublish: false })}><option value="review_required">Review required</option><option value="auto_publish">Automatic publish</option></select></Field>
              <Field label="Poll interval in seconds"><input required min={60} max={86400} type="number" className={fieldClass} value={form.pollIntervalSeconds} onChange={(e) => setForm({ ...form, pollIntervalSeconds: Number(e.target.value) })} /></Field>
              {form.publishingPolicy === "auto_publish" ? (
                <label className="flex items-start gap-2 md:col-span-2"><input type="checkbox" className="mt-1" checked={form.confirmAutoPublish} onChange={(e) => setForm({ ...form, confirmAutoPublish: e.target.checked })} /><span><strong>Confirm automatic publishing</strong><br /><span className="text-muted-foreground">Approved content can be sent without another operator action.</span></span></label>
              ) : null}
            </CardContent>
          </Card>
          {mutation.isError ? <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(mutation.error)}</div> : null}
          {outcome ? <div role="status" aria-label="Automation creation outcome" className="text-green-700">{outcome}</div> : null}
          <Button size="lg" type="submit" disabled={mutation.isPending || autoUnconfirmed || mtprotoIncomplete || optionsIncomplete || researchProfileMissing}>{mutation.isPending ? "Creating" : "Create automation"}</Button>
        </form>
      ) : null}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="grid min-w-0 gap-1.5 text-sm font-medium"><span>{label}</span>{children}</label>
}

function EnvironmentField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <Field label={label}><span className="text-xs font-normal text-muted-foreground">Environment variable name</span><input aria-label={label} required className={fieldClass} pattern={secretPattern} autoComplete="off" value={value} onChange={(e) => onChange(e.target.value)} /></Field>
}

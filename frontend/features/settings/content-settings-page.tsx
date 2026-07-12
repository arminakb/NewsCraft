"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  activatePromptVersion,
  createAIProviderProfile,
  createBrandProfile,
  createPromptTemplate,
  createPromptVersion,
  createTelegramDestination,
  getAIProviderProfiles,
  getBrandProfiles,
  getPromptTemplates,
  getPromptVersions,
  getTelegramDestinations,
  updateAIProviderProfile,
  updateBrandProfile,
} from "@/features/automations/telegram-api"
import type { AIProviderProfile, BrandProfile } from "@/features/automations/telegram-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

const telegramPromptBody = [
  "Source text: {source_text}",
  "Source URL: {source_url}",
  "Source channel: {source_channel}",
  "Language: {language}",
  "Direction: {direction}",
  "Attribution policy: {attribution_policy}",
  "Footer: {custom_footer}",
].join("\n")
const requiredTelegramPlaceholders = [
  "source_text",
  "source_url",
  "source_channel",
  "language",
  "direction",
  "attribution_policy",
  "custom_footer",
] as const
const environmentNamePattern = "[A-Z][A-Z0-9_]{2,127}"
const environmentNameRegex = /^[A-Z][A-Z0-9_]{2,127}$/

const fieldClass = "min-h-10 w-full rounded-lg border bg-background px-3 py-2"

export function ContentSettingsPage() {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const brands = useQuery({ queryKey: queryKeys.brandProfiles, queryFn: getBrandProfiles })
  const templates = useQuery({ queryKey: queryKeys.promptTemplates, queryFn: getPromptTemplates })
  const providers = useQuery({ queryKey: queryKeys.aiProviderProfiles, queryFn: getAIProviderProfiles })
  const destinations = useQuery({ queryKey: queryKeys.telegramDestinations, queryFn: getTelegramDestinations })
  const telegramTemplate = templates.data?.find((item) => item.purposeKey === "telegram_rewrite")
  const versions = useQuery({
    queryKey: telegramTemplate ? queryKeys.promptVersions(telegramTemplate.id) : ["prompt-versions", "none"],
    queryFn: () => getPromptVersions(telegramTemplate!.id),
    enabled: Boolean(telegramTemplate),
  })

  const [brandName, setBrandName] = useState("")
  const [instructions, setInstructions] = useState("Rewrite faithfully using only verified evidence")
  const [userTemplate, setUserTemplate] = useState(telegramPromptBody)
  const [activationConfirmed, setActivationConfirmed] = useState(false)
  const [providerName, setProviderName] = useState("")
  const [providerModel, setProviderModel] = useState("openai/gpt-5-mini")
  const [providerEnv, setProviderEnv] = useState("")
  const [destinationName, setDestinationName] = useState("")
  const [targetRef, setTargetRef] = useState("")
  const [destinationEnv, setDestinationEnv] = useState("")
  const [allowAutoPublish, setAllowAutoPublish] = useState(false)

  const fail = (title: string) => (error: unknown) =>
    pushNotice({ tone: "error", title, message: getApiErrorMessage(error) })

  const createBrand = useMutation({
    mutationFn: () =>
      createBrandProfile({
        name: brandName.trim(),
        outputLanguage: "fa",
        tone: "neutral",
        editorialRules: [],
        attributionRules: {},
        defaultHashtags: [],
        platformPreferences: {},
        isDefault: false,
      }),
    onSuccess: async () => {
      setBrandName("")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.brandProfiles }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      pushNotice({ tone: "success", title: "Brand created", message: "The brand profile is now available." })
    },
    onError: fail("Brand creation failed"),
  })
  const createTemplate = useMutation({
    mutationFn: () =>
      createPromptTemplate({ purposeKey: "telegram_rewrite", name: "Telegram rewrite", description: "Telegram newsroom rewrite" }),
    onSuccess: async () => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.promptTemplates }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
    ]) },
    onError: fail("Prompt initialization failed"),
  })
  const addVersion = useMutation({
    mutationFn: () => createPromptVersion(telegramTemplate!.id, { systemTemplate: instructions, userTemplate }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.promptVersions(telegramTemplate!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      pushNotice({ tone: "success", title: "Prompt version created", message: "The immutable version is inactive until confirmed." })
    },
    onError: fail("Prompt version creation failed"),
  })
  const activate = useMutation({
    mutationFn: (versionId: string) => activatePromptVersion(versionId),
    onSuccess: async () => {
      setActivationConfirmed(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.promptVersions(telegramTemplate!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      pushNotice({ tone: "success", title: "Prompt activated", message: "New jobs will use the selected exact version." })
    },
    onError: fail("Prompt activation failed"),
  })
  const createProvider = useMutation({
    mutationFn: () =>
      createAIProviderProfile({
        name: providerName.trim(),
        providerType: "openrouter",
        defaultModel: providerModel.trim() || null,
        secretRef: providerEnv.trim(),
        settings: {},
        enabled: true,
      }),
    onSuccess: async () => {
      setProviderEnv("")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.aiProviderProfiles }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      pushNotice({ tone: "success", title: "Provider saved", message: "Only configuration availability is displayed." })
    },
    onError: fail("Provider creation failed"),
  })
  const createDestination = useMutation({
    mutationFn: () =>
      createTelegramDestination({
        name: destinationName.trim(),
        targetRef: targetRef.trim(),
        secretRef: destinationEnv.trim(),
        allowAutoPublish,
      }),
    onSuccess: async () => {
      setDestinationEnv("")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramDestinations }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      pushNotice({ tone: "success", title: "Destination accepted", message: "Health will reflect the backend check." })
    },
    onError: fail("Destination creation failed"),
  })

  const queries = [brands, templates, providers, destinations]
  const missingPlaceholders = requiredTelegramPlaceholders.filter(
    (placeholder) => !userTemplate.includes(`{${placeholder}}`)
  )
  if (queries.some((query) => query.isPending)) {
    return <main className="p-4 md:p-6" role="status" aria-label="Loading content settings">Loading content settings</main>
  }
  const queryError = queries.find((query) => query.isError)?.error
  if (queryError) {
    return (
      <main className="space-y-3 p-4 md:p-6">
        <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(queryError, "Content settings request failed")}</div>
        <Button variant="outline" onClick={() => void Promise.all(queries.map((query) => query.refetch()))}>Retry settings</Button>
      </main>
    )
  }

  return (
    <main className="min-w-0 space-y-6 p-4 md:p-6" aria-labelledby="content-settings-heading">
      <header>
        <h1 id="content-settings-heading" className="text-2xl font-semibold">Content settings</h1>
        <p className="text-muted-foreground">Manage live editorial configuration without exposing credential values or secret references.</p>
      </header>

      <section className="grid min-w-0 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Brands</CardTitle><CardDescription>Reusable editorial voice and language profiles.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            <form className="grid gap-3 sm:grid-cols-[1fr_auto]" onSubmit={(event) => { event.preventDefault(); createBrand.mutate() }}>
              <Field label="New brand name"><input className={fieldClass} value={brandName} onChange={(event) => setBrandName(event.target.value)} required /></Field>
              <Button className="self-end" type="submit" disabled={createBrand.isPending || !brandName.trim()}>Create brand</Button>
            </form>
            {brands.data?.length ? brands.data.map((brand) => <BrandEditor key={brand.id} brand={brand} />) : <Empty>No brand profiles configured</Empty>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Telegram prompt versions</CardTitle><CardDescription>History is read-only. Every edit creates a new immutable version.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            {!telegramTemplate ? (
              <Button onClick={() => createTemplate.mutate()} disabled={createTemplate.isPending}>Initialize Telegram prompt</Button>
            ) : (
              <>
                <div className="grid gap-3">
                  <Field label="Custom instructions"><textarea className={fieldClass} rows={3} value={instructions} onChange={(event) => setInstructions(event.target.value)} /></Field>
                  <Field label="User template"><textarea className={`${fieldClass} font-mono text-xs`} rows={9} value={userTemplate} onChange={(event) => setUserTemplate(event.target.value)} /></Field>
                  {missingPlaceholders.length ? <div role="alert" className="text-amber-800">Required placeholders missing: {missingPlaceholders.join(", ")}</div> : null}
                  <Button className="justify-self-start" onClick={() => addVersion.mutate()} disabled={addVersion.isPending || missingPlaceholders.length > 0}>Create prompt version</Button>
                </div>
                <label className="flex min-h-11 items-center gap-2 rounded-lg border p-3">
                  <input type="checkbox" checked={activationConfirmed} onChange={(event) => setActivationConfirmed(event.target.checked)} />
                  <span>Confirm prompt activation</span>
                </label>
                {versions.isPending ? <div role="status">Loading prompt history</div> : versions.isError ? <div role="alert">{getApiErrorMessage(versions.error)}</div> : versions.data?.length ? (
                  <ol className="space-y-2" aria-label="Immutable prompt history">
                    {versions.data.map((version) => (
                      <li key={version.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
                        <div className="min-w-0 flex-1">
                          <div className="font-medium">Version {version.version}</div>
                          <div className="text-xs text-muted-foreground">{version.isActive ? "Active" : "Inactive"} · {version.checksumSha256.slice(0, 12)}</div>
                          <details className="mt-2">
                            <summary className="cursor-pointer">Inspect immutable templates</summary>
                            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-2 text-xs">{version.systemTemplate}{"\n\n"}{version.userTemplate}</pre>
                          </details>
                        </div>
                        <Button variant="outline" disabled={!activationConfirmed || activate.isPending || version.isActive} onClick={() => activate.mutate(version.id)}>Activate version {version.version}</Button>
                      </li>
                    ))}
                  </ol>
                ) : <Empty>No prompt versions</Empty>}
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>AI providers</CardTitle><CardDescription>The actual API key stays in .env. Enter only its environment-variable name.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); createProvider.mutate() }}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Provider profile name"><input className={fieldClass} value={providerName} onChange={(event) => setProviderName(event.target.value)} required /></Field>
                <Field label="Default model"><input className={fieldClass} value={providerModel} onChange={(event) => setProviderModel(event.target.value)} /></Field>
              </div>
              <Field label="Provider environment variable name"><input className={fieldClass} pattern={environmentNamePattern} autoComplete="off" value={providerEnv} onChange={(event) => setProviderEnv(event.target.value)} required /></Field>
              <Button className="justify-self-start" type="submit" disabled={createProvider.isPending}>Create OpenRouter profile</Button>
            </form>
            {providers.data?.length ? providers.data.map((provider) => <ProviderEditor key={provider.id} provider={provider} />) : <Empty>No AI providers configured</Empty>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Telegram destinations</CardTitle><CardDescription>Health and auto-publish policy come directly from the backend.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); createDestination.mutate() }}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Destination name"><input className={fieldClass} value={destinationName} onChange={(event) => setDestinationName(event.target.value)} required /></Field>
                <Field label="Telegram channel reference"><input className={fieldClass} placeholder="@channel" value={targetRef} onChange={(event) => setTargetRef(event.target.value)} required /></Field>
              </div>
              <Field label="Destination environment variable name"><input className={fieldClass} pattern={environmentNamePattern} autoComplete="off" value={destinationEnv} onChange={(event) => setDestinationEnv(event.target.value)} required /></Field>
              <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={allowAutoPublish} onChange={(event) => setAllowAutoPublish(event.target.checked)} /> Allow automatic publishing</label>
              <Button className="justify-self-start" type="submit" disabled={createDestination.isPending}>Create destination</Button>
            </form>
            {destinations.data?.length ? destinations.data.map((destination) => (
              <div key={destination.id} role="group" aria-label={`Destination ${destination.name}`} className="space-y-1 rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2"><strong>{destination.name}</strong><span>{healthLabel(destination.healthStatus)}</span></div>
                <div className="text-sm text-muted-foreground">{destination.targetRef} · {destination.settings.allowAutoPublish ? "Auto-publish enabled" : "Auto-publish disabled"}</div>
                <div className="text-xs text-muted-foreground">{destination.configured ? "Configured" : "Unavailable"}</div>
              </div>
            )) : <Empty>No Telegram destinations configured</Empty>}
          </CardContent>
        </Card>
      </section>
    </main>
  )
}

function BrandEditor({ brand }: { brand: BrandProfile }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [name, setName] = useState(brand.name)
  const [tone, setTone] = useState(brand.tone)
  const mutation = useMutation({
    mutationFn: () => updateBrandProfile(brand.id, { name, tone }),
    onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.brandProfiles }), queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions })]); pushNotice({ tone: "success", title: "Brand updated", message: "The live profile was saved." }) },
    onError: (error) => pushNotice({ tone: "error", title: "Brand update failed", message: getApiErrorMessage(error) }),
  })
  return (
    <fieldset role="group" aria-label={`Brand ${brand.name}`} className="grid gap-3 rounded-lg border p-3 sm:grid-cols-[1fr_1fr_auto]">
      <Field label="Name"><input className={fieldClass} value={name} onChange={(event) => setName(event.target.value)} /></Field>
      <Field label="Tone"><input className={fieldClass} value={tone} onChange={(event) => setTone(event.target.value)} /></Field>
      <Button className="self-end" variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate()}>Save brand</Button>
    </fieldset>
  )
}

function ProviderEditor({ provider }: { provider: AIProviderProfile }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [model, setModel] = useState(provider.defaultModel ?? "")
  const [environmentName, setEnvironmentName] = useState("")
  const environmentNameIsValid = !environmentName || environmentNameRegex.test(environmentName)
  const mutation = useMutation({
    mutationFn: () => updateAIProviderProfile(provider.id, { defaultModel: model || null, ...(environmentName ? { secretRef: environmentName } : {}) }),
    onSuccess: async () => { setEnvironmentName(""); await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.aiProviderProfiles }), queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions })]); pushNotice({ tone: "success", title: "Provider updated", message: "Configuration availability was refreshed." }) },
    onError: (error) => pushNotice({ tone: "error", title: "Provider update failed", message: getApiErrorMessage(error) }),
  })
  return (
    <fieldset role="group" aria-label={`Provider ${provider.name}`} className="grid gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong>{provider.name}</strong><span>{provider.configured ? "Configured" : "Unavailable"}</span></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Provider model"><input className={fieldClass} value={model} onChange={(event) => setModel(event.target.value)} /></Field>
        <Field label="Replacement environment variable name"><input className={fieldClass} pattern={environmentNamePattern} aria-invalid={!environmentNameIsValid} aria-describedby={!environmentNameIsValid ? `provider-environment-error-${provider.id}` : undefined} autoComplete="off" value={environmentName} onChange={(event) => setEnvironmentName(event.target.value)} /></Field>
      </div>
      {!environmentNameIsValid ? <div id={`provider-environment-error-${provider.id}`} role="alert" className="text-sm text-destructive">Use 3–128 characters: start with A–Z, then only A–Z, 0–9, or underscore.</div> : null}
      <Button className="justify-self-start" variant="outline" disabled={mutation.isPending || !environmentNameIsValid} onClick={() => mutation.mutate()}>Save provider</Button>
    </fieldset>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="grid gap-1 text-sm"><span>{label}</span>{children}</label>
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-dashed p-4 text-center text-muted-foreground">{children}</div>
}

function healthLabel(value: string) {
  if (value === "healthy") return "Healthy"
  if (value === "unhealthy") return "Unhealthy"
  return "Unknown"
}

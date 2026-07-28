"use client"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Pencil, Plus, UserRound } from "lucide-react"
import { useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  createBrandProfile,
  updateBrandProfile,
} from "@/features/automations/telegram-api"
import type { BrandProfile } from "@/features/automations/telegram-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import {
  compactJson,
  EmptyState,
  Field,
  fieldClass,
  formatJsonObject,
  lines,
  parseJsonObject,
  SettingsDialog,
  SettingsSection,
  words,
} from "./content-settings-primitives"

export function EditorialProfilesSection({ profiles }: { profiles: BrandProfile[] }) {
  const [editing, setEditing] = useState<BrandProfile | "new" | null>(null)
  const defaultProfile = profiles.find((profile) => profile.is_default)
  return (
    <SettingsSection
      id="editorial-profiles"
      icon={UserRound}
      title="Editorial profiles"
      description="Reusable language, tone, attribution, and platform defaults."
      action={<Button onClick={() => setEditing("new")}><Plus aria-hidden="true" /> New profile</Button>}
    >
      <div className="rounded-lg border border-border/60 bg-muted/50 p-3 text-sm leading-6 text-foreground" role="note">
        <strong>{defaultProfile ? `${defaultProfile.name} is the default.` : "No default profile is selected."}</strong>{" "}
        Requests that omit a profile use this default. Profile edits can affect queued jobs that have not executed;
        existing revisions remain unchanged.
      </div>
      {profiles.length ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {profiles.map((profile) => (
            <article key={profile.id} className="rounded-lg border border-border/50 bg-background p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{profile.name}</h3>
                    {profile.is_default ? <Badge variant="secondary">Default</Badge> : null}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{profile.output_language.toUpperCase()} · {profile.tone}</p>
                </div>
                <Button variant="outline" size="sm" onClick={() => setEditing(profile)}>
                  <Pencil aria-hidden="true" /> Edit
                </Button>
              </div>
              <details className="mt-3 rounded-lg bg-muted/60 p-3 text-sm">
                <summary className="cursor-pointer font-medium">Advanced profile details</summary>
                <dl className="mt-3 grid gap-2 text-muted-foreground">
                  <div><dt className="font-medium text-foreground">Editorial rules</dt><dd>{profile.editorial_rules?.length ? profile.editorial_rules.join(" · ") : "None"}</dd></div>
                  <div><dt className="font-medium text-foreground">Attribution policy</dt><dd className="break-words font-mono text-xs">{compactJson(profile.attribution_rules ?? {})}</dd></div>
                  <div><dt className="font-medium text-foreground">Default hashtags</dt><dd>{profile.default_hashtags?.length ? profile.default_hashtags.join(" ") : "None"}</dd></div>
                  <div><dt className="font-medium text-foreground">Per-platform preferences</dt><dd className="break-words font-mono text-xs">{compactJson(profile.platform_preferences ?? {})}</dd></div>
                </dl>
              </details>
            </article>
          ))}
        </div>
      ) : <EmptyState title="No editorial profiles" detail="Create one to set output language and editorial voice." />}
      {editing ? <EditorialProfileDialog profile={editing === "new" ? null : editing} onClose={() => setEditing(null)} /> : null}
    </SettingsSection>
  )
}

function EditorialProfileDialog({ profile, onClose }: { profile: BrandProfile | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const initial = {
    name: profile?.name ?? "",
    outputLanguage: profile?.output_language ?? "fa",
    tone: profile?.tone ?? "neutral",
    editorialRules: profile?.editorial_rules?.join("\n") ?? "",
    attributionRules: formatJsonObject(profile?.attribution_rules ?? {}),
    defaultHashtags: profile?.default_hashtags?.join(" ") ?? "",
    platformPreferences: formatJsonObject(profile?.platform_preferences ?? {}),
    isDefault: profile?.is_default ?? false,
  }
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const [jsonTouched, setJsonTouched] = useState({ attribution: false, platforms: false })
  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  const attribution = parseJsonObject(form.attributionRules)
  const platformPreferences = parseJsonObject(form.platformPreferences)
  const error = !form.name.trim()
    ? "Enter a profile name."
    : !form.outputLanguage.trim()
      ? "Enter an output language."
      : !form.tone.trim()
        ? "Enter an editorial tone."
        : attribution.error ?? platformPreferences.error
  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        output_language: form.outputLanguage.trim(),
        tone: form.tone.trim(),
        editorial_rules: lines(form.editorialRules),
        attribution_rules: attribution.value,
        default_hashtags: words(form.defaultHashtags),
        platform_preferences: platformPreferences.value,
        is_default: form.isDefault,
      }
      return profile ? updateBrandProfile(profile.id, body) : createBrandProfile(body)
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.brandProfiles }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
        queryClient.invalidateQueries({ queryKey: queryKeys.editorialBrandOptions }),
      ])
      pushNotice({
        tone: "success",
        title: profile ? "Profile updated" : "Profile created",
        message: "Future jobs will use the saved profile. Existing revisions were not changed.",
      })
      onClose()
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Profile could not be saved", message: getApiErrorMessage(cause) }),
  })
  return (
    <SettingsDialog
      title={profile ? `Edit ${profile.name}` : "New editorial profile"}
      description="Primary editorial defaults stay visible; detailed rules remain optional."
      dirty={dirty}
      pending={mutation.isPending}
      submitDisabled={Boolean(error)}
      onClose={onClose}
      onReset={() => {
        setForm(initial)
        setTouched(false)
        setJsonTouched({ attribution: false, platforms: false })
      }}
      onSubmit={() => {
        setTouched(true)
        setJsonTouched({ attribution: true, platforms: true })
        if (!error) mutation.mutate()
      }}
      submitLabel={profile ? "Save profile" : "Create profile"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Profile name" required error={touched && !form.name.trim() ? error : null}>
          <input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
        <Field label="Output language" required hint="BCP 47 language code, such as fa, en, or en-GB.">
          <input className={fieldClass} maxLength={12} autoCapitalize="none" value={form.outputLanguage} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, outputLanguage: event.target.value })} />
        </Field>
        <Field label="Editorial tone" required hint="Short voice direction, such as neutral, direct, or analytical.">
          <input className={fieldClass} maxLength={120} value={form.tone} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, tone: event.target.value })} />
        </Field>
        <label className="flex min-h-11 items-center gap-2 self-end rounded-lg border px-3 text-sm">
          <input type="checkbox" checked={form.isDefault} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, isDefault: event.target.checked })} />
          Default editorial profile
        </label>
      </div>
      <p className="rounded-lg bg-muted/60 p-3 text-sm leading-6 text-muted-foreground">
        Selecting a default changes profile resolution for future requests that do not choose one explicitly.
        Automation routes keep their selected profile. Saved revisions are immutable.
      </p>
      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer font-medium">Advanced policies and platform preferences</summary>
        <div className="mt-4 grid gap-4">
          <Field label="Editorial rules" hint="One rule per line">
            <textarea className={fieldClass} rows={5} value={form.editorialRules} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, editorialRules: event.target.value })} />
          </Field>
          <Field label="Default hashtags" hint="Separated by spaces">
            <input className={fieldClass} value={form.defaultHashtags} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, defaultHashtags: event.target.value })} />
          </Field>
          <Field
            label="Attribution policy (JSON)"
            hint="Structured source-credit rules passed to future generation jobs."
            error={jsonTouched.attribution ? attribution.error : null}
          >
            <textarea
              className={`${fieldClass} font-mono text-sm`}
              rows={5}
              dir="ltr"
              spellCheck={false}
              value={form.attributionRules}
              disabled={mutation.isPending}
              onBlur={() => setJsonTouched({ ...jsonTouched, attribution: true })}
              onChange={(event) => setForm({ ...form, attributionRules: event.target.value })}
            />
          </Field>
          <Field
            label="Per-platform preferences (JSON)"
            hint='Advanced generation preferences keyed by platform, for example {"telegram":{"direction":"rtl"}}.'
            error={jsonTouched.platforms ? platformPreferences.error : null}
          >
            <textarea
              className={`${fieldClass} font-mono text-sm`}
              rows={6}
              dir="ltr"
              spellCheck={false}
              value={form.platformPreferences}
              disabled={mutation.isPending}
              onBlur={() => setJsonTouched({ ...jsonTouched, platforms: true })}
              onChange={(event) => setForm({ ...form, platformPreferences: event.target.value })}
            />
          </Field>
        </div>
      </details>
    </SettingsDialog>
  )
}

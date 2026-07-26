"use client"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  CircleAlert,
  ExternalLink,
  LoaderCircle,
  Plus,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  Trash2,
} from "lucide-react"
import { useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import {
  createCodexPairingSession,
  revokeCodexConnection,
  rotateCodexConnection,
} from "./content-settings-api"
import type { CodexActivity, CodexConnection } from "./content-settings-api"
import {
  ActionButton,
  connectionColor,
  EmptyState,
  Field,
  fieldClass,
  formatDate,
  OneTimeSecretDialog,
  safeCode,
  SettingsDialog,
  SettingsSection,
  StatusBadge,
} from "./content-settings-primitives"

const readScopes = [
  "settings:read",
  "providers:read",
  "destinations:read",
  "prompts:read",
  "automations:read",
  "jobs:read",
]

export function CodexSection({
  connections,
  activity,
  error,
  loading,
  refreshing,
  onRetry,
}: {
  connections: CodexConnection[]
  activity: CodexActivity[]
  error: string | null
  loading: boolean
  refreshing: boolean
  onRetry: () => void
}) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [pairing, setPairing] = useState(false)
  const [issued, setIssued] = useState<{ title: string; secret: string; command?: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.codexConnections }),
    queryClient.invalidateQueries({ queryKey: queryKeys.codexActivity }),
  ])
  const rotate = async (connection: CodexConnection) => {
    setBusy(`${connection.id}:rotate`)
    try {
      const result = await rotateCodexConnection(connection.id)
      setIssued({ title: `Rotated credential for ${connection.device_name}`, secret: result.credential })
      await refresh()
    } catch (cause) {
      pushNotice({ tone: "error", title: "Credential rotation failed", message: getApiErrorMessage(cause) })
    } finally { setBusy(null) }
  }
  const revoke = async (connection: CodexConnection) => {
    if (!window.confirm(`Revoke ${connection.device_name}? Access stops immediately.`)) return
    setBusy(`${connection.id}:revoke`)
    try {
      await revokeCodexConnection(connection.id)
      await refresh()
      pushNotice({ tone: "success", title: "Codex connection revoked", message: connection.device_name })
    } catch (cause) {
      pushNotice({ tone: "error", title: "Revocation failed", message: getApiErrorMessage(cause) })
    } finally { setBusy(null) }
  }
  return (
    <SettingsSection
      id="codex-connection"
      icon={ShieldCheck}
      title="Codex connection"
      description="Paired, scoped access. Green requires a recent authenticated heartbeat."
      action={!error && !loading ? <Button onClick={() => setPairing(true)}><Plus aria-hidden="true" /> Pair Codex</Button> : undefined}
    >
      {error ? (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100 sm:flex-row sm:items-center">
          <CircleAlert className="size-5 shrink-0" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold">Codex management unavailable</h3>
            <p dir="auto" className="mt-1 text-sm">{error}</p>
          </div>
          <Button variant="outline" disabled={refreshing} onClick={onRetry}>
            <RefreshCw className={refreshing ? "animate-spin" : undefined} aria-hidden="true" />
            {refreshing ? "Retrying" : "Retry Codex"}
          </Button>
        </div>
      ) : loading ? (
        <div role="status" className="flex min-h-24 items-center justify-center gap-2 rounded-xl border text-sm text-muted-foreground">
          <LoaderCircle className="animate-spin" aria-hidden="true" /> Checking Codex access
        </div>
      ) : connections.length ? <div className="grid gap-3">
        {connections.map((connection) => (
          <article key={connection.id} className="rounded-xl border bg-background p-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`size-2.5 rounded-full ${connectionColor(connection.status)}`} aria-hidden="true" />
                  <h3 className="font-semibold">{connection.device_name}</h3>
                  <StatusBadge value={connection.connection_state} />
                  <StatusBadge value={connection.status} />
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Last seen {formatDate(connection.last_heartbeat_at, "never")} · Expires {formatDate(connection.expires_at)}
                </p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {connection.scopes.map((scope) => <Badge key={scope} variant="outline">{scope}</Badge>)}
                </div>
                {connection.failure_code ? <p className="mt-2 text-sm text-amber-800 dark:text-amber-300">{safeCode(connection.failure_code)}</p> : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <ActionButton label="Rotate" icon={RotateCw} busy={busy === `${connection.id}:rotate`} onClick={() => void rotate(connection)} />
                <ActionButton label="Revoke" icon={Trash2} destructive busy={busy === `${connection.id}:revoke`} onClick={() => void revoke(connection)} />
              </div>
            </div>
          </article>
        ))}
      </div> : <EmptyState title="No Codex connection" detail="Pair a device with least-privilege read scopes." />}
      {!error && !loading ? <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
        <div className="rounded-xl border bg-muted/40 p-4">
          <h3 className="font-semibold">Recent safe activity</h3>
          {activity.length ? <ol className="mt-3 divide-y">
            {activity.map((event) => (
              <li key={event.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>{safeCode(event.action)} · {safeCode(event.outcome)}</span>
                <time className="text-muted-foreground">{formatDate(event.created_at)}</time>
              </li>
            ))}
          </ol> : <p className="mt-2 text-sm text-muted-foreground">No recent gateway activity.</p>}
        </div>
        <a className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-medium hover:bg-muted" href="https://github.com/arminakb/NewsCraft/blob/main/docs/codex/skill.md" target="_blank" rel="noreferrer">
          Open skill.md <ExternalLink aria-hidden="true" />
        </a>
      </div> : null}
      {pairing ? <CodexPairingDialog onClose={() => setPairing(false)} onIssued={(result) => { setPairing(false); setIssued(result); void refresh() }} /> : null}
      {issued ? <OneTimeSecretDialog {...issued} onClose={() => setIssued(null)} /> : null}
    </SettingsSection>
  )
}

function CodexPairingDialog({ onClose, onIssued }: { onClose: () => void; onIssued: (result: { title: string; secret: string; command?: string }) => void }) {
  const { pushNotice } = useNotices()
  const initial = { deviceName: "", scopes: readScopes }
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const dirty = form.deviceName !== "" || form.scopes.length !== readScopes.length
  const mutation = useMutation({
    mutationFn: () => createCodexPairingSession(form.deviceName.trim(), form.scopes),
    onSuccess: (session) => onIssued({ title: `Pair ${session.device_name}`, secret: session.pairing_code, command: session.local_command }),
    onError: (cause) => pushNotice({ tone: "error", title: "Pairing session failed", message: getApiErrorMessage(cause) }),
  })
  return (
    <SettingsDialog
      title="Pair Codex"
      description="Create a five-minute, one-time pairing code. Start with least-privilege read scopes."
      dirty={dirty}
      pending={mutation.isPending}
      submitDisabled={!form.deviceName.trim() || !form.scopes.length}
      onClose={onClose}
      onReset={() => setForm(initial)}
      onSubmit={() => { setTouched(true); if (form.deviceName.trim() && form.scopes.length) mutation.mutate() }}
      submitLabel="Create pairing code"
    >
      <Field label="Agent or device name" required error={touched && !form.deviceName.trim() ? "Enter a device name." : null}>
        <input autoFocus className={fieldClass} value={form.deviceName} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, deviceName: event.target.value })} />
      </Field>
      <fieldset className="rounded-lg border p-3">
        <legend className="px-1 text-sm font-medium">Granted read scopes</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {readScopes.map((scope) => (
            <label key={scope} className="flex min-h-10 items-center gap-2 rounded-md px-2 hover:bg-muted">
              <input type="checkbox" checked={form.scopes.includes(scope)} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, scopes: event.target.checked ? [...form.scopes, scope] : form.scopes.filter((item) => item !== scope) })} />
              <span className="text-sm">{scope}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </SettingsDialog>
  )
}

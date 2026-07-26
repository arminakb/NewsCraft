"use client"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  Bot,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  ShieldCheck,
  Trash2,
} from "lucide-react"
import { useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { Button } from "@/components/ui/button"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import {
  createTelegramDestination,
  createTelegramProxy,
  deleteTelegramDestination,
  deleteTelegramProxy,
  getTelegramDestinationDependencies,
  getTelegramProxyDependencies,
  recheckTelegramDestination,
  recheckTelegramProxy,
  rotateTelegramProxyCredentials,
  rotateTelegramToken,
  setTelegramDestinationEnabled,
  setTelegramProxyEnabled,
  updateTelegramDestination,
  updateTelegramProxy,
} from "./content-settings-api"
import type {
  TelegramDestination,
  TelegramProxy,
} from "./content-settings-api"
import {
  ActionButton,
  EmptyState,
  Field,
  fieldClass,
  formatDate,
  HealthStage,
  NumberField,
  safeCode,
  SecretDialog,
  SettingsDialog,
  SettingsSection,
  StatusBadge,
} from "./content-settings-primitives"

export function TelegramSection({ destinations, proxies }: { destinations: TelegramDestination[]; proxies: TelegramProxy[] }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [editing, setEditing] = useState<TelegramDestination | "new" | null>(null)
  const [rotating, setRotating] = useState<TelegramDestination | null>(null)
  const [proxyEditing, setProxyEditing] = useState<TelegramProxy | "new" | null>(null)
  const [proxyRotating, setProxyRotating] = useState<TelegramProxy | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.telegramDestinations }),
    queryClient.invalidateQueries({ queryKey: queryKeys.telegramProxies }),
    queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
  ])
  const destinationAction = async (destination: TelegramDestination, action: "recheck" | "toggle" | "dependencies" | "delete") => {
    setBusy(`${destination.id}:${action}`)
    try {
      if (action === "recheck") {
        await recheckTelegramDestination(destination.id)
        pushNotice({ tone: "success", title: "Destination check queued", message: "Health updates automatically." })
      } else if (action === "toggle") {
        await setTelegramDestinationEnabled(destination.id, !destination.enabled)
      } else {
        const deps = await getTelegramDestinationDependencies(destination.id)
        const summary = `${deps.automations} automations, ${deps.publishJobs} publish jobs, ${deps.publications} publications, ${deps.activeJobs} active jobs`
        if (action === "dependencies") pushNotice({ tone: deps.blocked ? "error" : "success", title: "Destination dependencies", message: summary })
        else if (!deps.blocked && window.confirm(`Delete ${destination.name}? This cannot be undone.`)) await deleteTelegramDestination(destination.id)
        else if (deps.blocked) pushNotice({ tone: "error", title: "Destination cannot be deleted", message: summary })
      }
      await refresh()
    } catch (cause) {
      pushNotice({ tone: "error", title: "Destination action failed", message: getApiErrorMessage(cause) })
    } finally { setBusy(null) }
  }
  const proxyAction = async (proxy: TelegramProxy, action: "recheck" | "toggle" | "delete") => {
    setBusy(`${proxy.id}:${action}`)
    try {
      if (action === "recheck") await recheckTelegramProxy(proxy.id)
      else if (action === "toggle") await setTelegramProxyEnabled(proxy.id, !proxy.enabled)
      else {
        const deps = await getTelegramProxyDependencies(proxy.id)
        if (deps.blocked) pushNotice({ tone: "error", title: "Proxy cannot be deleted", message: `Assigned to ${deps.destinations} destinations.` })
        else if (window.confirm(`Delete ${proxy.name}?`)) await deleteTelegramProxy(proxy.id)
      }
      await refresh()
    } catch (cause) {
      pushNotice({ tone: "error", title: "Proxy action failed", message: getApiErrorMessage(cause) })
    } finally { setBusy(null) }
  }
  return (
    <SettingsSection
      id="telegram-destinations"
      icon={Bot}
      title="Telegram destinations"
      description="Bot API destinations and reusable direct or proxy connection routes."
      action={<Button onClick={() => setEditing("new")}><Plus aria-hidden="true" /> Add destination</Button>}
    >
      {destinations.length ? <div className="grid gap-3">
        {destinations.map((destination) => (
          <article key={destination.id} className="rounded-xl border bg-background p-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold">{destination.name}</h3>
                  <StatusBadge value={destination.enabled ? "enabled" : "disabled"} />
                  <StatusBadge value={destination.healthStatus} />
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{destination.canonicalTarget} · {destination.connectionRoute}</p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                  <HealthStage label="Proxy" value={destination.proxyHealthStatus} />
                  <HealthStage label="Telegram API" value={destination.telegramHealthStatus} />
                  <HealthStage label="Bot" value={destination.botHealthStatus} />
                  <HealthStage label="Target" value={destination.targetHealthStatus} />
                  <HealthStage label="Administrator" value={destination.administratorStatus} />
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  {destination.verifiedChatTitle ?? "Target not verified"} · {destination.verifiedBotUsername ? `@${destination.verifiedBotUsername}` : "Bot not verified"} · {formatDate(destination.lastCheckedAt, "Never checked")}
                </p>
                {destination.failureCode ? <p className="mt-2 text-sm text-amber-800 dark:text-amber-300">{safeCode(destination.failureCode)}</p> : null}
              </div>
              <div className="flex flex-wrap gap-2 xl:max-w-md xl:justify-end">
                <ActionButton label="Edit" icon={Pencil} onClick={() => setEditing(destination)} />
                <ActionButton label="Rotate token" icon={KeyRound} onClick={() => setRotating(destination)} />
                <ActionButton label="Recheck" icon={RefreshCw} busy={busy === `${destination.id}:recheck`} onClick={() => void destinationAction(destination, "recheck")} />
                <ActionButton label={destination.enabled ? "Disable" : "Enable"} icon={ShieldCheck} busy={busy === `${destination.id}:toggle`} onClick={() => void destinationAction(destination, "toggle")} />
                <ActionButton label="Dependencies" icon={Route} busy={busy === `${destination.id}:dependencies`} onClick={() => void destinationAction(destination, "dependencies")} />
                <ActionButton label="Delete" icon={Trash2} destructive busy={busy === `${destination.id}:delete`} onClick={() => void destinationAction(destination, "delete")} />
              </div>
            </div>
          </article>
        ))}
      </div> : <EmptyState title="No Telegram destinations" detail="Add a bot token and channel or group identifier." />}

      <details className="rounded-xl border bg-muted/30 p-4">
        <summary className="cursor-pointer font-semibold">Manage proxy profiles ({proxies.length})</summary>
        <div className="mt-4 space-y-3">
          <Button variant="outline" onClick={() => setProxyEditing("new")}><Plus aria-hidden="true" /> New proxy profile</Button>
          {proxies.map((proxy) => (
            <div key={proxy.id} className="flex flex-col gap-3 rounded-lg border bg-background p-3 lg:flex-row lg:items-center">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2"><strong>{proxy.name}</strong><StatusBadge value={proxy.enabled ? "enabled" : "disabled"} /><StatusBadge value={proxy.reachabilityStatus} /></div>
                <div className="mt-1 text-sm text-muted-foreground">{proxy.proxyType === "http_connect" ? "HTTP CONNECT" : "SOCKS5"} · {proxy.host}:{proxy.port} · {proxy.credentialsConfigured ? "Credentials configured" : "No credentials"}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <ActionButton label="Edit" icon={Pencil} onClick={() => setProxyEditing(proxy)} />
                <ActionButton label="Credentials" icon={KeyRound} onClick={() => setProxyRotating(proxy)} />
                <ActionButton label="Test" icon={RefreshCw} busy={busy === `${proxy.id}:recheck`} onClick={() => void proxyAction(proxy, "recheck")} />
                <ActionButton label={proxy.enabled ? "Disable" : "Enable"} icon={ShieldCheck} busy={busy === `${proxy.id}:toggle`} onClick={() => void proxyAction(proxy, "toggle")} />
                <ActionButton label="Delete" icon={Trash2} destructive busy={busy === `${proxy.id}:delete`} onClick={() => void proxyAction(proxy, "delete")} />
              </div>
            </div>
          ))}
        </div>
      </details>
      {editing ? <DestinationDialog destination={editing === "new" ? null : editing} proxies={proxies} onClose={() => setEditing(null)} /> : null}
      {proxyEditing ? <ProxyDialog proxy={proxyEditing === "new" ? null : proxyEditing} onClose={() => setProxyEditing(null)} /> : null}
      {proxyRotating ? <ProxyCredentialsDialog proxy={proxyRotating} onClose={() => setProxyRotating(null)} /> : null}
      {rotating ? <SecretDialog title={`Rotate token for ${rotating.name}`} label="New bot token" onClose={() => setRotating(null)} onSave={async (secret) => { await rotateTelegramToken(rotating.id, secret); await refresh(); pushNotice({ tone: "success", title: "Bot token rotated", message: "Destination check queued." }) }} /> : null}
    </SettingsSection>
  )
}

function DestinationDialog({
  destination,
  proxies,
  onClose,
}: {
  destination: TelegramDestination | null
  proxies: TelegramProxy[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const initial = { name: destination?.name ?? "", target: destination?.targetRef ?? "", botToken: "", proxyProfileId: destination?.proxyProfileId ?? "" }
  const [form, setForm] = useState(initial)
  const [showProxyCreate, setShowProxyCreate] = useState(false)
  const [newProxy, setNewProxy] = useState({
    name: "",
    proxyType: "http_connect" as TelegramProxy["proxyType"],
    host: "",
    port: 8080,
    username: "",
    password: "",
  })
  const [touched, setTouched] = useState(false)
  const dirty = JSON.stringify(form) !== JSON.stringify(initial) || showProxyCreate
  const error = !form.name.trim() ? "Enter a destination name." : !form.target.trim() ? "Enter a channel or group identifier." : !destination && !form.botToken ? "Enter a bot token." : null
  const mutation = useMutation({
    mutationFn: () => destination
      ? updateTelegramDestination(destination.id, { name: form.name.trim(), target: form.target.trim(), proxyProfileId: form.proxyProfileId || null })
      : createTelegramDestination({ name: form.name.trim(), target: form.target.trim(), botToken: form.botToken, proxyProfileId: form.proxyProfileId || null }),
    onSuccess: async () => {
      setForm({ ...form, botToken: "" })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramDestinations }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      pushNotice({ tone: "success", title: destination ? "Destination updated" : "Destination created", message: "Route-specific health check queued." })
      onClose()
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Destination could not be saved", message: getApiErrorMessage(cause) }),
  })
  const createProxy = useMutation({
    mutationFn: () => createTelegramProxy({
      name: newProxy.name.trim(),
      proxyType: newProxy.proxyType,
      host: newProxy.host.trim(),
      port: newProxy.port,
      ...(newProxy.username ? { username: newProxy.username, password: newProxy.password } : {}),
    }),
    onSuccess: async (result) => {
      setForm((current) => ({ ...current, proxyProfileId: result.proxy.id }))
      setShowProxyCreate(false)
      setNewProxy({ name: "", proxyType: "http_connect", host: "", port: 8080, username: "", password: "" })
      await queryClient.invalidateQueries({ queryKey: queryKeys.telegramProxies })
      pushNotice({ tone: "success", title: "Proxy profile created", message: "Selected for this destination. Reachability check queued." })
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Proxy could not be created", message: getApiErrorMessage(cause) }),
  })
  const proxyCredentialsInvalid = Boolean(newProxy.username) !== Boolean(newProxy.password)
  const proxyInvalid = !newProxy.name.trim() || !newProxy.host.trim() || newProxy.host.includes("://") || proxyCredentialsInvalid
  return (
    <SettingsDialog
      title={destination ? `Edit ${destination.name}` : "Add Telegram destination"}
      description="The same selected route is used for health checks and every publish request."
      dirty={dirty}
      pending={mutation.isPending || createProxy.isPending}
      submitDisabled={Boolean(error) || showProxyCreate}
      onClose={onClose}
      onReset={() => { setForm(initial); setShowProxyCreate(false) }}
      onSubmit={() => { setTouched(true); if (!error) mutation.mutate() }}
      submitLabel={destination ? "Save destination" : "Add destination"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Destination name" required error={touched && !form.name.trim() ? error : null}>
          <input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
        <Field label="Channel or group identifier" required hint="@channel or numeric ID">
          <input className={fieldClass} value={form.target} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, target: event.target.value })} />
        </Field>
      </div>
      {!destination ? <Field label="Bot token" required hint="Write-only. Never shown again."><input type="password" autoComplete="new-password" className={fieldClass} value={form.botToken} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, botToken: event.target.value })} /></Field> : null}
      <Field label="Connection route">
        <div className="flex gap-2">
          <select className={fieldClass} value={form.proxyProfileId} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, proxyProfileId: event.target.value })}>
            <option value="">Direct connection</option>
            {proxies.filter((proxy) => proxy.enabled).map((proxy) => <option key={proxy.id} value={proxy.id}>{proxy.name} · {proxy.proxyType === "http_connect" ? "HTTP CONNECT" : "SOCKS5"}</option>)}
          </select>
          <Button type="button" variant="outline" onClick={() => setShowProxyCreate((value) => !value)}>{showProxyCreate ? "Cancel proxy" : "New proxy"}</Button>
        </div>
      </Field>
      {showProxyCreate ? (
        <fieldset className="space-y-4 rounded-lg border bg-muted/30 p-4">
          <legend className="px-1 font-medium">Create proxy inline</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Proxy name" required><input className={fieldClass} value={newProxy.name} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, name: event.target.value })} /></Field>
            <Field label="Proxy type"><select className={fieldClass} value={newProxy.proxyType} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, proxyType: event.target.value as TelegramProxy["proxyType"] })}><option value="http_connect">HTTP CONNECT</option><option value="socks5">SOCKS5</option></select></Field>
            <Field label="Host" required error={newProxy.host.includes("://") ? "Use a plain host without a scheme." : null}><input className={fieldClass} value={newProxy.host} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, host: event.target.value })} /></Field>
            <NumberField label="Port" value={newProxy.port} min={1} max={65535} onChange={(port) => setNewProxy({ ...newProxy, port })} />
            <Field label="Username" error={proxyCredentialsInvalid ? "Username and password must be supplied together." : null}><input className={fieldClass} autoComplete="off" value={newProxy.username} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, username: event.target.value })} /></Field>
            <Field label="Password"><input type="password" className={fieldClass} autoComplete="new-password" value={newProxy.password} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, password: event.target.value })} /></Field>
          </div>
          <Button type="button" disabled={proxyInvalid || createProxy.isPending} onClick={() => createProxy.mutate()}>{createProxy.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Plus aria-hidden="true" />}Create and select proxy</Button>
        </fieldset>
      ) : null}
    </SettingsDialog>
  )
}

function ProxyDialog({ proxy, onClose }: { proxy: TelegramProxy | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const initial = { name: proxy?.name ?? "", proxyType: proxy?.proxyType ?? "http_connect" as const, host: proxy?.host ?? "", port: proxy?.port ?? 8080, username: "", password: "" }
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  const credentialsInvalid = Boolean(form.username) !== Boolean(form.password)
  const error = !form.name.trim() ? "Enter a proxy name." : !form.host.trim() ? "Enter a plain hostname." : form.host.includes("://") ? "Host must not include a scheme." : credentialsInvalid ? "Username and password must be supplied together." : null
  const mutation = useMutation({
    mutationFn: () => proxy
      ? updateTelegramProxy(proxy.id, { name: form.name.trim(), proxyType: form.proxyType, host: form.host.trim(), port: form.port })
      : createTelegramProxy({ name: form.name.trim(), proxyType: form.proxyType, host: form.host.trim(), port: form.port, ...(form.username ? { username: form.username, password: form.password } : {}) }),
    onSuccess: async () => {
      setForm({ ...form, username: "", password: "" })
      await queryClient.invalidateQueries({ queryKey: queryKeys.telegramProxies })
      pushNotice({ tone: "success", title: proxy ? "Proxy updated" : "Proxy created", message: "Reachability check queued." })
      onClose()
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Proxy could not be saved", message: getApiErrorMessage(cause) }),
  })
  return (
    <SettingsDialog
      title={proxy ? `Edit ${proxy.name}` : "New proxy profile"}
      description="Supported transport: HTTP/HTTPS CONNECT or SOCKS5. MTProto is not supported."
      dirty={dirty}
      pending={mutation.isPending}
      submitDisabled={Boolean(error)}
      onClose={onClose}
      onReset={() => setForm(initial)}
      onSubmit={() => { setTouched(true); if (!error) mutation.mutate() }}
      submitLabel={proxy ? "Save proxy" : "Create proxy"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Profile name" required error={touched && error?.includes("name") ? error : null}><input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
        <Field label="Proxy type"><select className={fieldClass} value={form.proxyType} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, proxyType: event.target.value as "http_connect" | "socks5" })}><option value="http_connect">HTTP CONNECT</option><option value="socks5">SOCKS5</option></select></Field>
        <Field label="Host" required error={touched && (form.host.includes("://") || !form.host.trim()) ? error : null}><input className={fieldClass} value={form.host} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, host: event.target.value })} /></Field>
        <NumberField label="Port" value={form.port} min={1} max={65535} onChange={(port) => setForm({ ...form, port })} />
      </div>
      {!proxy ? <details className="rounded-lg border p-3"><summary className="cursor-pointer font-medium">Optional proxy credentials</summary><div className="mt-4 grid gap-4 sm:grid-cols-2"><Field label="Username" error={touched && credentialsInvalid ? error : null}><input className={fieldClass} autoComplete="off" value={form.username} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, username: event.target.value })} /></Field><Field label="Password"><input type="password" autoComplete="new-password" className={fieldClass} value={form.password} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, password: event.target.value })} /></Field></div></details> : null}
    </SettingsDialog>
  )
}

function ProxyCredentialsDialog({ proxy, onClose }: { proxy: TelegramProxy; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [remove, setRemove] = useState(false)
  const [pending, setPending] = useState(false)
  const dirty = Boolean(username || password || remove)
  const invalid = Boolean(username) !== Boolean(password)
  return (
    <SettingsDialog
      title={`Proxy credentials for ${proxy.name}`}
      description="Submit both values to rotate credentials, or leave both blank and save to remove them."
      dirty={dirty}
      pending={pending}
      submitDisabled={invalid}
      onClose={onClose}
      onReset={() => { setUsername(""); setPassword(""); setRemove(false) }}
      onSubmit={() => {
        if (invalid) return
        setPending(true)
        void rotateTelegramProxyCredentials(proxy.id, remove ? undefined : username || undefined, remove ? undefined : password || undefined)
          .then(async () => {
            setUsername("")
            setPassword("")
            await queryClient.invalidateQueries({ queryKey: queryKeys.telegramProxies })
            pushNotice({ tone: "success", title: "Proxy credentials updated", message: "Reachability check queued." })
            onClose()
          })
          .catch((cause) => pushNotice({ tone: "error", title: "Credential rotation failed", message: getApiErrorMessage(cause) }))
          .finally(() => setPending(false))
      }}
      submitLabel={remove ? "Remove credentials" : "Rotate credentials"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Username" error={invalid ? "Username and password must be supplied together." : null}>
          <input autoFocus className={fieldClass} autoComplete="off" value={username} disabled={pending || remove} onChange={(event) => setUsername(event.target.value)} />
        </Field>
        <Field label="Password">
          <input type="password" className={fieldClass} autoComplete="new-password" value={password} disabled={pending || remove} onChange={(event) => setPassword(event.target.value)} />
        </Field>
      </div>
      {proxy.credentialsConfigured ? <label className="flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm"><input type="checkbox" checked={remove} disabled={pending} onChange={(event) => { setRemove(event.target.checked); if (event.target.checked) { setUsername(""); setPassword("") } }} />Remove configured credentials</label> : null}
    </SettingsDialog>
  )
}

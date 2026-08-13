"use client"

import { Menu } from "@base-ui/react/menu"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  CircleDashed,
  Clock3,
  Ellipsis,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  Send,
  ShieldCheck,
  Trash2,
} from "lucide-react"
import { useState } from "react"
import type React from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Button, buttonVariants } from "@/components/ui/button"
import { ApiError } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"
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
  EmptyState,
  Field,
  fieldClass,
  formatDate,
  NumberField,
  safeCode,
  SecretDialog,
  SettingsDialog,
  SettingsSection,
  StatusBadge,
} from "./content-settings-primitives"

export function TelegramSection({ destinations, proxies }: { destinations: TelegramDestination[]; proxies: TelegramProxy[] }) {
  const { timezone } = useDateTime()
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [editing, setEditing] = useState<TelegramDestination | "new" | null>(null)
  const [rotating, setRotating] = useState<TelegramDestination | null>(null)
  const [proxyEditing, setProxyEditing] = useState<TelegramProxy | "new" | null>(null)
  const [proxyRotating, setProxyRotating] = useState<TelegramProxy | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const showError = (cause: unknown, fallbackTitle: string) => {
    const error = telegramActionError(cause, fallbackTitle)
    pushNotice({ tone: "error", title: error.title, message: error.message })
  }
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
      showError(cause, "Destination action failed")
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
      showError(cause, "Proxy action failed")
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
          <TelegramDestinationCard
            busy={busy}
            destination={destination}
            key={destination.id}
            onAction={(action) => void destinationAction(destination, action)}
            onEdit={() => setEditing(destination)}
            onRotate={() => setRotating(destination)}
            proxies={proxies}
            timezone={timezone}
          />
        ))}
      </div> : <EmptyState title="No Telegram destinations" detail="Add a bot token and channel or group identifier." />}

      <details className="group border-t border-border/60 pt-2">
        <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-md px-1 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
          <ChevronDown aria-hidden="true" className="size-4 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
          Proxy profiles ({proxies.length})
        </summary>
        <div className="mt-4 space-y-3">
          <Button variant="outline" onClick={() => setProxyEditing("new")}><Plus aria-hidden="true" /> New proxy profile</Button>
          {proxies.map((proxy) => (
            <TelegramProxyCard
              busy={busy}
              key={proxy.id}
              onAction={(action) => void proxyAction(proxy, action)}
              onCredentials={() => setProxyRotating(proxy)}
              onEdit={() => setProxyEditing(proxy)}
              proxy={proxy}
              timezone={timezone}
            />
          ))}
          {!proxies.length ? <EmptyState title="No proxy profiles" detail="Destinations can connect directly without a proxy." /> : null}
        </div>
      </details>
      {editing ? <DestinationDialog destination={editing === "new" ? null : editing} proxies={proxies} onClose={() => setEditing(null)} /> : null}
      {proxyEditing ? <ProxyDialog proxy={proxyEditing === "new" ? null : proxyEditing} onClose={() => setProxyEditing(null)} /> : null}
      {proxyRotating ? <ProxyCredentialsDialog proxy={proxyRotating} onClose={() => setProxyRotating(null)} /> : null}
      {rotating ? <SecretDialog title={`Rotate token for ${rotating.name}`} label="New bot token" onClose={() => setRotating(null)} onError={(cause) => showError(cause, "Token rotation failed")} onSave={async (secret) => { await rotateTelegramToken(rotating.id, secret); await refresh(); pushNotice({ tone: "success", title: "Bot token rotated", message: "Destination check queued." }) }} /> : null}
    </SettingsSection>
  )
}

function TelegramDestinationCard({
  busy,
  destination,
  onAction,
  onEdit,
  onRotate,
  proxies,
  timezone,
}: {
  busy: string | null
  destination: TelegramDestination
  onAction: (action: "recheck" | "toggle" | "dependencies" | "delete") => void
  onEdit: () => void
  onRotate: () => void
  proxies: TelegramProxy[]
  timezone: string
}) {
  const proxyName = proxies.find((proxy) => proxy.id === destination.proxy_profile_id)?.name
  const route = destination.proxy_profile_id
    ? `Proxy: ${proxyName ?? destination.connection_route}`
    : "Direct"
  const targetType = destination.target_type === "numeric_id"
    ? "Numeric ID"
    : destination.target_type === "username" ? "Username" : "Legacy"

  return (
    <article
      aria-labelledby={`telegram-destination-${destination.id}`}
      className="min-w-0 max-w-full overflow-hidden rounded-xl border border-border/60 bg-card p-3 shadow-xs"
      data-testid="telegram-destination-card"
    >
      <div className="flex min-w-0 items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
          <Send aria-hidden="true" className="size-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="mr-0.5 min-w-0 max-w-full truncate text-sm font-semibold" id={`telegram-destination-${destination.id}`} title={destination.name}>{destination.name}</h3>
            <StatusBadge value={destination.enabled ? "enabled" : "disabled"} />
            <StatusBadge value={destination.health_status} />
          </div>
          <p className="mt-1 truncate font-mono text-xs text-muted-foreground" title={destination.canonical_target}>{destination.canonical_target}</p>
        </div>
        <TelegramOverflowMenu
          busy={busy}
          id={destination.id}
          name={destination.name}
          onDelete={() => onAction("delete")}
          onDependencies={() => onAction("dependencies")}
          onRotate={onRotate}
          type="destination"
        />
      </div>

      <dl className="mt-3 grid min-w-0 grid-cols-2 gap-x-4 gap-y-3 border-t border-border/60 pt-3 sm:grid-cols-4">
        <TelegramFact label="Target type" value={targetType} />
        <TelegramFact label="Route" title={route} value={route} />
        <TelegramFact label="Proxy" status value={destination.proxy_health_status} />
        <TelegramFact label="Telegram API" status value={destination.telegram_health_status} />
        <TelegramFact detail={destination.verified_bot_username ? `@${destination.verified_bot_username}` : undefined} label="Bot" status value={destination.bot_health_status} />
        <TelegramFact detail={destination.verified_chat_title ?? undefined} label="Target" status value={destination.target_health_status} />
        <TelegramFact label="Administrator" status value={destination.administrator_status} />
        <TelegramFact icon={Clock3} label="Last checked" title={formatDate(destination.last_checked_at, "Never checked", timezone)} value={formatDate(destination.last_checked_at, "Never checked", timezone)} />
      </dl>

      {destination.failure_code ? (
        <p className="mt-3 flex items-start gap-1.5 text-xs text-warning" role="status">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span>{telegramFailureMessage(destination.failure_code)}</span>
        </p>
      ) : null}

      <div aria-label={`Primary actions for ${destination.name}`} className="mt-3 grid grid-cols-3 gap-2 border-t border-border/60 pt-2" role="group">
        <TelegramActionButton busy={busy === `${destination.id}:recheck`} icon={RefreshCw} label="Check" onClick={() => onAction("recheck")} />
        <TelegramActionButton icon={Pencil} label="Edit" onClick={onEdit} />
        <TelegramActionButton busy={busy === `${destination.id}:toggle`} className={destination.enabled ? "text-warning hover:text-warning" : undefined} icon={ShieldCheck} label={destination.enabled ? "Disable" : "Enable"} onClick={() => onAction("toggle")} variant={destination.enabled ? "ghost" : "secondary"} />
      </div>
    </article>
  )
}

function TelegramProxyCard({ busy, onAction, onCredentials, onEdit, proxy, timezone }: {
  busy: string | null
  onAction: (action: "recheck" | "toggle" | "delete") => void
  onCredentials: () => void
  onEdit: () => void
  proxy: TelegramProxy
  timezone: string
}) {
  const endpoint = `${proxy.host}:${proxy.port}`
  return (
    <article aria-labelledby={`telegram-proxy-${proxy.id}`} className="min-w-0 max-w-full overflow-hidden rounded-xl border border-border/60 bg-card p-3 shadow-xs" data-testid="telegram-proxy-card">
      <div className="flex min-w-0 items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground"><Route aria-hidden="true" className="size-[18px]" /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="mr-0.5 min-w-0 max-w-full truncate text-sm font-semibold" id={`telegram-proxy-${proxy.id}`} title={proxy.name}>{proxy.name}</h3>
            <StatusBadge value={proxy.enabled ? "enabled" : "disabled"} />
            <StatusBadge value={proxy.reachability_status} />
          </div>
          <p className="mt-1 truncate font-mono text-xs text-muted-foreground" title={endpoint}>{endpoint}</p>
        </div>
        <TelegramOverflowMenu busy={busy} id={proxy.id} name={proxy.name} onCredentials={onCredentials} onDelete={() => onAction("delete")} type="proxy" />
      </div>
      <dl className="mt-3 grid min-w-0 grid-cols-2 gap-x-4 gap-y-3 border-t border-border/60 pt-3 sm:grid-cols-4">
        <TelegramFact label="Type" value={proxy.proxy_type === "http_connect" ? "HTTP CONNECT" : "SOCKS5"} />
        <TelegramFact label="Endpoint" title={endpoint} value={endpoint} />
        <TelegramFact label="Credentials" value={proxy.credentials_configured ? "Configured" : "Not configured"} />
        <TelegramFact icon={Clock3} label="Last checked" title={formatDate(proxy.last_checked_at, "Never checked", timezone)} value={formatDate(proxy.last_checked_at, "Never checked", timezone)} />
      </dl>
      {proxy.failure_code ? <p className="mt-3 flex items-start gap-1.5 text-xs text-warning" role="status"><CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" /><span>{telegramFailureMessage(proxy.failure_code)}</span></p> : null}
      <div aria-label={`Primary actions for ${proxy.name}`} className="mt-3 grid grid-cols-3 gap-2 border-t border-border/60 pt-2" role="group">
        <TelegramActionButton busy={busy === `${proxy.id}:recheck`} icon={RefreshCw} label="Test" onClick={() => onAction("recheck")} />
        <TelegramActionButton icon={Pencil} label="Edit" onClick={onEdit} />
        <TelegramActionButton busy={busy === `${proxy.id}:toggle`} className={proxy.enabled ? "text-warning hover:text-warning" : undefined} icon={ShieldCheck} label={proxy.enabled ? "Disable" : "Enable"} onClick={() => onAction("toggle")} variant={proxy.enabled ? "ghost" : "secondary"} />
      </div>
    </article>
  )
}

function TelegramFact({ detail, icon: Icon, label, status, title, value }: {
  detail?: string
  icon?: typeof Bot
  label: string
  status?: boolean
  title?: string
  value: string
}) {
  const normalized = value.toLowerCase().replaceAll("_", " ")
  const healthy = ["healthy", "reachable", "authenticated", "resolved", "administrator", "ready", "direct", "verified"].includes(normalized)
  const failed = ["unhealthy", "unavailable", "unreachable", "failed", "invalid", "not configured", "missing", "not administrator"].includes(normalized)
  const StateIcon = status ? healthy ? CheckCircle2 : failed ? CircleAlert : normalized === "checking" ? LoaderCircle : CircleDashed : Icon
  return (
    <div className="min-w-0">
      <dt className="text-[11px] leading-4 text-muted-foreground">{label}</dt>
      <dd className={cn("mt-0.5 flex min-w-0 items-center gap-1 text-xs font-medium", status && healthy && "text-success", status && failed && "text-warning")}>
        {StateIcon ? <StateIcon aria-hidden="true" className={cn("size-3.5 shrink-0", normalized === "checking" && "animate-spin motion-reduce:animate-none")} /> : null}
        <span className="min-w-0 flex-1 truncate" title={title ?? value}>{status ? safeCode(value) : value}</span>
      </dd>
      {detail ? <dd className="mt-0.5 truncate text-[11px] text-muted-foreground" title={detail}>{detail}</dd> : null}
    </div>
  )
}

function TelegramActionButton({ busy, className, icon: Icon, label, onClick, variant = "outline" }: {
  busy?: boolean
  className?: string
  icon: typeof Bot
  label: string
  onClick: () => void
  variant?: "ghost" | "outline" | "secondary"
}) {
  return (
    <Button aria-busy={busy || undefined} className={cn("min-w-0 px-1.5", className)} disabled={busy} onClick={onClick} size="sm" type="button" variant={variant}>
      {busy ? <LoaderCircle aria-hidden="true" className="animate-spin motion-reduce:animate-none" /> : <Icon aria-hidden="true" />}{label}
    </Button>
  )
}

function TelegramOverflowMenu({ busy, id, name, onCredentials, onDelete, onDependencies, onRotate, type }: {
  busy: string | null
  id: string
  name: string
  onCredentials?: () => void
  onDelete: () => void
  onDependencies?: () => void
  onRotate?: () => void
  type: "destination" | "proxy"
}) {
  return (
    <Menu.Root>
      <Menu.Trigger aria-label={`More actions for ${name}`} className={buttonVariants({ size: "icon-sm", variant: "ghost" })}><Ellipsis aria-hidden="true" /></Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner align="end" className="z-[130] outline-hidden" sideOffset={6}>
          <Menu.Popup className="w-56 origin-[var(--transform-origin)] rounded-lg border border-border/70 bg-popover p-1 text-popover-foreground shadow-md outline-hidden transition-[transform,opacity] duration-150 ease-out data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0 motion-reduce:transition-none">
            {onRotate ? <TelegramMenuItem icon={KeyRound} label="Rotate bot token" onClick={onRotate} sensitive /> : null}
            {onCredentials ? <TelegramMenuItem icon={KeyRound} label="Manage credentials" onClick={onCredentials} sensitive /> : null}
            {onDependencies ? <TelegramMenuItem busy={busy === `${id}:dependencies`} icon={Route} label="View dependencies" onClick={onDependencies} /> : null}
            <Menu.Separator className="mx-1 my-1 h-px bg-border/70" />
            <TelegramMenuItem busy={busy === `${id}:delete`} destructive icon={Trash2} label={`Delete ${type}`} onClick={onDelete} />
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  )
}

function TelegramMenuItem({ busy, destructive, icon: Icon, label, onClick, sensitive }: {
  busy?: boolean
  destructive?: boolean
  icon: typeof Bot
  label: string
  onClick: () => void
  sensitive?: boolean
}) {
  return (
    <Menu.Item className={cn("flex min-h-11 cursor-default items-center gap-2 rounded-md px-2.5 text-sm outline-none select-none data-disabled:opacity-50 data-highlighted:bg-muted min-[900px]:min-h-9", sensitive && "text-warning data-highlighted:bg-[var(--warning-surface)]", destructive && "text-destructive data-highlighted:bg-[var(--error-surface)]")} disabled={busy} onClick={onClick}>
      {busy ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" /> : <Icon aria-hidden="true" className="size-4" />}{label}
    </Menu.Item>
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
  const initial = { name: destination?.name ?? "", target: destination?.target_ref ?? "", botToken: "", proxyProfileId: destination?.proxy_profile_id ?? "" }
  const [form, setForm] = useState(initial)
  const [showProxyCreate, setShowProxyCreate] = useState(false)
  const [newProxy, setNewProxy] = useState({
    name: "",
    proxyType: "http_connect" as TelegramProxy["proxy_type"],
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
    onError: (cause) => {
      const error = telegramActionError(cause, "Destination could not be saved")
      pushNotice({ tone: "error", title: error.title, message: error.message })
    },
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
    onError: (cause) => {
      const error = telegramActionError(cause, "Proxy could not be created")
      pushNotice({ tone: "error", title: error.title, message: error.message })
    },
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
      <FormSection description="Name this destination for operators." title="Basic information">
        <Field label="Destination name" required error={touched && !form.name.trim() ? "Enter a destination name." : null}>
          <input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
      </FormSection>
      <FormSection description="Use @channel, numeric Bot API chat ID, or supported Telegram URL." title="Telegram target">
        <Field label="Channel or group identifier" required error={touched && !form.target.trim() ? "Enter a channel or group identifier." : null}>
          <input className={fieldClass} value={form.target} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, target: event.target.value })} />
        </Field>
      </FormSection>
      {!destination ? (
        <FormSection description="Accepted once and never returned by the API." title="Bot credential">
          <Field label="Bot token" required hint="Write-only. Cleared only after a successful save." error={touched && !form.botToken ? "Enter a bot token." : null}>
            <input type="password" autoComplete="new-password" className={fieldClass} value={form.botToken} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, botToken: event.target.value })} />
          </Field>
        </FormSection>
      ) : null}
      <FormSection description="Use a direct connection or one enabled proxy profile." title="Connection route">
        <Field label="Connection route">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
            <select className={cn(fieldClass, "min-w-0 flex-1")} value={form.proxyProfileId} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, proxyProfileId: event.target.value })}>
              <option value="">Direct connection</option>
              {proxies.filter((proxy) => proxy.enabled).map((proxy) => <option key={proxy.id} value={proxy.id}>{proxy.name} · {proxy.proxy_type === "http_connect" ? "HTTP CONNECT" : "SOCKS5"}</option>)}
            </select>
            <Button className="sm:self-end" type="button" variant="outline" onClick={() => setShowProxyCreate((value) => !value)}>{showProxyCreate ? "Cancel proxy" : "New proxy"}</Button>
          </div>
        </Field>
      </FormSection>
      {showProxyCreate ? (
        <FormSection description="Create a reusable profile, then select it for this destination." title="New proxy profile">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Proxy name" required><input className={fieldClass} value={newProxy.name} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, name: event.target.value })} /></Field>
            <Field label="Proxy type"><select className={fieldClass} value={newProxy.proxyType} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, proxyType: event.target.value as TelegramProxy["proxy_type"] })}><option value="http_connect">HTTP CONNECT</option><option value="socks5">SOCKS5</option></select></Field>
            <Field label="Host" required error={newProxy.host.includes("://") ? "Use a plain host without a scheme." : null}><input className={fieldClass} value={newProxy.host} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, host: event.target.value })} /></Field>
            <NumberField label="Port" value={newProxy.port} min={1} max={65535} onChange={(port) => setNewProxy({ ...newProxy, port })} />
            <Field label="Username" error={proxyCredentialsInvalid ? "Username and password must be supplied together." : null}><input className={fieldClass} autoComplete="off" value={newProxy.username} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, username: event.target.value })} /></Field>
            <Field label="Password"><input type="password" className={fieldClass} autoComplete="new-password" value={newProxy.password} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, password: event.target.value })} /></Field>
          </div>
          <Button type="button" disabled={proxyInvalid || createProxy.isPending} onClick={() => createProxy.mutate()}>{createProxy.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Plus aria-hidden="true" />}Create and select proxy</Button>
        </FormSection>
      ) : null}
    </SettingsDialog>
  )
}

function ProxyDialog({ proxy, onClose }: { proxy: TelegramProxy | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const initial = { name: proxy?.name ?? "", proxyType: proxy?.proxy_type ?? "http_connect" as const, host: proxy?.host ?? "", port: proxy?.port ?? 8080, username: "", password: "" }
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
    onError: (cause) => {
      const safeError = telegramActionError(cause, "Proxy could not be saved")
      pushNotice({ tone: "error", title: safeError.title, message: safeError.message })
    },
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
      <FormSection description="Reusable name and supported transport." title="Basic information">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Profile name" required error={touched && error?.includes("name") ? error : null}><input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
          <Field label="Proxy type"><select className={fieldClass} value={form.proxyType} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, proxyType: event.target.value as "http_connect" | "socks5" })}><option value="http_connect">HTTP CONNECT</option><option value="socks5">SOCKS5</option></select></Field>
        </div>
      </FormSection>
      <FormSection description="Plain host and port only; do not include a URL scheme." title="Endpoint">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Host" required error={touched && (form.host.includes("://") || !form.host.trim()) ? error : null}><input className={fieldClass} value={form.host} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, host: event.target.value })} /></Field>
          <NumberField label="Port" value={form.port} min={1} max={65535} onChange={(port) => setForm({ ...form, port })} />
        </div>
      </FormSection>
      {!proxy ? <details className="group border-t border-border/60 pt-2"><summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-md px-1 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden"><ChevronDown aria-hidden="true" className="size-4 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />Optional proxy credentials</summary><div className="mt-3 grid gap-4 sm:grid-cols-2"><Field label="Username" error={touched && credentialsInvalid ? error : null}><input className={fieldClass} autoComplete="off" value={form.username} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, username: event.target.value })} /></Field><Field label="Password"><input type="password" autoComplete="new-password" className={fieldClass} value={form.password} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, password: event.target.value })} /></Field></div></details> : null}
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
          .catch((cause) => {
            const error = telegramActionError(cause, "Credential rotation failed")
            pushNotice({ tone: "error", title: error.title, message: error.message })
          })
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
      {proxy.credentials_configured ? <label className="flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm"><input type="checkbox" checked={remove} disabled={pending} onChange={(event) => { setRemove(event.target.checked); if (event.target.checked) { setUsername(""); setPassword("") } }} />Remove configured credentials</label> : null}
    </SettingsDialog>
  )
}

function FormSection({ children, description, title }: {
  children: React.ReactNode
  description: string
  title: string
}) {
  return (
    <fieldset className="min-w-0 space-y-3 border-t border-border/60 pt-4">
      <legend className="pr-2 text-sm font-semibold">{title}</legend>
      <p className="text-xs leading-5 text-muted-foreground">{description}</p>
      {children}
    </fieldset>
  )
}

const TELEGRAM_FAILURE_MESSAGES: Record<string, string> = {
  secret_store_unavailable: "Secure credential storage is unavailable.",
  telegram_bot_not_administrator: "Bot is not an administrator for this target.",
  telegram_credential_missing: "Bot credential is missing.",
  telegram_credential_unavailable: "Bot credential is unavailable.",
  telegram_destination_changed_during_check: "Destination changed during verification. Run the check again.",
  telegram_destination_check_ambiguous: "Telegram returned an unclear verification result. Run the check again.",
  telegram_destination_check_failed: "Destination verification could not complete.",
  telegram_destination_connect_failed: "Telegram API could not be reached for this destination.",
  telegram_destination_missing: "Destination no longer exists.",
  telegram_destination_rate_limited: "Telegram temporarily limited verification requests. Try again later.",
  telegram_destination_secret_missing: "Bot credential is missing.",
  telegram_proxy_address_blocked: "Proxy endpoint is blocked by deployment policy.",
  telegram_proxy_changed_during_check: "Proxy changed during verification. Run the check again.",
  telegram_proxy_client_initialization_failed: "Proxy connection could not be initialized.",
  telegram_proxy_credentials_incomplete: "Proxy username and password must be supplied together.",
  telegram_proxy_disabled: "Assigned proxy profile is disabled.",
  telegram_proxy_dns_failed: "Proxy hostname could not be resolved.",
  telegram_proxy_dns_invalid: "Proxy hostname is invalid.",
  telegram_proxy_egress_policy_invalid: "Proxy route is blocked by deployment policy.",
  telegram_proxy_host_invalid: "Proxy host is invalid.",
  telegram_proxy_missing: "Assigned proxy profile no longer exists.",
  telegram_proxy_not_ready: "Assigned proxy profile is not ready.",
  telegram_proxy_port_blocked: "Proxy port is blocked by deployment policy.",
  telegram_proxy_unreachable: "Proxy endpoint could not be reached.",
  telegram_target_invalid: "Telegram target is invalid.",
}

const TELEGRAM_ACTION_ERRORS: Record<string, { title: string; message: string }> = {
  secret_store_unavailable: {
    title: "Secret storage unavailable",
    message: "Secure credential storage is unavailable. Try again after deployment configuration is restored.",
  },
  telegram_bot_not_administrator: {
    title: "Administrator permission required",
    message: "Add the bot as an administrator for this target, then run the check again.",
  },
  telegram_credential_missing: {
    title: "Bot credential required",
    message: "Add or rotate the write-only bot token, then retry.",
  },
  telegram_credential_unavailable: {
    title: "Bot credential unavailable",
    message: "Stored bot credential could not be used. Rotate it, then retry.",
  },
  telegram_destination_conflict: {
    title: "Destination already exists",
    message: "Use a distinct destination name and Telegram target.",
  },
  telegram_destination_has_dependencies: {
    title: "Destination cannot be deleted",
    message: "This destination is still referenced. Review dependencies before deleting it.",
  },
  telegram_destination_not_found: {
    title: "Destination not found",
    message: "Destination may have been removed. Refresh Settings and retry.",
  },
  telegram_proxy_has_dependencies: {
    title: "Proxy cannot be deleted",
    message: "This proxy is still assigned to a destination. Remove assignments first.",
  },
  telegram_proxy_host_invalid: {
    title: "Invalid proxy host",
    message: "Enter a plain hostname without a scheme.",
  },
  telegram_proxy_name_conflict: {
    title: "Proxy name already exists",
    message: "Use a distinct proxy profile name.",
  },
  telegram_proxy_not_found: {
    title: "Proxy profile not found",
    message: "Proxy profile may have been removed. Select another route and retry.",
  },
  telegram_proxy_port_blocked: {
    title: "Proxy port blocked",
    message: "Choose a port allowed by deployment policy.",
  },
  telegram_target_invalid: {
    title: "Invalid Telegram target",
    message: "Use @channel, a numeric Bot API chat ID, or a supported Telegram URL.",
  },
}

function telegramFailureMessage(code: string) {
  return TELEGRAM_FAILURE_MESSAGES[code]
    ?? "Connection check could not complete. Review this destination and run the check again."
}

function telegramActionError(cause: unknown, fallbackTitle: string) {
  if (cause instanceof ApiError && cause.status === 401) {
    return {
      title: "Application sign-in required",
      message: "Your application session is unavailable. Sign in to NewsCraft, then retry.",
    }
  }
  if (cause instanceof ApiError && cause.status === 403) {
    return {
      title: "Insufficient permission",
      message: "Authenticated principal does not have permission for this Settings mutation.",
    }
  }
  const code = telegramApiErrorCode(cause)
  return code && TELEGRAM_ACTION_ERRORS[code]
    ? TELEGRAM_ACTION_ERRORS[code]
    : { title: fallbackTitle, message: "Request could not be completed. Review the current settings and retry." }
}

function telegramApiErrorCode(cause: unknown) {
  if (!(cause instanceof ApiError) || !cause.body) return null
  try {
    const payload = JSON.parse(cause.body) as { detail?: { code?: unknown } }
    return typeof payload.detail?.code === "string" ? payload.detail.code : null
  } catch {
    return null
  }
}

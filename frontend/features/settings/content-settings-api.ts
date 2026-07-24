import { API_BASE_URL, ApiError, apiRequest } from "@/lib/http"

type JsonMethod = "POST" | "PATCH"

const json = (method: JsonMethod, body?: unknown, headers?: Record<string, string>): RequestInit => ({
  method,
  headers: { "content-type": "application/json", ...headers },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
})

const id = (value: string) => encodeURIComponent(value)

async function apiRequestVoid(path: string, init?: RequestInit) {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) {
    throw new ApiError(response.statusText || "Request failed", response.status, await response.text())
  }
}

export type LLMProviderSettings = {
  timeoutSeconds: number
  maxInputTokens: number
  maxOutputTokens: number
  researchBudgets: Record<string, unknown>
  pricing: { inputUsdPerMillion: number; outputUsdPerMillion: number }
  attributionHeaders: { httpReferer: string | null; appTitle: string }
}

export type LLMProvider = {
  id: string
  name: string
  protocol: "openai_compatible" | "fake"
  baseUrl: string | null
  defaultModel: string
  enabled: boolean
  configured: boolean
  settings: LLMProviderSettings
  healthStatus: "unchecked" | "healthy" | "unhealthy"
  generationCapability: "unknown" | "ready" | "unavailable"
  researchCapability: "unknown" | "ready" | "unavailable"
  generationReady: boolean
  researchReady: boolean
  failureCode: string | null
  lastCheckedAt: string | null
  ownership: "system_managed" | "operator_managed"
}

export type LLMProviderInput = {
  name: string
  baseUrl: string
  defaultModel: string
  apiKey: string
  enabled?: boolean
  settings?: Partial<LLMProviderSettings>
}

export type LLMProviderDependencies = {
  automations: number
  generationRuns: number
  researchRuns: number
  activeJobs: number
  blocked: boolean
}

type BackendLLMProvider = {
  id: string
  name: string
  protocol: LLMProvider["protocol"]
  base_url: string | null
  default_model: string
  enabled: boolean
  configured: boolean
  settings: {
    timeout_seconds: number
    max_input_tokens: number
    max_output_tokens: number
    research_budgets: Record<string, unknown>
    pricing: { input_usd_per_million: number; output_usd_per_million: number }
    attribution_headers: { http_referer: string | null; app_title: string }
  }
  health_status: LLMProvider["healthStatus"]
  generation_capability: LLMProvider["generationCapability"]
  research_capability: LLMProvider["researchCapability"]
  generation_ready: boolean
  research_ready: boolean
  failure_code: string | null
  last_checked_at: string | null
  ownership: LLMProvider["ownership"]
}

function mapProvider(row: BackendLLMProvider): LLMProvider {
  return {
    id: row.id,
    name: row.name,
    protocol: row.protocol,
    baseUrl: row.base_url,
    defaultModel: row.default_model,
    enabled: row.enabled,
    configured: row.configured,
    settings: {
      timeoutSeconds: row.settings.timeout_seconds,
      maxInputTokens: row.settings.max_input_tokens,
      maxOutputTokens: row.settings.max_output_tokens,
      researchBudgets: row.settings.research_budgets,
      pricing: {
        inputUsdPerMillion: Number(row.settings.pricing.input_usd_per_million),
        outputUsdPerMillion: Number(row.settings.pricing.output_usd_per_million),
      },
      attributionHeaders: {
        httpReferer: row.settings.attribution_headers.http_referer,
        appTitle: row.settings.attribution_headers.app_title,
      },
    },
    healthStatus: row.health_status,
    generationCapability: row.generation_capability,
    researchCapability: row.research_capability,
    generationReady: row.generation_ready,
    researchReady: row.research_ready,
    failureCode: row.failure_code,
    lastCheckedAt: row.last_checked_at,
    ownership: row.ownership,
  }
}

function providerSettingsBody(settings: Partial<LLMProviderSettings> | undefined) {
  if (!settings) return undefined
  return {
    ...(settings.timeoutSeconds === undefined ? {} : { timeout_seconds: settings.timeoutSeconds }),
    ...(settings.maxInputTokens === undefined ? {} : { max_input_tokens: settings.maxInputTokens }),
    ...(settings.maxOutputTokens === undefined ? {} : { max_output_tokens: settings.maxOutputTokens }),
    ...(settings.researchBudgets === undefined ? {} : { research_budgets: settings.researchBudgets }),
    ...(settings.pricing === undefined ? {} : {
      pricing: {
        input_usd_per_million: settings.pricing.inputUsdPerMillion,
        output_usd_per_million: settings.pricing.outputUsdPerMillion,
      },
    }),
    ...(settings.attributionHeaders === undefined ? {} : {
      attribution_headers: {
        http_referer: settings.attributionHeaders.httpReferer,
        app_title: settings.attributionHeaders.appTitle,
      },
    }),
  }
}

export async function getLLMProviders() {
  return (await apiRequest<BackendLLMProvider[]>("/llm-providers")).map(mapProvider)
}

export async function createLLMProvider(input: LLMProviderInput) {
  return mapProvider(await apiRequest<BackendLLMProvider>("/llm-providers", json("POST", {
    name: input.name,
    protocol: "openai_compatible",
    base_url: input.baseUrl,
    default_model: input.defaultModel,
    api_key: input.apiKey,
    settings: providerSettingsBody(input.settings),
    enabled: input.enabled ?? false,
  })))
}

export async function updateLLMProvider(providerId: string, input: Partial<Omit<LLMProviderInput, "apiKey" | "enabled">>) {
  return mapProvider(await apiRequest<BackendLLMProvider>(`/llm-providers/${id(providerId)}`, json("PATCH", {
    ...(input.name === undefined ? {} : { name: input.name }),
    ...(input.baseUrl === undefined ? {} : { base_url: input.baseUrl }),
    ...(input.defaultModel === undefined ? {} : { default_model: input.defaultModel }),
    ...(input.settings === undefined ? {} : { settings: providerSettingsBody(input.settings) }),
  })))
}

export async function rotateLLMProviderKey(providerId: string, apiKey: string) {
  return mapProvider(await apiRequest<BackendLLMProvider>(
    `/llm-providers/${id(providerId)}/rotate-secret`,
    json("POST", { secret: apiKey })
  ))
}

export async function testLLMProvider(providerId: string) {
  return mapProvider(await apiRequest<BackendLLMProvider>(`/llm-providers/${id(providerId)}/test`, { method: "POST" }))
}

export async function setLLMProviderEnabled(providerId: string, enabled: boolean) {
  return mapProvider(await apiRequest<BackendLLMProvider>(
    `/llm-providers/${id(providerId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" }
  ))
}

export async function getLLMProviderDependencies(providerId: string): Promise<LLMProviderDependencies> {
  const row = await apiRequest<{
    automations: number
    generation_runs: number
    research_runs: number
    active_jobs: number
    blocked: boolean
  }>(`/llm-providers/${id(providerId)}/dependencies`)
  return {
    automations: row.automations,
    generationRuns: row.generation_runs,
    researchRuns: row.research_runs,
    activeJobs: row.active_jobs,
    blocked: row.blocked,
  }
}

export const deleteLLMProvider = (providerId: string) =>
  apiRequestVoid(`/llm-providers/${id(providerId)}`, { method: "DELETE" })

export type TelegramProxy = {
  id: string
  name: string
  proxyType: "http_connect" | "socks5"
  host: string
  port: number
  enabled: boolean
  credentialsConfigured: boolean
  reachabilityStatus: string
  failureCode: string | null
  lastCheckedAt: string | null
}

export type TelegramDestination = {
  id: string
  name: string
  targetRef: string
  canonicalTarget: string
  targetType: "username" | "numeric_id" | "legacy"
  enabled: boolean
  healthStatus: string
  configured: boolean
  proxyProfileId: string | null
  connectionRoute: string
  proxyHealthStatus: string
  telegramHealthStatus: string
  botHealthStatus: string
  targetHealthStatus: string
  administratorStatus: string
  failureCode: string | null
  verifiedBotUsername: string | null
  verifiedChatTitle: string | null
  lastCheckedAt: string | null
}

type BackendTelegramProxy = {
  id: string
  name: string
  proxy_type: TelegramProxy["proxyType"]
  host: string
  port: number
  enabled: boolean
  credentials_configured: boolean
  reachability_status: string
  failure_code: string | null
  last_checked_at: string | null
}

type BackendTelegramDestination = {
  id: string
  name: string
  target_ref: string
  canonical_target: string
  target_type: TelegramDestination["targetType"]
  enabled: boolean
  health_status: string
  configured: boolean
  proxy_profile_id: string | null
  connection_route: string
  proxy_health_status: string
  telegram_health_status: string
  bot_health_status: string
  target_health_status: string
  administrator_status: string
  failure_code: string | null
  verified_bot_username: string | null
  verified_chat_title: string | null
  last_checked_at: string | null
}

type BackendJob = { job_id: string; status: string; deduplicated: boolean }
type Accepted<T, K extends string> = { [P in K]: T } & { job: BackendJob }

const mapProxy = (row: BackendTelegramProxy): TelegramProxy => ({
  id: row.id,
  name: row.name,
  proxyType: row.proxy_type,
  host: row.host,
  port: row.port,
  enabled: row.enabled,
  credentialsConfigured: row.credentials_configured,
  reachabilityStatus: row.reachability_status,
  failureCode: row.failure_code,
  lastCheckedAt: row.last_checked_at,
})

const mapDestination = (row: BackendTelegramDestination): TelegramDestination => ({
  id: row.id,
  name: row.name,
  targetRef: row.target_ref,
  canonicalTarget: row.canonical_target,
  targetType: row.target_type,
  enabled: row.enabled,
  healthStatus: row.health_status,
  configured: row.configured,
  proxyProfileId: row.proxy_profile_id,
  connectionRoute: row.connection_route,
  proxyHealthStatus: row.proxy_health_status,
  telegramHealthStatus: row.telegram_health_status,
  botHealthStatus: row.bot_health_status,
  targetHealthStatus: row.target_health_status,
  administratorStatus: row.administrator_status,
  failureCode: row.failure_code,
  verifiedBotUsername: row.verified_bot_username,
  verifiedChatTitle: row.verified_chat_title,
  lastCheckedAt: row.last_checked_at,
})

export async function getTelegramDestinations() {
  return (await apiRequest<BackendTelegramDestination[]>("/telegram/destinations")).map(mapDestination)
}

export async function createTelegramDestination(input: {
  name: string
  target: string
  botToken: string
  proxyProfileId: string | null
}) {
  const row = await apiRequest<Accepted<BackendTelegramDestination, "destination">>("/telegram/destinations", json("POST", {
    name: input.name,
    target: input.target,
    bot_token: input.botToken,
    proxy_profile_id: input.proxyProfileId,
  }))
  return { destination: mapDestination(row.destination), jobId: row.job.job_id }
}

export async function updateTelegramDestination(destinationId: string, input: {
  name?: string
  target?: string
  proxyProfileId?: string | null
}) {
  const row = await apiRequest<Accepted<BackendTelegramDestination, "destination">>(
    `/telegram/destinations/${id(destinationId)}`,
    json("PATCH", {
      ...(input.name === undefined ? {} : { name: input.name }),
      ...(input.target === undefined ? {} : { target: input.target }),
      ...(input.proxyProfileId === undefined ? {} : { proxy_profile_id: input.proxyProfileId }),
    })
  )
  return { destination: mapDestination(row.destination), jobId: row.job.job_id }
}

export async function rotateTelegramToken(destinationId: string, botToken: string) {
  const row = await apiRequest<Accepted<BackendTelegramDestination, "destination">>(
    `/telegram/destinations/${id(destinationId)}/rotate-token`,
    json("POST", { secret: botToken })
  )
  return { destination: mapDestination(row.destination), jobId: row.job.job_id }
}

export async function recheckTelegramDestination(destinationId: string) {
  const row = await apiRequest<Accepted<BackendTelegramDestination, "destination">>(
    `/telegram/destinations/${id(destinationId)}/recheck`,
    { method: "POST" }
  )
  return { destination: mapDestination(row.destination), jobId: row.job.job_id }
}

export async function setTelegramDestinationEnabled(destinationId: string, enabled: boolean) {
  return mapDestination(await apiRequest<BackendTelegramDestination>(
    `/telegram/destinations/${id(destinationId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" }
  ))
}

export async function getTelegramDestinationDependencies(destinationId: string) {
  const row = await apiRequest<{
    automations: number
    publish_jobs: number
    publications: number
    active_jobs: number
    blocked: boolean
  }>(`/telegram/destinations/${id(destinationId)}/dependencies`)
  return {
    automations: row.automations,
    publishJobs: row.publish_jobs,
    publications: row.publications,
    activeJobs: row.active_jobs,
    blocked: row.blocked,
  }
}

export const deleteTelegramDestination = (destinationId: string) =>
  apiRequestVoid(`/telegram/destinations/${id(destinationId)}`, { method: "DELETE" })

export async function getTelegramProxies() {
  return (await apiRequest<BackendTelegramProxy[]>("/telegram/proxies")).map(mapProxy)
}

export async function createTelegramProxy(input: {
  name: string
  proxyType: TelegramProxy["proxyType"]
  host: string
  port: number
  username?: string
  password?: string
}) {
  const row = await apiRequest<Accepted<BackendTelegramProxy, "proxy">>("/telegram/proxies", json("POST", {
    name: input.name,
    proxy_type: input.proxyType,
    host: input.host,
    port: input.port,
    ...(input.username ? { username: input.username, password: input.password } : {}),
  }))
  return { proxy: mapProxy(row.proxy), jobId: row.job.job_id }
}

export async function updateTelegramProxy(proxyId: string, input: {
  name?: string
  proxyType?: TelegramProxy["proxyType"]
  host?: string
  port?: number
}) {
  const row = await apiRequest<Accepted<BackendTelegramProxy, "proxy">>(
    `/telegram/proxies/${id(proxyId)}`,
    json("PATCH", {
      ...(input.name === undefined ? {} : { name: input.name }),
      ...(input.proxyType === undefined ? {} : { proxy_type: input.proxyType }),
      ...(input.host === undefined ? {} : { host: input.host }),
      ...(input.port === undefined ? {} : { port: input.port }),
    })
  )
  return { proxy: mapProxy(row.proxy), jobId: row.job.job_id }
}

export async function rotateTelegramProxyCredentials(proxyId: string, username?: string, password?: string) {
  const row = await apiRequest<Accepted<BackendTelegramProxy, "proxy">>(
    `/telegram/proxies/${id(proxyId)}/rotate-credentials`,
    json("POST", username ? { username, password } : {})
  )
  return { proxy: mapProxy(row.proxy), jobId: row.job.job_id }
}

export async function recheckTelegramProxy(proxyId: string) {
  const row = await apiRequest<Accepted<BackendTelegramProxy, "proxy">>(
    `/telegram/proxies/${id(proxyId)}/recheck`,
    { method: "POST" }
  )
  return { proxy: mapProxy(row.proxy), jobId: row.job.job_id }
}

export async function setTelegramProxyEnabled(proxyId: string, enabled: boolean) {
  return mapProxy(await apiRequest<BackendTelegramProxy>(
    `/telegram/proxies/${id(proxyId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" }
  ))
}

export async function getTelegramProxyDependencies(proxyId: string) {
  const row = await apiRequest<{ destinations: number; blocked: boolean }>(
    `/telegram/proxies/${id(proxyId)}/dependencies`
  )
  return row
}

export const deleteTelegramProxy = (proxyId: string) =>
  apiRequestVoid(`/telegram/proxies/${id(proxyId)}`, { method: "DELETE" })

export async function getTelegramCheck(jobId: string) {
  return apiRequest<{
    job_id: string
    resource_type: "destination" | "proxy"
    resource_id: string
    status: string
    progress: number
    progress_message: string | null
    error_code: string | null
  }>(`/telegram/destination-checks/${id(jobId)}`)
}

export type CodexConnection = {
  id: string
  deviceName: string
  scopes: string[]
  status: "green" | "yellow" | "gray" | "red"
  connectionState: "active" | "revoked"
  failureCode: string | null
  expiresAt: string
  lastHeartbeatAt: string | null
  lastRotatedAt: string | null
}

type BackendCodexConnection = {
  id: string
  device_name: string
  scopes: string[]
  status: CodexConnection["status"]
  connection_state: CodexConnection["connectionState"]
  failure_code: string | null
  expires_at: string
  last_heartbeat_at: string | null
  last_rotated_at: string | null
}

const mapConnection = (row: BackendCodexConnection): CodexConnection => ({
  id: row.id,
  deviceName: row.device_name,
  scopes: row.scopes,
  status: row.status,
  connectionState: row.connection_state,
  failureCode: row.failure_code,
  expiresAt: row.expires_at,
  lastHeartbeatAt: row.last_heartbeat_at,
  lastRotatedAt: row.last_rotated_at,
})

export async function getCodexConnections() {
  return (await apiRequest<BackendCodexConnection[]>("/codex-gateway/connections")).map(mapConnection)
}

export async function createCodexPairingSession(deviceName: string, scopes: string[]) {
  const row = await apiRequest<{
    id: string
    device_name: string
    scopes: string[]
    status: string
    expires_at: string
    pairing_code: string
    local_command: string
  }>("/codex-gateway/pairing-sessions", json("POST", {
    device_name: deviceName,
    scopes,
    confirm_write_scopes: scopes.some((scope) => scope.endsWith(":write")),
  }))
  return {
    id: row.id,
    deviceName: row.device_name,
    scopes: row.scopes,
    status: row.status,
    expiresAt: row.expires_at,
    pairingCode: row.pairing_code,
    localCommand: row.local_command,
  }
}

export async function rotateCodexConnection(connectionId: string) {
  const key = crypto.randomUUID()
  const row = await apiRequest<{ connection: BackendCodexConnection; credential: string }>(
    `/codex-gateway/connections/${id(connectionId)}/rotate`,
    { method: "POST", headers: { "Idempotency-Key": key } }
  )
  return { connection: mapConnection(row.connection), credential: row.credential }
}

export const revokeCodexConnection = (connectionId: string) =>
  apiRequestVoid(`/codex-gateway/connections/${id(connectionId)}`, { method: "DELETE" })

export async function getCodexActivity(connectionId?: string) {
  const query = connectionId ? `?connection_id=${id(connectionId)}&limit=8` : "?limit=8"
  const rows = await apiRequest<Array<{
    id: string
    connection_id: string | null
    action: string
    outcome: string
    reason_code: string | null
    created_at: string
  }>>(`/codex-gateway/activity${query}`)
  return rows.map((row) => ({
    id: row.id,
    connectionId: row.connection_id,
    action: row.action,
    outcome: row.outcome,
    reasonCode: row.reason_code,
    createdAt: row.created_at,
  }))
}

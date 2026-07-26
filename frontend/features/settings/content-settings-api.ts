import type { components } from "@/lib/api/generated"
import { camelize } from "@/lib/camelize"
import { apiRequest, apiRequestVoid } from "@/lib/http"

type JsonMethod = "POST" | "PATCH"

const json = (method: JsonMethod, body?: unknown, headers?: Record<string, string>): RequestInit => ({
  method,
  headers: { "content-type": "application/json", ...headers },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
})

const id = (value: string) => encodeURIComponent(value)

type Schemas = components["schemas"]

export type LLMProviderSettings = {
  timeoutSeconds: number
  maxInputTokens: number
  maxOutputTokens: number
  researchBudgets: Record<string, unknown>
  pricing: { inputUsdPerMillion: number; outputUsdPerMillion: number }
  attributionHeaders: { httpReferer: string | null; appTitle: string }
}

export type LLMProvider = Schemas["LLMProviderOut"]

export type LLMProviderInput = {
  name: string
  baseUrl: string
  defaultModel: string
  apiKey: string
  enabled?: boolean
  settings?: Partial<LLMProviderSettings>
}

export type LLMProviderDependencies = Schemas["LLMProviderDependenciesOut"]

type BackendLLMProvider = Schemas["LLMProviderOut"]

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
  return apiRequest<BackendLLMProvider[]>("/llm-providers")
}

export async function createLLMProvider(input: LLMProviderInput) {
  return apiRequest<BackendLLMProvider>("/llm-providers", json("POST", {
    name: input.name,
    protocol: "openai_compatible",
    base_url: input.baseUrl,
    default_model: input.defaultModel,
    api_key: input.apiKey,
    settings: providerSettingsBody(input.settings),
    enabled: input.enabled ?? false,
  }))
}

export async function updateLLMProvider(providerId: string, input: Partial<Omit<LLMProviderInput, "apiKey" | "enabled">>) {
  return apiRequest<BackendLLMProvider>(`/llm-providers/${id(providerId)}`, json("PATCH", {
    ...(input.name === undefined ? {} : { name: input.name }),
    ...(input.baseUrl === undefined ? {} : { base_url: input.baseUrl }),
    ...(input.defaultModel === undefined ? {} : { default_model: input.defaultModel }),
    ...(input.settings === undefined ? {} : { settings: providerSettingsBody(input.settings) }),
  }))
}

export async function rotateLLMProviderKey(providerId: string, apiKey: string) {
  return apiRequest<BackendLLMProvider>(
    `/llm-providers/${id(providerId)}/rotate-secret`,
    json("POST", { secret: apiKey })
  )
}

export async function testLLMProvider(providerId: string) {
  return apiRequest<BackendLLMProvider>(`/llm-providers/${id(providerId)}/test`, { method: "POST" })
}

export async function setLLMProviderEnabled(providerId: string, enabled: boolean) {
  return apiRequest<BackendLLMProvider>(
    `/llm-providers/${id(providerId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" }
  )
}

export async function getLLMProviderDependencies(providerId: string): Promise<LLMProviderDependencies> {
  return apiRequest<LLMProviderDependencies>(
    `/llm-providers/${id(providerId)}/dependencies`
  )
}

export const deleteLLMProvider = (providerId: string) =>
  apiRequestVoid(`/llm-providers/${id(providerId)}`, { method: "DELETE" })

export type TelegramProxy = Schemas["TelegramProxyOut"]
export type TelegramDestination = Schemas["TelegramDestinationOut"]

type BackendTelegramProxy = Schemas["TelegramProxyOut"]
type BackendTelegramDestination = Schemas["TelegramDestinationOut"]
type BackendJob = Schemas["JobAcceptedOut"]
type Accepted<T, K extends string> = { [P in K]: T } & { job: BackendJob }

export async function getTelegramDestinations() {
  return apiRequest<BackendTelegramDestination[]>("/telegram/destinations")
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
  return { destination: row.destination, jobId: row.job.job_id }
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
  return { destination: row.destination, jobId: row.job.job_id }
}

export async function rotateTelegramToken(destinationId: string, botToken: string) {
  const row = await apiRequest<Accepted<BackendTelegramDestination, "destination">>(
    `/telegram/destinations/${id(destinationId)}/rotate-token`,
    json("POST", { secret: botToken })
  )
  return { destination: row.destination, jobId: row.job.job_id }
}

export async function recheckTelegramDestination(destinationId: string) {
  const row = await apiRequest<Accepted<BackendTelegramDestination, "destination">>(
    `/telegram/destinations/${id(destinationId)}/recheck`,
    { method: "POST" }
  )
  return { destination: row.destination, jobId: row.job.job_id }
}

export async function setTelegramDestinationEnabled(destinationId: string, enabled: boolean) {
  return apiRequest<BackendTelegramDestination>(
    `/telegram/destinations/${id(destinationId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" }
  )
}

export async function getTelegramDestinationDependencies(destinationId: string) {
  return camelize(await apiRequest<Schemas["TelegramDestinationDependenciesOut"]>(
    `/telegram/destinations/${id(destinationId)}/dependencies`
  ))
}

export const deleteTelegramDestination = (destinationId: string) =>
  apiRequestVoid(`/telegram/destinations/${id(destinationId)}`, { method: "DELETE" })

export async function getTelegramProxies() {
  return apiRequest<BackendTelegramProxy[]>("/telegram/proxies")
}

export async function createTelegramProxy(input: {
  name: string
  proxyType: TelegramProxy["proxy_type"]
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
  return { proxy: row.proxy, jobId: row.job.job_id }
}

export async function updateTelegramProxy(proxyId: string, input: {
  name?: string
  proxyType?: TelegramProxy["proxy_type"]
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
  return { proxy: row.proxy, jobId: row.job.job_id }
}

export async function rotateTelegramProxyCredentials(proxyId: string, username?: string, password?: string) {
  const row = await apiRequest<Accepted<BackendTelegramProxy, "proxy">>(
    `/telegram/proxies/${id(proxyId)}/rotate-credentials`,
    json("POST", username ? { username, password } : {})
  )
  return { proxy: row.proxy, jobId: row.job.job_id }
}

export async function recheckTelegramProxy(proxyId: string) {
  const row = await apiRequest<Accepted<BackendTelegramProxy, "proxy">>(
    `/telegram/proxies/${id(proxyId)}/recheck`,
    { method: "POST" }
  )
  return { proxy: row.proxy, jobId: row.job.job_id }
}

export async function setTelegramProxyEnabled(proxyId: string, enabled: boolean) {
  return apiRequest<BackendTelegramProxy>(
    `/telegram/proxies/${id(proxyId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" }
  )
}

export async function getTelegramProxyDependencies(proxyId: string) {
  const row = await apiRequest<Schemas["TelegramProxyDependenciesOut"]>(
    `/telegram/proxies/${id(proxyId)}/dependencies`
  )
  return row
}

export const deleteTelegramProxy = (proxyId: string) =>
  apiRequestVoid(`/telegram/proxies/${id(proxyId)}`, { method: "DELETE" })

export type CodexConnection = Schemas["CodexConnectionOut"]
export type CodexActivity = Schemas["GatewayActivityOut"]
export type CodexPairingSession = Schemas["PairingSessionCreatedOut"]

type BackendCodexConnection = Schemas["CodexConnectionOut"]

export async function getCodexConnections() {
  return apiRequest<BackendCodexConnection[]>("/codex-gateway/connections")
}

export async function createCodexPairingSession(deviceName: string, scopes: string[]): Promise<CodexPairingSession> {
  return apiRequest<CodexPairingSession>("/codex-gateway/pairing-sessions", json("POST", {
    device_name: deviceName,
    scopes,
    confirm_write_scopes: scopes.some((scope) => scope.endsWith(":write")),
  }))
}

export async function rotateCodexConnection(connectionId: string) {
  const key = crypto.randomUUID()
  const row = await apiRequest<{ connection: BackendCodexConnection; credential: string }>(
    `/codex-gateway/connections/${id(connectionId)}/rotate`,
    { method: "POST", headers: { "Idempotency-Key": key } }
  )
  return row
}

export const revokeCodexConnection = (connectionId: string) =>
  apiRequestVoid(`/codex-gateway/connections/${id(connectionId)}`, { method: "DELETE" })

export async function getCodexActivity(connectionId?: string): Promise<CodexActivity[]> {
  const query = connectionId ? `?connection_id=${id(connectionId)}&limit=8` : "?limit=8"
  return apiRequest<CodexActivity[]>(`/codex-gateway/activity${query}`)
}

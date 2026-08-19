import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import {
  activatePromptVersion,
  getPromptTemplates,
  getPromptVersions,
} from "@/features/automations/telegram-api"
import {
  createCodexPairingSession,
  createLLMProvider,
  deleteTelegramDestination,
  deleteLLMProvider,
  createTelegramDestination,
  getCodexActivity,
  getCodexConnections,
  getLLMProviderDependencies,
  getLLMProviders,
  getTelegramDestinationDependencies,
  getTelegramDestinations,
  getTelegramProxies,
  recheckTelegramDestination,
  rotateLLMProviderKey,
  setLLMProviderEnabled,
  setTelegramDestinationEnabled,
  testLLMProvider,
  updateTelegramDestination,
} from "@/features/settings/content-settings-api"
import { ContentSettingsPage } from "@/features/settings/content-settings-page"
import { getDateTimeSettings } from "@/features/settings/date-time-api"
import { fetchRetentionPolicy } from "@/features/operations/api"
import { ApiError } from "@/lib/http"

vi.mock("@/features/automations/telegram-api", () => ({
  activatePromptVersion: vi.fn(),
  createPromptVersion: vi.fn(),
  getPromptTemplates: vi.fn(),
  getPromptVersions: vi.fn(),
}))

vi.mock("@/features/settings/content-settings-api", () => ({
  createCodexPairingSession: vi.fn(),
  createLLMProvider: vi.fn(),
  createTelegramDestination: vi.fn(),
  createTelegramProxy: vi.fn(),
  deleteLLMProvider: vi.fn(),
  deleteTelegramDestination: vi.fn(),
  deleteTelegramProxy: vi.fn(),
  getCodexActivity: vi.fn(),
  getCodexConnections: vi.fn(),
  getLLMProviderDependencies: vi.fn(),
  getLLMProviders: vi.fn(),
  getTelegramDestinationDependencies: vi.fn(),
  getTelegramDestinations: vi.fn(),
  getTelegramProxies: vi.fn(),
  getTelegramProxyDependencies: vi.fn(),
  recheckTelegramDestination: vi.fn(),
  recheckTelegramProxy: vi.fn(),
  revokeCodexConnection: vi.fn(),
  rotateCodexConnection: vi.fn(),
  rotateLLMProviderKey: vi.fn(),
  rotateTelegramToken: vi.fn(),
  setLLMProviderEnabled: vi.fn(),
  setTelegramDestinationEnabled: vi.fn(),
  setTelegramProxyEnabled: vi.fn(),
  testLLMProvider: vi.fn(),
  updateLLMProvider: vi.fn(),
  updateTelegramDestination: vi.fn(),
  updateTelegramProxy: vi.fn(),
}))

vi.mock("@/features/operations/api", () => ({
  createRetentionPreview: vi.fn(),
  enqueueRetentionRun: vi.fn(),
  fetchRetentionPolicy: vi.fn(),
  updateRetentionPolicy: vi.fn(),
}))

vi.mock("@/features/settings/date-time-api", () => ({
  getDateTimeSettings: vi.fn(),
  updateDateTimeSettings: vi.fn(),
}))

const template = {
  id: "22222222-2222-4222-8222-222222222222",
  purposeKey: "telegram_rewrite",
  name: "Telegram rewrite",
  description: "Immutable newsroom prompt",
}

const promptVersion = {
  id: "33333333-3333-4333-8333-333333333333",
  prompt_template_id: template.id,
  version: 4,
  system_template: "Use evidence only",
  user_template: "{source_text}",
  output_schema_version: "telegram_rewrite.v1",
  output_schema: {},
  checksum_sha256: "a".repeat(64),
  is_active: true,
  activated_at: "2026-07-20T08:00:00Z",
  activated_by_type: "human_admin",
  activated_by_id: "operator",
  activation_reason: "Approved newsroom baseline",
  created_at: "2026-07-20T08:00:00Z",
}

const provider = {
  id: "44444444-4444-4444-8444-444444444444",
  name: "Newsroom model",
  protocol: "openai_compatible" as const,
  base_url: "https://llm.example/v1",
  default_model: "openai/gpt-5-mini",
  enabled: true,
  configured: true,
  settings: {
    timeout_seconds: 60,
    max_input_tokens: 60_000,
    max_output_tokens: 12_000,
    pricing: { input_usd_per_million: "0", output_usd_per_million: "0" },
    attribution_headers: { http_referer: null, app_title: "NewsCraft" },
  },
  health_status: "healthy" as const,
  generation_capability: "ready" as const,
  research_capability: "unavailable" as const,
  generation_ready: true,
  research_ready: false,
  failure_code: "research_budget_missing",
  failure_message: "Generation is healthy, but Research is unavailable because research configuration is incomplete.",
  last_checked_at: "2026-07-23T08:00:00Z",
  last_successful_test_at: "2026-07-23T08:00:00Z",
  last_test_latency_ms: 184,
  last_tested_model: "openai/gpt-5-mini",
  ready_for_enablement: true,
  readiness_code: "ready_for_generation",
  readiness_message: "Ready for Generation. Research is Unavailable.",
  ownership: "operator_managed" as const,
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

const proxy = {
  id: "55555555-5555-4555-8555-555555555555",
  name: "Publishing proxy",
  proxy_type: "socks5" as const,
  host: "proxy.example",
  port: 1080,
  enabled: true,
  credentials_configured: true,
  reachability_status: "healthy",
  failure_code: null,
  last_checked_at: "2026-07-23T08:00:00Z",
  last_rotated_at: null,
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

const destination = {
  id: "66666666-6666-4666-8666-666666666666",
  name: "Main channel",
  target_ref: "@newscraft",
  canonical_target: "@newscraft",
  target_type: "username" as const,
  enabled: true,
  health_status: "healthy",
  configured: true,
  proxy_profile_id: proxy.id,
  connection_route: "Publishing proxy",
  proxy_health_status: "healthy",
  telegram_health_status: "healthy",
  bot_health_status: "authenticated",
  target_health_status: "resolved",
  administrator_status: "administrator",
  failure_code: null,
  verified_bot_id: 42,
  verified_bot_username: "newscraft_bot",
  verified_chat_id: -10042,
  verified_chat_title: "NewsCraft",
  verified_chat_type: "channel",
  last_checked_at: "2026-07-23T08:00:00Z",
  last_rotated_at: null,
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

const connection = {
  id: "77777777-7777-4777-8777-777777777777",
  device_name: "Editorial workstation",
  scopes: ["settings:read", "providers:read"],
  status: "green" as const,
  connection_state: "active" as const,
  failure_code: null,
  expires_at: "2026-08-23T08:00:00Z",
  last_heartbeat_at: "2026-07-24T08:00:00Z",
  last_rotated_at: null,
  created_at: "2026-07-23T08:00:00Z",
  credential_fingerprint: "sha256:test",
  revoked_at: null,
}

const retentionPolicy = {
  id: "global" as const,
  raw_payload_days: 30,
  completed_job_days: 90,
  attempt_metadata_days: 90,
  export_artifact_days: 14,
  unreferenced_media_days: 30,
  created_at: "2026-07-24T08:00:00Z",
  updated_at: "2026-07-24T08:00:00Z",
}

describe("ContentSettingsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getPromptTemplates).mockResolvedValue([template])
    vi.mocked(getPromptVersions).mockResolvedValue([promptVersion])
    vi.mocked(getLLMProviders).mockResolvedValue([provider])
    vi.mocked(getLLMProviderDependencies).mockResolvedValue({
      active_jobs: 0,
      automations: 1,
      blocked: false,
      generation_runs: 2,
      research_runs: 3,
    })
    vi.mocked(setLLMProviderEnabled).mockResolvedValue({ ...provider, enabled: false })
    vi.mocked(testLLMProvider).mockResolvedValue(provider)
    vi.mocked(getTelegramProxies).mockResolvedValue([proxy])
    vi.mocked(getTelegramDestinations).mockResolvedValue([destination])
    vi.mocked(getTelegramDestinationDependencies).mockResolvedValue({
      activeJobs: 0,
      automations: 0,
      blocked: false,
      publications: 0,
      publishJobs: 0,
    })
    vi.mocked(recheckTelegramDestination).mockResolvedValue({
      destination,
      jobId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    })
    vi.mocked(setTelegramDestinationEnabled).mockResolvedValue({ ...destination, enabled: false })
    vi.mocked(getCodexConnections).mockResolvedValue([connection])
    vi.mocked(fetchRetentionPolicy).mockResolvedValue(retentionPolicy)
    vi.mocked(getDateTimeSettings).mockResolvedValue({
      timezone: "Asia/Tehran",
      updatedAt: "2026-07-28T11:00:00Z",
    })
    vi.mocked(getCodexActivity).mockResolvedValue([
      {
        id: "88888888-8888-4888-8888-888888888888",
        action: "codex_gateway.heartbeat",
        outcome: "succeeded",
        created_at: "2026-07-24T08:00:00Z",
      },
    ])
  })

  it("renders only the selected category and keeps credential values private", async () => {
    renderSettings()

    expect(await screen.findByRole("heading", { name: "LLM providers" })).toBeInTheDocument()
    expect(getLLMProviders).toHaveBeenCalledTimes(1)
    expect(getTelegramDestinations).not.toHaveBeenCalled()
    expect(screen.queryByText(/bot token/i)).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue(/api[_-]?key/i)).not.toBeInTheDocument()
  })

  it.each([
    ["llm-providers", "LLM providers"],
    ["codex", "Codex connection"],
    ["telegram", "Telegram destinations"],
    ["date-time", "Date & Time"],
    ["retention", "Retention"],
    ["prompts", "Prompt governance"],
  ] as const)("mounts %s without rendering a long Settings page", async (section, heading) => {
    renderSettings({ section })

    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument()
    expect(screen.getAllByRole("region")).toHaveLength(1)
  })

  it("keeps non-Codex settings available when Codex requires authentication", async () => {
    const authenticationRequired = new ApiError(
      "Unauthorized",
      401,
      JSON.stringify({ detail: { code: "authentication_required" } })
    )
    vi.mocked(getCodexConnections).mockRejectedValue(authenticationRequired)
    vi.mocked(getCodexActivity).mockRejectedValue(authenticationRequired)

    renderSettings({ section: "codex" })

    expect(await screen.findByRole("heading", { name: "Codex connection" })).toBeInTheDocument()
    expect(await screen.findByRole("alert")).toHaveTextContent("authentication required")
  })

  it("shows Codex loading feedback while both safe reads are pending", () => {
    vi.mocked(getCodexConnections).mockReturnValue(new Promise(() => undefined))
    vi.mocked(getCodexActivity).mockReturnValue(new Promise(() => undefined))

    renderSettings({ section: "codex" })

    expect(screen.getByText("Checking Codex access").closest('[role="status"]')).toBeInTheDocument()
  })

  it("shows safe empty states when Codex has no connections or activity", async () => {
    vi.mocked(getCodexConnections).mockResolvedValue([])
    vi.mocked(getCodexActivity).mockResolvedValue([])

    renderSettings({ section: "codex" })

    expect(await screen.findByRole("heading", { name: "No Codex connection" })).toBeInTheDocument()
    expect(screen.getByText("No recent gateway activity.")).toBeInTheDocument()
  })

  it("creates a generic provider through one write-only form and resets dirty values", async () => {
    vi.mocked(createLLMProvider).mockResolvedValue({ ...provider, id: "99999999-9999-4999-8999-999999999999" })
    renderSettings({ section: "llm-providers" })

    fireEvent.click(await screen.findByRole("button", { name: "Add provider" }))
    const dialog = screen.getByRole("dialog", { name: "Add LLM provider" })
    const submit = within(dialog).getByRole("button", { name: "Add provider" })
    expect(submit).toBeDisabled()

    fireEvent.change(within(dialog).getByLabelText(/Connection name/), { target: { value: "Custom model" } })
    fireEvent.change(within(dialog).getByLabelText(/Model name/), { target: { value: "vendor/model" } })
    fireEvent.change(within(dialog).getByLabelText(/Base URL/), { target: { value: "http://unsafe.example/v1" } })
    fireEvent.blur(within(dialog).getByLabelText(/Base URL/))
    expect(within(dialog).getByRole("alert")).toHaveTextContent("HTTPS")
    fireEvent.change(within(dialog).getByLabelText(/Base URL/), { target: { value: "https://safe.example/v1" } })
    fireEvent.change(within(dialog).getByLabelText(/API key/), { target: { value: "write-only-value" } })
    fireEvent.click(submit)

    await waitFor(() => expect(createLLMProvider).toHaveBeenCalledWith(expect.objectContaining({
      name: "Custom model",
      baseUrl: "https://safe.example/v1",
      defaultModel: "vendor/model",
      apiKey: "write-only-value",
    })))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add LLM provider" })).not.toBeInTheDocument())
    expect(screen.queryByDisplayValue("write-only-value")).not.toBeInTheDocument()
  })

  it("keeps primary provider actions visible and groups secondary actions in an overflow menu", async () => {
    renderSettings()

    const card = await screen.findByTestId("llm-provider-card")
    expect(within(card).getByRole("heading", { name: provider.name })).toBeInTheDocument()
    expect(within(card).getByText(provider.default_model)).toBeInTheDocument()
    expect(within(card).getByText("Generation")).toBeInTheDocument()
    expect(within(card).getByText("Research")).toBeInTheDocument()
    expect(within(card).getByText("API key")).toBeInTheDocument()
    expect(within(card).getByText("Last checked")).toBeInTheDocument()

    const primaryActions = within(card).getByRole("group", {
      name: `Primary actions for ${provider.name}`,
    })
    expect(within(primaryActions).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Test",
      "Edit",
      "Disable",
    ])
    expect(within(card).queryByText("Rotate key")).not.toBeInTheDocument()

    fireEvent.click(within(card).getByRole("button", {
      name: `More actions for ${provider.name}`,
    }))
    expect(screen.getByRole("menuitem", { name: "Rotate key" })).toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: "Dependencies" })).toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: "Delete provider" })).toHaveClass(
      "text-destructive",
    )
  })

  it("preserves provider test, toggle, dependencies, and key rotation behavior", async () => {
    renderSettings()

    const card = await screen.findByTestId("llm-provider-card")
    fireEvent.click(within(card).getByRole("button", { name: "Test" }))
    await waitFor(() => expect(testLLMProvider).toHaveBeenCalledWith(provider.id))

    fireEvent.click(within(card).getByRole("button", { name: "Disable" }))
    await waitFor(() => expect(setLLMProviderEnabled).toHaveBeenCalledWith(provider.id, false))

    fireEvent.click(within(card).getByRole("button", {
      name: `More actions for ${provider.name}`,
    }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Dependencies" }))
    await waitFor(() => expect(getLLMProviderDependencies).toHaveBeenCalledWith(provider.id))

    fireEvent.click(within(card).getByRole("button", {
      name: `More actions for ${provider.name}`,
    }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Rotate key" }))
    expect(screen.getByRole("dialog", { name: `Rotate key for ${provider.name}` }))
      .toBeInTheDocument()
  })

  it("shows legacy credential recovery and opens a write-only replacement form", async () => {
    vi.mocked(getLLMProviders).mockResolvedValueOnce([{
      ...provider,
      enabled: false,
      health_status: "unhealthy",
      generation_capability: "unavailable",
      research_capability: "unavailable",
      generation_ready: false,
      research_ready: false,
      failure_code: "credential_replacement_required",
    }])
    renderSettings()

    const card = await screen.findByTestId("llm-provider-card")
    expect(within(card).getByRole("alert")).toHaveTextContent(
      "This provider credential can no longer be decrypted. Re-enter the API key to restore the provider connection.",
    )
    fireEvent.click(within(card).getByRole("button", { name: "Replace API key" }))

    expect(screen.getByRole("dialog", { name: `Replace API key for ${provider.name}` }))
      .toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Save API key" })).toBeInTheDocument()
  })

  it("shows genuine application authentication and scope failures without a Settings login flow", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    vi.mocked(deleteLLMProvider).mockRejectedValueOnce(new ApiError(
      "Unauthorized",
      401,
      JSON.stringify({ detail: { code: "authentication_required" } }),
    ))
    renderSettings()

    const card = await screen.findByTestId("llm-provider-card")
    fireEvent.click(within(card).getByRole("button", { name: `More actions for ${provider.name}` }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete provider" }))

    expect(await screen.findByText("Application sign-in required", { selector: "[data-notice-title]" }))
      .toBeInTheDocument()
    expect(screen.getByText(/sign in to NewsCraft, then retry/i)).toBeInTheDocument()
    expect(screen.queryByRole("dialog", { name: /authenticate local operator/i }))
      .not.toBeInTheDocument()

    vi.mocked(deleteLLMProvider).mockRejectedValueOnce(new ApiError(
      "Forbidden",
      403,
      JSON.stringify({ detail: { code: "scope_denied" } }),
    ))
    fireEvent.click(within(card).getByRole("button", { name: `More actions for ${provider.name}` }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete provider" }))

    expect(await screen.findByText("Insufficient permission", { selector: "[data-notice-title]" }))
      .toBeInTheDocument()
    expect(screen.queryByRole("dialog", { name: /authenticate local operator/i }))
      .not.toBeInTheDocument()
  })

  it("never renders Settings-specific operator authentication controls", async () => {
    renderSettings()

    await screen.findByRole("heading", { name: "LLM providers" })
    expect(screen.queryByRole("button", { name: /operator sign in/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/operator secret/i)).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /^sign out$/i })).not.toBeInTheDocument()
  })

  it("keeps encrypted secret-store failures distinct and visible", async () => {
    vi.mocked(createLLMProvider).mockRejectedValue(new ApiError(
      "Service Unavailable",
      503,
      JSON.stringify({ detail: { code: "secret_store_unavailable" } }),
    ))
    renderSettings()

    fireEvent.click(await screen.findByRole("button", { name: "Add provider" }))
    const dialog = screen.getByRole("dialog", { name: "Add LLM provider" })
    fireEvent.change(within(dialog).getByLabelText(/Connection name/), { target: { value: "Secure model" } })
    fireEvent.change(within(dialog).getByLabelText(/Model name/), { target: { value: "vendor/model" } })
    fireEvent.change(within(dialog).getByLabelText(/Base URL/), { target: { value: "https://safe.example/v1" } })
    fireEvent.change(within(dialog).getByLabelText(/API key/), { target: { value: "write-only-value" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Add provider" }))

    expect(await screen.findByText("Secret storage unavailable", { selector: "[data-notice-title]" }))
      .toBeInTheDocument()
    expect(screen.getByText("Secure secret storage is unavailable.")).toBeInTheDocument()
    expect(screen.queryByRole("dialog", { name: /authenticate local operator/i })).not.toBeInTheDocument()
  })

  it.each([
    ["secret_store_unavailable", "Secure secret storage is unavailable."],
    ["secret_store_configuration_invalid", "Secure secret storage is not configured."],
    ["secret_database_unavailable", "Secure secret storage database is unavailable."],
    ["secret_schema_unavailable", "Secure secret storage database schema is unavailable."],
    ["secret_encryption_failed", "The credential could not be encrypted."],
    ["secret_decryption_failed", "This provider credential can no longer be decrypted. Re-enter the API key to restore the provider connection."],
    ["secret_rotation_failed", "The credential could not be rotated. Existing credential remains unchanged."],
  ])("shows actionable provider rotation message for %s", async (code, message) => {
    vi.mocked(rotateLLMProviderKey).mockRejectedValueOnce(new ApiError(
      "Service Unavailable",
      503,
      JSON.stringify({ detail: { code } }),
    ))
    const { queryClient } = renderSettings()
    const invalidate = vi.spyOn(queryClient, "invalidateQueries")

    const card = await screen.findByTestId("llm-provider-card")
    fireEvent.click(within(card).getByRole("button", { name: `More actions for ${provider.name}` }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Rotate key" }))
    const dialog = screen.getByRole("dialog", { name: `Rotate key for ${provider.name}` })
    fireEvent.change(within(dialog).getByLabelText(/New API key/), {
      target: { value: "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "Rotate secret" }))

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(dialog).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/New API key/)).toHaveValue("TEST_PROVIDER_API_KEY_MUST_NOT_LEAK")
    expect(document.body.textContent).not.toContain("TEST_PROVIDER_API_KEY_MUST_NOT_LEAK")
    expect(invalidate).not.toHaveBeenCalled()
  })

  it("clears and closes the API-key form, then refreshes only after rotation succeeds", async () => {
    vi.mocked(rotateLLMProviderKey).mockResolvedValueOnce(provider)
    const { queryClient } = renderSettings()
    const invalidate = vi.spyOn(queryClient, "invalidateQueries")

    const card = await screen.findByTestId("llm-provider-card")
    fireEvent.click(within(card).getByRole("button", { name: `More actions for ${provider.name}` }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Rotate key" }))
    const dialog = screen.getByRole("dialog", { name: `Rotate key for ${provider.name}` })
    fireEvent.change(within(dialog).getByLabelText(/New API key/), {
      target: { value: "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "Rotate secret" }))

    await waitFor(() => expect(rotateLLMProviderKey).toHaveBeenCalledWith(
      provider.id,
      "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK",
    ))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(screen.queryByDisplayValue("TEST_PROVIDER_API_KEY_MUST_NOT_LEAK")).not.toBeInTheDocument()
    expect(await screen.findByText("API key rotated", { selector: "[data-notice-title]" }))
      .toBeInTheDocument()
    expect(invalidate).toHaveBeenCalledTimes(2)
  })

  it("creates a Telegram destination with a reusable route and no auto-publish permission", async () => {
    vi.mocked(createTelegramDestination).mockResolvedValue({
      destination: { ...destination, id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "Backup" },
      jobId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    })
    renderSettings({ section: "telegram" })

    fireEvent.click(await screen.findByRole("button", { name: "Add destination" }))
    const dialog = screen.getByRole("dialog", { name: "Add Telegram destination" })
    fireEvent.change(within(dialog).getByLabelText(/Destination name/), { target: { value: "Backup" } })
    fireEvent.change(within(dialog).getByLabelText(/Channel or group identifier/), { target: { value: "@backup" } })
    fireEvent.change(within(dialog).getByLabelText(/Bot token/), { target: { value: "telegram-write-only" } })
    fireEvent.change(within(dialog).getByLabelText("Connection route"), { target: { value: proxy.id } })
    expect(within(dialog).queryByLabelText(/auto.?publish/i)).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: "Add destination" }))

    await waitFor(() => expect(createTelegramDestination).toHaveBeenCalledWith({
      name: "Backup",
      target: "@backup",
      botToken: "telegram-write-only",
      proxyProfileId: proxy.id,
    }))
    expect(screen.queryByDisplayValue("telegram-write-only")).not.toBeInTheDocument()
  })

  it("renders a compact Telegram card with one status grid and stable action hierarchy", async () => {
    renderSettings({ section: "telegram" })

    const card = await screen.findByTestId("telegram-destination-card")
    expect(within(card).getByRole("heading", { name: destination.name })).toBeInTheDocument()
    expect(within(card).getByText(destination.canonical_target)).toHaveAttribute(
      "title",
      destination.canonical_target,
    )
    expect(within(card).getByText("Target type")).toBeInTheDocument()
    expect(within(card).getByText("Username")).toBeInTheDocument()
    expect(within(card).getByText("Proxy: Publishing proxy")).toBeInTheDocument()
    expect(within(card).getAllByText("Telegram API")).toHaveLength(1)
    expect(within(card).getAllByText("Administrator")).toHaveLength(1)
    expect(within(card).queryByText(/bot token/i)).not.toBeInTheDocument()

    const actions = within(card).getByRole("group", {
      name: `Primary actions for ${destination.name}`,
    })
    expect(within(actions).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Check",
      "Edit",
      "Disable",
    ])
    expect(within(card).queryByText("Rotate bot token")).not.toBeInTheDocument()

    fireEvent.click(within(card).getByRole("button", {
      name: `More actions for ${destination.name}`,
    }))
    expect(screen.getByRole("menuitem", { name: "Rotate bot token" })).toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: "View dependencies" })).toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: "Delete destination" })).toHaveClass(
      "text-destructive",
    )
  })

  it("shows a direct route without duplicating destination status", async () => {
    vi.mocked(getTelegramDestinations).mockResolvedValue([{
      ...destination,
      connection_route: "direct",
      proxy_health_status: "direct",
      proxy_profile_id: null,
    }])
    vi.mocked(getTelegramProxies).mockResolvedValue([])
    renderSettings({ section: "telegram" })

    const card = await screen.findByTestId("telegram-destination-card")
    expect(within(card).getByText("Direct")).toBeInTheDocument()
    expect(within(card).getAllByText("Proxy")).toHaveLength(1)
  })

  it("preserves Telegram check, toggle, dependencies, and delete confirmation behavior", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    vi.mocked(deleteTelegramDestination).mockResolvedValue(undefined)
    renderSettings({ section: "telegram" })

    const card = await screen.findByTestId("telegram-destination-card")
    fireEvent.click(within(card).getByRole("button", { name: "Check" }))
    await waitFor(() => expect(recheckTelegramDestination).toHaveBeenCalledWith(destination.id))

    fireEvent.click(within(card).getByRole("button", { name: "Disable" }))
    await waitFor(() => expect(setTelegramDestinationEnabled).toHaveBeenCalledWith(destination.id, false))

    fireEvent.click(within(card).getByRole("button", { name: `More actions for ${destination.name}` }))
    fireEvent.click(screen.getByRole("menuitem", { name: "View dependencies" }))
    await waitFor(() => expect(getTelegramDestinationDependencies).toHaveBeenCalledWith(destination.id))

    fireEvent.click(within(card).getByRole("button", { name: `More actions for ${destination.name}` }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete destination" }))
    await waitFor(() => expect(deleteTelegramDestination).toHaveBeenCalledWith(destination.id))
    expect(window.confirm).toHaveBeenCalledWith(`Delete ${destination.name}? This cannot be undone.`)
  })

  it("keeps edited Telegram values after a failed save and closes only after success", async () => {
    vi.mocked(updateTelegramDestination).mockRejectedValueOnce(new ApiError(
      "Unprocessable Entity",
      422,
      JSON.stringify({ detail: { code: "telegram_target_invalid", raw: "SECRET_RAW_ERROR" } }),
    ))
    renderSettings({ section: "telegram" })

    const card = await screen.findByTestId("telegram-destination-card")
    fireEvent.click(within(card).getByRole("button", { name: "Edit" }))
    const dialog = screen.getByRole("dialog", { name: `Edit ${destination.name}` })
    const name = within(dialog).getByLabelText(/Destination name/)
    const target = within(dialog).getByLabelText(/Channel or group identifier/)
    fireEvent.change(name, { target: { value: "Updated destination" } })
    fireEvent.change(target, { target: { value: "not valid" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Save destination" }))

    expect(await screen.findByText("Invalid Telegram target", { selector: "[data-notice-title]" }))
      .toBeInTheDocument()
    expect(dialog).toBeInTheDocument()
    expect(name).toHaveValue("Updated destination")
    expect(target).toHaveValue("not valid")
    expect(document.body.textContent).not.toContain("SECRET_RAW_ERROR")

    vi.mocked(updateTelegramDestination).mockResolvedValueOnce({
      destination: { ...destination, name: "Updated destination" },
      jobId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "Save destination" }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
  })

  it("pairs Codex with explicit read scopes and shows one-time output", async () => {
    vi.mocked(createCodexPairingSession).mockResolvedValue({
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      device_name: "Review laptop",
      scopes: ["settings:read"],
      status: "pending",
      expires_at: "2026-07-24T08:05:00Z",
      pairing_code: "one-time-code",
      local_command: "newscraft pair one-time-code",
      created_at: "2026-07-24T08:00:00Z",
    })
    renderSettings({ section: "codex" })

    fireEvent.click(await screen.findByRole("button", { name: "Pair Codex" }))
    const dialog = screen.getByRole("dialog", { name: "Pair Codex" })
    fireEvent.change(within(dialog).getByLabelText(/Agent or device name/), { target: { value: "Review laptop" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Create pairing code" }))

    await waitFor(() => expect(createCodexPairingSession).toHaveBeenCalledWith(
      "Review laptop",
      expect.arrayContaining(["settings:read", "providers:read"])
    ))
    const output = await screen.findByRole("dialog", { name: "Pair Review laptop" })
    expect(within(output).getByDisplayValue("one-time-code")).toBeInTheDocument()
    expect(within(output).getByText(/Shown once/)).toBeInTheDocument()
  })

  it("keeps raw prompt text directional and activation guarded", async () => {
    vi.mocked(activatePromptVersion).mockResolvedValue({ ...promptVersion, is_active: true })
    renderSettings({ section: "prompts" })

    const purpose = await screen.findByRole("heading", { name: "Telegram Automation Rewrite" })
    const article = purpose.closest("article")
    expect(article).not.toBeNull()
    fireEvent.click(within(article!).getByRole("button", { name: "Manage" }))
    const userTemplate = within(article!).getByLabelText(/^User template/)
    expect(userTemplate).toHaveAttribute("dir", "auto")
    fireEvent.click(within(article!).getByText("Inspect raw template"))
    expect(within(article!).getByText(/Use evidence only/, { selector: "pre" })).toHaveAttribute("dir", "auto")
    expect(within(article!).getByRole("button", { name: "Review activation" })).toBeDisabled()
  })

})

function renderSettings({
  section = "llm-providers",
}: {
  section?: Parameters<typeof ContentSettingsPage>[0]["section"]
} = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <NoticeProvider>
          <ContentSettingsPage section={section} />
        </NoticeProvider>
      </QueryClientProvider>
    ),
  }
}

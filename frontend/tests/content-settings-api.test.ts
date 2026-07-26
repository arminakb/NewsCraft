import {
  createCodexPairingSession,
  createLLMProvider,
  createTelegramDestination,
  getLLMProviders,
  rotateCodexConnection,
} from "@/features/settings/content-settings-api"

describe("content settings API", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("maps generic LLM readiness and serializes write-only provider fields", async () => {
    const request = stubFetch(providerPayload())

    await expect(getLLMProviders()).resolves.toEqual([
      expect.objectContaining({
        name: "Newsroom model",
        base_url: "https://llm.example/v1",
        default_model: "vendor/model",
        generation_ready: true,
        research_ready: false,
        settings: expect.objectContaining({ timeout_seconds: 60, max_input_tokens: 60000 }),
      }),
    ])

    request.mockClear()
    request.mockResolvedValueOnce(new Response(JSON.stringify(providerPayload()[0]), {
      status: 201,
      headers: { "content-type": "application/json" },
    }))
    await createLLMProvider({
      name: "Newsroom model",
      baseUrl: "https://llm.example/v1",
      defaultModel: "vendor/model",
      apiKey: "write-only",
      settings: { timeoutSeconds: 45, maxInputTokens: 50000, maxOutputTokens: 8000 },
    })
    expect(request).toHaveBeenCalledWith(
      "/api/backend/llm-providers",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "Newsroom model",
          protocol: "openai_compatible",
          base_url: "https://llm.example/v1",
          default_model: "vendor/model",
          api_key: "write-only",
          settings: { timeout_seconds: 45, max_input_tokens: 50000, max_output_tokens: 8000 },
          enabled: false,
        }),
      }),
    )
  })

  it("uses normalized Telegram destination contract without auto-publish fields", async () => {
    const request = stubFetch({
      destination: destinationPayload(),
      job: { job_id: "job-1", status: "queued", deduplicated: false },
    })

    await expect(createTelegramDestination({
      name: "Main channel",
      target: "@newscraft",
      botToken: "write-only-token",
      proxyProfileId: "55555555-5555-4555-8555-555555555555",
    })).resolves.toMatchObject({
      destination: {
        canonical_target: "@newscraft",
        connection_route: "Publishing proxy",
        administrator_status: "administrator",
      },
      jobId: "job-1",
    })

    const body = JSON.parse((request.mock.calls[0][1] as RequestInit).body as string)
    expect(body).toEqual({
      name: "Main channel",
      target: "@newscraft",
      bot_token: "write-only-token",
      proxy_profile_id: "55555555-5555-4555-8555-555555555555",
    })
    expect(body).not.toHaveProperty("allow_auto_publish")
  })

  it("creates least-privilege pairing sessions and sends rotation idempotency keys", async () => {
    const request = stubFetch({
      id: "77777777-7777-4777-8777-777777777777",
      device_name: "Review laptop",
      scopes: ["settings:read"],
      status: "pending",
      expires_at: "2026-07-24T08:05:00Z",
      pairing_code: "one-time-code",
      local_command: "pair command",
    })

    await createCodexPairingSession("Review laptop", ["settings:read"])
    expect(request).toHaveBeenLastCalledWith(
      "/api/backend/codex-gateway/pairing-sessions",
      expect.objectContaining({
        body: JSON.stringify({
          device_name: "Review laptop",
          scopes: ["settings:read"],
          confirm_write_scopes: false,
        }),
      }),
    )

    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "idempotency-key") })
    request.mockResolvedValueOnce(new Response(JSON.stringify({
      connection: connectionPayload(),
      credential: "rotated-secret",
    }), { status: 200, headers: { "content-type": "application/json" } }))
    await rotateCodexConnection("77777777-7777-4777-8777-777777777777")
    expect(request).toHaveBeenLastCalledWith(
      "/api/backend/codex-gateway/connections/77777777-7777-4777-8777-777777777777/rotate",
      { method: "POST", headers: { "Idempotency-Key": "idempotency-key" } },
    )
  })
})

function stubFetch(payload: unknown) {
  const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  }))
  vi.stubGlobal("fetch", request)
  return request
}

function providerPayload() {
  return [{
    id: "44444444-4444-4444-8444-444444444444",
    name: "Newsroom model",
    protocol: "openai_compatible",
    base_url: "https://llm.example/v1",
    default_model: "vendor/model",
    enabled: true,
    configured: true,
    settings: {
      timeout_seconds: 60,
      max_input_tokens: 60000,
      max_output_tokens: 12000,
      research_budgets: {},
      pricing: { input_usd_per_million: 0, output_usd_per_million: 0 },
      attribution_headers: { http_referer: null, app_title: "NewsCraft" },
    },
    health_status: "healthy",
    generation_capability: "ready",
    research_capability: "unavailable",
    generation_ready: true,
    research_ready: false,
    failure_code: "research_budget_missing",
    last_checked_at: "2026-07-24T08:00:00Z",
    ownership: "operator_managed",
  }]
}

function destinationPayload() {
  return {
    id: "66666666-6666-4666-8666-666666666666",
    name: "Main channel",
    target_ref: "@newscraft",
    canonical_target: "@newscraft",
    target_type: "username",
    enabled: false,
    health_status: "unchecked",
    configured: true,
    proxy_profile_id: "55555555-5555-4555-8555-555555555555",
    connection_route: "Publishing proxy",
    proxy_health_status: "unchecked",
    telegram_health_status: "unchecked",
    bot_health_status: "unchecked",
    target_health_status: "unchecked",
    administrator_status: "administrator",
    failure_code: null,
    verified_bot_username: null,
    verified_chat_title: null,
    last_checked_at: null,
  }
}

function connectionPayload() {
  return {
    id: "77777777-7777-4777-8777-777777777777",
    device_name: "Review laptop",
    scopes: ["settings:read"],
    status: "gray",
    connection_state: "active",
    failure_code: null,
    expires_at: "2026-08-24T08:00:00Z",
    last_heartbeat_at: null,
    last_rotated_at: "2026-07-24T08:00:00Z",
  }
}

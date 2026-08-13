import { NextRequest } from "next/server"

import { DELETE, GET } from "@/app/api/backend/[...path]/route"

describe("backend proxy route", () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it("forwards backend API requests to the configured internal backend URL", async () => {
    vi.stubEnv("API_INTERNAL_BASE_URL", "http://api:8000")
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([{ id: "source-1" }]), {
        headers: { "content-type": "application/json" },
        status: 200,
      })
    )
    vi.stubGlobal("fetch", fetchSpy)

    const response = await GET(new NextRequest("http://localhost:3000/api/backend/sources?limit=2"), {
      params: Promise.resolve({ path: ["sources"] }),
    })

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://api:8000/sources?limit=2",
      expect.objectContaining({ method: "GET" })
    )
    await expect(response.json()).resolves.toEqual([{ id: "source-1" }])
  })

  it("proxies public Codex reads without requiring cookie or authorization headers", async () => {
    vi.stubEnv("API_INTERNAL_BASE_URL", "http://api:8000")
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { "content-type": "application/json" },
        status: 200,
      })
    )
    vi.stubGlobal("fetch", fetchSpy)

    const response = await GET(
      new NextRequest("http://localhost:3000/api/backend/codex-gateway/connections"),
      { params: Promise.resolve({ path: ["codex-gateway", "connections"] }) },
    )

    expect(response.status).toBe(200)
    const requestHeaders = (fetchSpy.mock.calls[0][1] as RequestInit).headers as Headers
    expect(requestHeaders.has("authorization")).toBe(false)
    expect(requestHeaders.has("cookie")).toBe(false)
  })

  it("forwards profile cookies and bearer credentials without client-controlled principal metadata", async () => {
    vi.stubEnv("API_INTERNAL_BASE_URL", "http://api:8000")
    const fetchSpy = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchSpy)

    await GET(
      new NextRequest("http://localhost:3000/api/backend/codex-gateway/capabilities", {
        headers: {
          Authorization: "Bearer gateway-credential",
          Cookie: "newscraft_profile_session=opaque",
          "X-NewsCraft-Principal-Type": "human_admin",
          "X-NewsCraft-Scopes": "settings:write",
        },
      }),
      { params: Promise.resolve({ path: ["codex-gateway", "capabilities"] }) },
    )

    const requestHeaders = (fetchSpy.mock.calls[0][1] as RequestInit).headers as Headers
    expect(requestHeaders.get("authorization")).toBe("Bearer gateway-credential")
    expect(requestHeaders.get("cookie")).toBe("newscraft_profile_session=opaque")
    expect(requestHeaders.has("x-newscraft-principal-type")).toBe(false)
    expect(requestHeaders.has("x-newscraft-scopes")).toBe(false)
  })

  it("forwards same-origin provider deletion without an Operator Secret or session", async () => {
    vi.stubEnv("API_INTERNAL_BASE_URL", "http://api:8000")
    const fetchSpy = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchSpy)

    const response = await DELETE(
      new NextRequest(
        "http://localhost:3000/api/backend/llm-providers/44444444-4444-4444-8444-444444444444",
        {
          method: "DELETE",
          headers: {
            Origin: "http://localhost:3000",
          },
        },
      ),
      { params: Promise.resolve({ path: ["llm-providers", "44444444-4444-4444-8444-444444444444"] }) },
    )

    expect(response.status).toBe(204)
    const requestHeaders = (fetchSpy.mock.calls[0][1] as RequestInit).headers as Headers
    expect(requestHeaders.has("cookie")).toBe(false)
    expect(requestHeaders.get("origin")).toBe("http://localhost:3000")
    expect(requestHeaders.has("authorization")).toBe(false)
  })

  it("returns a structured 503 when the backend cannot be reached", async () => {
    vi.stubEnv("API_INTERNAL_BASE_URL", "http://api:8000")
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")))

    const response = await GET(new NextRequest("http://localhost:3000/api/backend/automations?limit=50"), {
      params: Promise.resolve({ path: ["automations"] }),
    })

    expect(response.status).toBe(503)
    await expect(response.json()).resolves.toEqual({
      detail: {
        code: "backend_unavailable",
        message: "NewsCraft API is unavailable. Start the backend service and retry.",
      },
    })
  })
})

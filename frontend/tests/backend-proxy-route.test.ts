import { createServer, type IncomingHttpHeaders, type Server } from "node:http"
import { AddressInfo } from "node:net"

import { NextRequest } from "next/server"

import { DELETE, GET, POST } from "@/app/api/backend/[...path]/route"

describe("backend proxy route", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
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

  it("ignores the browser-facing NEXT_PUBLIC_API_BASE_URL when resolving its upstream", async () => {
    vi.stubEnv("API_INTERNAL_BASE_URL", undefined)
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://attacker.example:9000")
    const fetchSpy = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchSpy)

    await GET(new NextRequest("http://localhost:3000/api/backend/sources"), {
      params: Promise.resolve({ path: ["sources"] }),
    })

    expect(fetchSpy).toHaveBeenCalledWith("http://localhost:8000/sources", expect.anything())
  })

  it("returns a structured 503 when the backend cannot be reached", async () => {
    vi.stubEnv("API_INTERNAL_BASE_URL", "http://api:8000")
    const connectionRefused = new TypeError("fetch failed")
    connectionRefused.cause = Object.assign(new Error("connect ECONNREFUSED"), { code: "ECONNREFUSED" })
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(connectionRefused))

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

  it("reports proxy defects as 502 instead of masking them as an unavailable backend", async () => {
    vi.stubEnv("API_INTERNAL_BASE_URL", "http://api:8000")
    const invalidHeader = new TypeError("fetch failed")
    invalidHeader.cause = new TypeError("invalid transfer-encoding header")
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(invalidHeader))

    const response = await GET(new NextRequest("http://localhost:3000/api/backend/automations"), {
      params: Promise.resolve({ path: ["automations"] }),
    })

    expect(response.status).toBe(502)
    await expect(response.json()).resolves.toEqual({
      detail: {
        code: "proxy_error",
        message: "The NewsCraft proxy could not complete this request (TypeError).",
      },
    })
    expect(console.error).toHaveBeenCalled()
  })
})

describe("backend proxy route header forwarding against a real backend", () => {
  let server: Server
  let baseUrl = ""
  let received: { method: string; url: string; headers: IncomingHttpHeaders; body: string }[] = []

  beforeAll(async () => {
    server = createServer((request, response) => {
      const chunks: Buffer[] = []
      request.on("data", (chunk: Buffer) => chunks.push(chunk))
      request.on("end", () => {
        received.push({
          method: request.method ?? "",
          url: request.url ?? "",
          headers: request.headers,
          body: Buffer.concat(chunks).toString("utf8"),
        })
        response.writeHead(200, { "content-type": "application/json" })
        response.end(JSON.stringify({ ok: true }))
      })
    })
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve))
    baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
  })

  afterAll(async () => {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()))
    })
  })

  beforeEach(() => {
    received = []
    vi.spyOn(console, "error").mockImplementation(() => {})
    vi.stubEnv("API_INTERNAL_BASE_URL", baseUrl)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it("drops inbound hop-by-hop and stale framing headers so a buffered body still reaches the backend", async () => {
    const request = new NextRequest("http://localhost:3000/api/backend/articles", {
      method: "POST",
      body: '{"a":1}',
      headers: {
        "content-type": "application/json",
        "content-length": "999",
        "transfer-encoding": "chunked",
        connection: "keep-alive",
        "keep-alive": "timeout=5",
        te: "trailers",
        trailer: "expires",
        upgrade: "websocket",
        "proxy-authorization": "Basic secret",
        "x-forwarded-for": "203.0.113.9",
      },
    })

    const response = await POST(request, { params: Promise.resolve({ path: ["articles"] }) })

    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toEqual({ ok: true })
    expect(received).toHaveLength(1)
    expect(received[0].body).toBe('{"a":1}')
    expect(received[0].headers["content-length"]).toBe("7")
    expect(received[0].headers["transfer-encoding"]).toBeUndefined()
    expect(received[0].headers["keep-alive"]).toBeUndefined()
    expect(received[0].headers.te).toBeUndefined()
    expect(received[0].headers.trailer).toBeUndefined()
    expect(received[0].headers.upgrade).toBeUndefined()
    expect(received[0].headers["proxy-authorization"]).toBeUndefined()
    expect(received[0].headers["content-type"]).toBe("application/json")
    expect(received[0].headers["x-forwarded-for"]).toBe("203.0.113.9")
  })

  it("keeps the truthful request content-encoding because the body is forwarded verbatim", async () => {
    const request = new NextRequest("http://localhost:3000/api/backend/articles", {
      method: "POST",
      body: "payload",
      headers: {
        "content-type": "application/json",
        "content-encoding": "gzip",
      },
    })

    const response = await POST(request, { params: Promise.resolve({ path: ["articles"] }) })

    expect(response.status).toBe(200)
    expect(received[0].headers["content-encoding"]).toBe("gzip")
    expect(received[0].body).toBe("payload")
  })
})

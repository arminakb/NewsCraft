import { NextRequest } from "next/server"

import { GET } from "@/app/api/backend/[...path]/route"

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
})

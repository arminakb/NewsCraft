import {
  getAutomationControl,
  updateAutomationControl,
} from "@/features/control/api"
import { queryKeys } from "@/lib/query-keys"

describe("automation control API", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("maps every automation control field", async () => {
    const fetchSpy = stubFetch({
      global_pause: true,
      dry_run: false,
      pause_reason: "Editorial review",
      paused_at: "2026-07-12T08:00:00Z",
      updated_at: "2026-07-12T08:00:01Z",
    })

    await expect(getAutomationControl()).resolves.toEqual({
      globalPause: true,
      dryRun: false,
      pauseReason: "Editorial review",
      pausedAt: "2026-07-12T08:00:00Z",
      updatedAt: "2026-07-12T08:00:01Z",
    })
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/automation-control", undefined)
  })

  it("patches camel-case control input as snake case", async () => {
    const fetchSpy = stubFetch({
      global_pause: true,
      dry_run: true,
      pause_reason: "Paused from Newsroom",
      paused_at: "2026-07-12T08:00:00Z",
      updated_at: "2026-07-12T08:00:01Z",
    })

    await updateAutomationControl({
      globalPause: true,
      dryRun: true,
      pauseReason: "Paused from Newsroom",
    })

    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/automation-control", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        global_pause: true,
        dry_run: true,
        pause_reason: "Paused from Newsroom",
      }),
    })
  })

  it("preserves explicit null while omitting unset patch fields", async () => {
    const fetchSpy = stubFetch({
      global_pause: true,
      dry_run: false,
      pause_reason: null,
      paused_at: "2026-07-12T08:00:00Z",
      updated_at: "2026-07-12T08:00:01Z",
    })

    await updateAutomationControl({ pauseReason: null })

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/automation-control",
      expect.objectContaining({ body: JSON.stringify({ pause_reason: null }) })
    )
    expect(queryKeys.automationControl).toEqual(["automation-control"])
  })
})

function stubFetch(payload: unknown) {
  const fetchSpy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  })
  vi.stubGlobal("fetch", fetchSpy)
  return fetchSpy
}

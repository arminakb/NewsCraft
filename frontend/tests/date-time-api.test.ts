import {
  getDateTimeSettings,
  updateDateTimeSettings,
} from "@/features/settings/date-time-api"

describe("Date & Time API", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("persists timezone and reads the saved value after reload", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(response({
        timezone: "Asia/Tehran",
        updated_at: "2026-07-28T11:00:00Z",
      }))
      .mockResolvedValueOnce(response({
        timezone: "Europe/London",
        updated_at: "2026-07-28T11:05:00Z",
      }))
      .mockResolvedValueOnce(response({
        timezone: "Europe/London",
        updated_at: "2026-07-28T11:05:00Z",
      }))
    vi.stubGlobal("fetch", request)

    await expect(getDateTimeSettings()).resolves.toMatchObject({ timezone: "Asia/Tehran" })
    await expect(updateDateTimeSettings("Europe/London")).resolves.toMatchObject({
      timezone: "Europe/London",
    })
    await expect(getDateTimeSettings()).resolves.toMatchObject({ timezone: "Europe/London" })

    expect(request).toHaveBeenNthCalledWith(
      2,
      "/api/backend/operator-settings/date-time",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ timezone: "Europe/London" }),
      }),
    )
  })

  it("rejects invalid selections before transport and invalid server values after transport", async () => {
    const request = vi.fn().mockResolvedValue(response({ timezone: "Mars/Olympus" }))
    vi.stubGlobal("fetch", request)

    await expect(updateDateTimeSettings("Mars/Olympus")).rejects.toThrow("valid IANA")
    expect(request).not.toHaveBeenCalled()
    await expect(getDateTimeSettings()).rejects.toThrow("invalid timezone")
  })
})

function response(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  })
}

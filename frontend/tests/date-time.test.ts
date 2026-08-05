import {
  formatInTimeZone,
  getSupportedTimeZones,
  isValidTimeZone,
  timeZoneCity,
  timeZoneLabel,
  zonedLocalDateTimeToUtc,
} from "@/lib/date-time"

describe("date and time utilities", () => {
  it("validates IANA identifiers and exposes searchable labels", () => {
    expect(isValidTimeZone("Asia/Tehran")).toBe(true)
    expect(isValidTimeZone("UTC")).toBe(true)
    expect(isValidTimeZone("Mars/Olympus")).toBe(false)
    expect(isValidTimeZone(" Asia/Tehran")).toBe(false)
    expect(timeZoneLabel("America/New_York")).toBe("America/New_York — New York")
    expect(timeZoneCity("Asia/Tehran")).toBe("Tehran")
    expect(timeZoneCity("America/Argentina/Buenos_Aires")).toBe("Buenos Aires")
    expect(timeZoneCity("UTC")).toBe("UTC")
    expect(getSupportedTimeZones()).toEqual(expect.arrayContaining([
      "Asia/Tehran",
      "Europe/London",
      "America/New_York",
      "Asia/Tokyo",
      "UTC",
    ]))
  })

  it("formats one UTC instant in the selected timezone", () => {
    const instant = "2026-07-28T11:05:42.000Z"
    const options: Intl.DateTimeFormatOptions = {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }

    expect(formatInTimeZone(instant, "Asia/Tehran", options, "en-CA")).toContain("14:35:42")
    expect(formatInTimeZone(instant, "Europe/London", options, "en-CA")).toContain("12:05:42")
  })

  it("converts local schedules to UTC with seasonal IANA rules", () => {
    expect(zonedLocalDateTimeToUtc("2026-07-28T14:35", "Asia/Tehran"))
      .toBe("2026-07-28T11:05:00.000Z")
    expect(zonedLocalDateTimeToUtc("2026-07-28T08:00", "America/New_York"))
      .toBe("2026-07-28T12:00:00.000Z")
    expect(zonedLocalDateTimeToUtc("2026-01-28T08:00", "America/New_York"))
      .toBe("2026-01-28T13:00:00.000Z")
  })

  it("rejects malformed and nonexistent local times", () => {
    expect(zonedLocalDateTimeToUtc("not-a-date", "Asia/Tehran")).toBeNull()
    expect(zonedLocalDateTimeToUtc("2026-03-08T02:30", "America/New_York")).toBeNull()
    expect(zonedLocalDateTimeToUtc("2026-07-28T14:35", "Mars/Olympus")).toBeNull()
  })
})

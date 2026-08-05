import { apiRequest } from "@/lib/http"
import { isValidTimeZone } from "@/lib/date-time"

export type DateTimeSettings = {
  timezone: string
  updatedAt: string | null
}

type DateTimeSettingsWire = {
  timezone?: unknown
  updated_at?: unknown
}

export async function getDateTimeSettings(): Promise<DateTimeSettings> {
  return decodeDateTimeSettings(
    await apiRequest<DateTimeSettingsWire>("/operator-settings/date-time"),
  )
}

export async function updateDateTimeSettings(timezone: string): Promise<DateTimeSettings> {
  if (!isValidTimeZone(timezone)) throw new Error("Select a valid IANA timezone.")
  return decodeDateTimeSettings(
    await apiRequest<DateTimeSettingsWire>("/operator-settings/date-time", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ timezone }),
    }),
  )
}

function decodeDateTimeSettings(value: DateTimeSettingsWire): DateTimeSettings {
  if (typeof value.timezone !== "string" || !isValidTimeZone(value.timezone)) {
    throw new Error("Date & Time settings returned an invalid timezone.")
  }
  if (value.updated_at !== undefined && value.updated_at !== null && typeof value.updated_at !== "string") {
    throw new Error("Date & Time settings returned an invalid update time.")
  }
  return {
    timezone: value.timezone,
    updatedAt: value.updated_at ?? null,
  }
}

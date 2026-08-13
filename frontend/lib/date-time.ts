export const DEFAULT_TIME_ZONE = "Asia/Tehran"

const REQUIRED_TIME_ZONES = [
  "Asia/Tehran",
  "Europe/London",
  "America/New_York",
  "Asia/Tokyo",
  "UTC",
] as const

const PARTS_LOCALE = "en-CA-u-ca-gregory-nu-latn"

type DateTimeInput = Date | number | string
type ZonedParts = {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
}

export function isValidTimeZone(value: string): boolean {
  if (!value || value !== value.trim()) return false
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: value }).format()
    return true
  } catch {
    return false
  }
}

export function getSupportedTimeZones(): string[] {
  const supportedValuesOf = (
    Intl as typeof Intl & {
      supportedValuesOf?: (key: "timeZone") => string[]
    }
  ).supportedValuesOf
  const supported = supportedValuesOf?.("timeZone") ?? []
  return [...new Set([...REQUIRED_TIME_ZONES, ...supported])].sort((left, right) =>
    left.localeCompare(right),
  )
}

export function timeZoneLabel(timeZone: string): string {
  if (timeZone === "UTC") return "UTC — Coordinated Universal Time"
  return `${timeZone} — ${timeZoneCity(timeZone)}`
}

export function timeZoneCity(timeZone: string): string {
  return timeZone.split("/").at(-1)?.replaceAll("_", " ") || timeZone
}

export function formatInTimeZone(
  value: DateTimeInput,
  timeZone: string,
  options: Intl.DateTimeFormatOptions = {
    dateStyle: "medium",
    timeStyle: "short",
  },
  locale = "en-US",
): string {
  const parsed = toDate(value)
  if (!parsed || !isValidTimeZone(timeZone)) return typeof value === "string" ? value : "Time unavailable"
  return new Intl.DateTimeFormat(locale, { ...options, timeZone }).format(parsed)
}

export function zonedLocalDateTimeToUtc(value: string, timeZone: string): string | null {
  const local = parseLocalDateTime(value)
  if (!local || !isValidTimeZone(timeZone)) return null

  const expectedAsUtc = partsAsUtc(local)
  let candidate = expectedAsUtc
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const observed = zonedParts(candidate, timeZone)
    if (!observed) return null
    const correction = expectedAsUtc - partsAsUtc(observed)
    candidate += correction
    if (correction === 0) break
  }

  const resolved = zonedParts(candidate, timeZone)
  if (!resolved || !sameParts(resolved, local)) return null
  return new Date(candidate).toISOString()
}

export function formatDateTimeLocalValue(value: DateTimeInput, timeZone: string): string | null {
  const parsed = toDate(value)
  if (!parsed || !isValidTimeZone(timeZone)) return null
  const parts = zonedParts(parsed.getTime(), timeZone)
  if (!parts) return null
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`
}

function toDate(value: DateTimeInput): Date | null {
  const parsed = value instanceof Date ? value : new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function parseLocalDateTime(value: string): ZonedParts | null {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/)
  if (!match) return null
  const parts = {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
    second: Number(match[6] ?? "0"),
  }
  const roundTrip = new Date(partsAsUtc(parts))
  if (
    roundTrip.getUTCFullYear() !== parts.year
    || roundTrip.getUTCMonth() + 1 !== parts.month
    || roundTrip.getUTCDate() !== parts.day
    || roundTrip.getUTCHours() !== parts.hour
    || roundTrip.getUTCMinutes() !== parts.minute
    || roundTrip.getUTCSeconds() !== parts.second
  ) return null
  return parts
}

function zonedParts(value: number, timeZone: string): ZonedParts | null {
  const entries = new Intl.DateTimeFormat(PARTS_LOCALE, {
    timeZone,
    calendar: "gregory",
    numberingSystem: "latn",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value))
  const values = Object.fromEntries(
    entries
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  )
  if (
    !Number.isInteger(values.year)
    || !Number.isInteger(values.month)
    || !Number.isInteger(values.day)
    || !Number.isInteger(values.hour)
    || !Number.isInteger(values.minute)
    || !Number.isInteger(values.second)
  ) return null
  return values as ZonedParts
}

function partsAsUtc(parts: ZonedParts): number {
  return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second)
}

function sameParts(left: ZonedParts, right: ZonedParts): boolean {
  return left.year === right.year
    && left.month === right.month
    && left.day === right.day
    && left.hour === right.hour
    && left.minute === right.minute
    && left.second === right.second
}

function pad(value: number): string {
  return String(value).padStart(2, "0")
}

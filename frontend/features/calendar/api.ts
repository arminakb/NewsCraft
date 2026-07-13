import { apiRequest } from "@/lib/http"

import type {
  CalendarEvent,
  CalendarEventKind,
  CalendarPlatform,
  PublicationCalendarRequest,
  PublicationCalendarResult,
} from "./types"

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const AWARE_INSTANT_PATTERN = /(?:Z|[+-]\d{2}:\d{2})$/
const EVENT_KEYS = ["id", "kind", "platform", "revision_id", "title", "starts_at", "status", "action_url"] as const
const RESPONSE_KEYS = ["items", "timezone"] as const

export async function getPublicationCalendar(
  request: PublicationCalendarRequest,
): Promise<PublicationCalendarResult> {
  requireUtcInstant(request.start, "Calendar start")
  requireUtcInstant(request.end, "Calendar end")
  if (Date.parse(request.end) <= Date.parse(request.start)) throw new Error("Calendar end must follow start")
  if (!request.timezone.trim()) throw new Error("Calendar timezone is required")

  const search = new URLSearchParams({
    start: request.start,
    end: request.end,
    timezone: request.timezone,
  })
  const value = await apiRequest<unknown>(`/calendar?${search.toString()}`)
  const row = exactObject(value, RESPONSE_KEYS, "Invalid calendar response")
  const timezone = nonEmptyString(row.timezone, "Invalid calendar response timezone")
  if (timezone !== request.timezone) throw new Error("Calendar response timezone mismatch")
  if (!Array.isArray(row.items)) throw new Error("Invalid calendar event list")

  return { events: row.items.map(decodeCalendarEvent), timezone }
}

export function decodeCalendarEvent(value: unknown): CalendarEvent {
  const row = exactObject(value, EVENT_KEYS, "Invalid calendar event")
  const id = nonEmptyString(row.id, "Invalid calendar event id")
  const kind = oneOf(row.kind, ["telegram_publish", "manual_publication"] as const, "Invalid calendar event kind")
  const platform = oneOf(row.platform, ["telegram", "instagram", "x", "blog"] as const, "Invalid calendar event platform")
  const revisionId = nonEmptyString(row.revision_id, "Invalid calendar event revision")
  if (!UUID_PATTERN.test(revisionId)) throw new Error("Invalid calendar event revision")
  const startsAt = nonEmptyString(row.starts_at, "Invalid calendar event start")
  if (!AWARE_INSTANT_PATTERN.test(startsAt) || Number.isNaN(Date.parse(startsAt))) {
    throw new Error("Invalid calendar event start")
  }
  if ((kind === "telegram_publish") !== (platform === "telegram")) {
    throw new Error("Invalid calendar event kind and platform")
  }

  return {
    id,
    kind: kind as CalendarEventKind,
    platform: platform as CalendarPlatform,
    revisionId,
    title: nonEmptyString(row.title, "Invalid calendar event title"),
    startsAt,
    status: nonEmptyString(row.status, "Invalid calendar event status"),
    actionUrl: safeApplicationPath(row.action_url),
  }
}

function requireUtcInstant(value: string, field: string) {
  if (!value.endsWith("Z") || Number.isNaN(Date.parse(value))) throw new Error(`${field} must be a UTC instant`)
}

function safeApplicationPath(value: unknown): string {
  const path = nonEmptyString(value, "Invalid calendar event action URL")
  const segments = path.split("/")
  if (
    !path.startsWith("/")
    || path.startsWith("//")
    || path.includes("\\")
    || path.includes("?")
    || path.includes("#")
    || segments.some((segment) => segment === "." || segment === "..")
  ) {
    throw new Error("Invalid calendar event action URL")
  }
  return path
}

function exactObject<const K extends readonly string[]>(
  value: unknown,
  keys: K,
  message: string,
): Record<K[number], unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(message)
  const row = value as Record<string, unknown>
  const actual = Object.keys(row).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new Error(message)
  return row as Record<K[number], unknown>
}

function nonEmptyString(value: unknown, message: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(message)
  return value
}

function oneOf<const T extends readonly string[]>(value: unknown, values: T, message: string): T[number] {
  if (typeof value !== "string" || !values.includes(value)) throw new Error(message)
  return value as T[number]
}

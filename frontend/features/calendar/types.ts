export type CalendarPlatform = "telegram" | "instagram" | "x" | "blog"
export type CalendarEventKind = "telegram_publish" | "manual_publication"

export type CalendarEvent = {
  id: string
  kind: CalendarEventKind
  platform: CalendarPlatform
  revisionId: string
  title: string
  startsAt: string
  status: string
  /** Server-projected application path for the exact persisted record. */
  actionUrl: string
}

export type PublicationCalendarResult = {
  events: CalendarEvent[]
  timezone: string
}

export type PublicationCalendarRequest = {
  /** Inclusive UTC instant. */
  start: string
  /** Exclusive UTC instant. */
  end: string
  timezone: string
}

"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { getApiErrorMessage } from "@/lib/http"
import { packageQueryKeys } from "@/lib/query-keys"

import { getPublicationCalendar } from "./api"
import type { CalendarEvent, CalendarPlatform } from "./types"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

type CalendarView = "month" | "list"
type CalendarMonth = { year: number; month: number }

const PLATFORM_OPTIONS: Array<{ value: CalendarPlatform; label: string }> = [
  { value: "telegram", label: "Telegram" },
  { value: "instagram", label: "Instagram" },
  { value: "x", label: "X" },
  { value: "blog", label: "Blog" },
]

const DEFAULT_TIMEZONES = ["Asia/Tehran", "UTC", "Europe/London", "America/New_York"]
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

export function PublicationCalendar({
  events,
  timezone: initialTimezone = "Asia/Tehran",
  initialDate = new Date(),
}: {
  /** A server-projected event set can be supplied for a pure embedded view. */
  events?: CalendarEvent[]
  timezone?: string
  initialDate?: Date
}) {
  const [timezone, setTimezone] = useState(initialTimezone)
  const [month, setMonth] = useState<CalendarMonth>(() => monthAt(initialDate, initialTimezone))
  const [view, setView] = useState<CalendarView>("month")
  const [platform, setPlatform] = useState<CalendarPlatform | "all">("all")
  const [status, setStatus] = useState("all")
  const window = useMemo(() => calendarWindow(month, timezone), [month, timezone])
  const hasProvidedEvents = events !== undefined
  const calendarQuery = useQuery({
    queryKey: packageQueryKeys.calendar(window.start, window.end, timezone),
    queryFn: () => getPublicationCalendar({ start: window.start, end: window.end, timezone }),
    enabled: !hasProvidedEvents,
  })

  const sourceEvents = events ?? calendarQuery.data?.events ?? []
  const eventsInWindow = useMemo(
    () => sourceEvents.filter((event) => isWithinWindow(event, window)),
    [sourceEvents, window],
  )
  const statuses = useMemo(
    () => [...new Set(eventsInWindow.map((event) => event.status))].sort((left, right) => left.localeCompare(right)),
    [eventsInWindow],
  )
  const visibleEvents = useMemo(
    () => [...eventsInWindow]
      .filter((event) => platform === "all" || event.platform === platform)
      .filter((event) => status === "all" || event.status === status)
      .sort(compareEvents),
    [eventsInWindow, platform, status],
  )
  const timezoneOptions = DEFAULT_TIMEZONES.includes(initialTimezone)
    ? DEFAULT_TIMEZONES
    : [initialTimezone, ...DEFAULT_TIMEZONES]

  const moveMonth = (offset: number) => setMonth((current) => normalizeMonth(current.year, current.month + offset))
  const moveToToday = () => setMonth(monthAt(new Date(), timezone))

  return (
    <section className="min-w-0 space-y-6 p-4 md:p-6" aria-labelledby="publication-calendar-heading">
      <header>
        <h1 id="publication-calendar-heading" className="text-2xl font-semibold">Publication calendar</h1>
        <p className="text-muted-foreground">Server-recorded Telegram and manual publication events in the operator timezone.</p>
      </header>

      <section aria-label="Calendar controls" className="space-y-4 rounded-lg border p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="grid gap-1 text-sm">
            <span>Platform</span>
            <select
              aria-label="Platform"
              value={platform}
              onChange={(event) => setPlatform(event.target.value as CalendarPlatform | "all")}
              className="h-9 rounded-md border bg-background px-3"
            >
              <option value="all">All platforms</option>
              {PLATFORM_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            <span>Status</span>
            <select
              aria-label="Status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="h-9 rounded-md border bg-background px-3"
            >
              <option value="all">All statuses</option>
              {statuses.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            <span>Timezone</span>
            <select
              aria-label="Timezone"
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
              className="h-9 rounded-md border bg-background px-3"
            >
              {timezoneOptions.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Calendar navigation">
            <Button type="button" variant="outline" onClick={() => moveMonth(-1)} aria-label="Previous month">Previous</Button>
            <Button type="button" variant="outline" onClick={moveToToday}>Today</Button>
            <Button type="button" variant="outline" onClick={() => moveMonth(1)} aria-label="Next month">Next</Button>
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Calendar view">
            <Button type="button" variant={view === "month" ? "default" : "outline"} aria-pressed={view === "month"} onClick={() => setView("month")} aria-label="Month view">Month</Button>
            <Button type="button" variant={view === "list" ? "default" : "outline"} aria-pressed={view === "list"} onClick={() => setView("list")} aria-label="Chronological list view">List</Button>
          </div>
        </div>
      </section>

      <section className="space-y-4" aria-live="polite" aria-busy={!hasProvidedEvents && calendarQuery.isPending}>
        <h2 className="text-xl font-semibold">{monthLabel(month)}</h2>
        {!hasProvidedEvents && calendarQuery.isPending ? (
          <div role="status" aria-label="Loading publication calendar" className="rounded-lg border p-6 text-muted-foreground">Loading publication calendar…</div>
        ) : null}
        {!hasProvidedEvents && calendarQuery.isError ? (
          <div className="space-y-3 rounded-lg border p-6">
            <div role="alert" className="text-red-700" dir="auto">{getApiErrorMessage(calendarQuery.error, "Publication calendar could not be loaded")}</div>
            <Button type="button" variant="outline" onClick={() => void calendarQuery.refetch()}>Retry calendar</Button>
          </div>
        ) : null}
        {(hasProvidedEvents || calendarQuery.isSuccess) && eventsInWindow.length === 0 ? (
          <p className="rounded-lg border p-6 text-muted-foreground">No publication events in this calendar window.</p>
        ) : null}
        {(hasProvidedEvents || calendarQuery.isSuccess) && eventsInWindow.length > 0 && visibleEvents.length === 0 ? (
          <p className="rounded-lg border p-6 text-muted-foreground">No publication events match these filters.</p>
        ) : null}
        {(hasProvidedEvents || calendarQuery.isSuccess) && visibleEvents.length > 0 && view === "month" ? (
          <MonthGrid events={visibleEvents} month={month} timezone={timezone} />
        ) : null}
        {(hasProvidedEvents || calendarQuery.isSuccess) && visibleEvents.length > 0 && view === "list" ? (
          <ChronologicalList events={visibleEvents} timezone={timezone} />
        ) : null}
      </section>
    </section>
  )
}

function MonthGrid({ events, month, timezone }: { events: CalendarEvent[]; month: CalendarMonth; timezone: string }) {
  const firstWeekday = new Date(Date.UTC(month.year, month.month - 1, 1)).getUTCDay()
  const dayCount = new Date(Date.UTC(month.year, month.month, 0)).getUTCDate()
  const eventsByDay = new Map<string, CalendarEvent[]>()
  for (const event of events) {
    const key = dateKey(new Date(event.startsAt), timezone)
    eventsByDay.set(key, [...(eventsByDay.get(key) ?? []), event])
  }

  return (
    <div className="overflow-x-auto rounded-lg border" role="grid" aria-label={`${monthLabel(month)} calendar grid`}>
      <div className="grid min-w-[840px] grid-cols-7 bg-muted/50" role="row">
        {WEEKDAYS.map((weekday) => <div key={weekday} role="columnheader" className="border-b p-2 text-sm font-medium">{weekday}</div>)}
      </div>
      <div className="grid min-w-[840px] grid-cols-7">
        {Array.from({ length: firstWeekday }, (_, index) => <div key={`before-${index}`} role="gridcell" aria-hidden="true" className="min-h-28 border-b border-e bg-muted/20" />)}
        {Array.from({ length: dayCount }, (_, index) => {
          const day = index + 1
          const key = localDateKey(month.year, month.month, day)
          const dayEvents = eventsByDay.get(key) ?? []
          return (
            <div key={key} role="gridcell" aria-label={key} className="min-h-28 space-y-2 border-b border-e p-2">
              <div className="text-sm font-medium">{day}</div>
              {dayEvents.length ? <ul className="space-y-2">{dayEvents.map((event) => <li key={event.id}><CalendarEventSummary event={event} timezone={timezone} compact /></li>)}</ul> : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ChronologicalList({ events, timezone }: { events: CalendarEvent[]; timezone: string }) {
  return (
    <ul aria-label="Chronological publication events" className="space-y-3">
      {events.map((event) => <li key={event.id}><CalendarEventSummary event={event} timezone={timezone} /></li>)}
    </ul>
  )
}

function CalendarEventSummary({ event, timezone, compact = false }: { event: CalendarEvent; timezone: string; compact?: boolean }) {
  return (
    <article className={compact ? "space-y-1 rounded-md border bg-background p-2 text-xs" : "space-y-2 rounded-lg border p-4"}>
      <div className="font-medium"><span>{platformLabel(event.platform)}: </span><DirectionBoundary as="span" language={null}>{event.title}</DirectionBoundary></div>
      <div className="flex flex-wrap gap-x-2 text-muted-foreground">
        <time dateTime={event.startsAt}>{formatEventTime(event.startsAt, timezone, compact)}</time>
        <span>{humanize(event.status)}</span>
      </div>
      <Link className="inline-flex text-primary underline" href={event.actionUrl} aria-label={`Open ${platformLabel(event.platform)} event: ${event.title} (${event.id})`}>
        Open exact record
      </Link>
    </article>
  )
}

function compareEvents(left: CalendarEvent, right: CalendarEvent) {
  return Date.parse(left.startsAt) - Date.parse(right.startsAt) || left.id.localeCompare(right.id)
}

function isWithinWindow(event: CalendarEvent, window: { start: string; end: string }) {
  const instant = Date.parse(event.startsAt)
  return instant >= Date.parse(window.start) && instant < Date.parse(window.end)
}

function monthAt(instant: Date, timezone: string): CalendarMonth {
  const parts = zonedParts(instant, timezone)
  return { year: parts.year, month: parts.month }
}

function normalizeMonth(year: number, month: number): CalendarMonth {
  const normalized = new Date(Date.UTC(year, month - 1, 1))
  return { year: normalized.getUTCFullYear(), month: normalized.getUTCMonth() + 1 }
}

function calendarWindow(month: CalendarMonth, timezone: string) {
  const next = normalizeMonth(month.year, month.month + 1)
  return {
    start: zonedMidnightUtc(month.year, month.month, 1, timezone).toISOString(),
    end: zonedMidnightUtc(next.year, next.month, 1, timezone).toISOString(),
  }
}

function zonedMidnightUtc(year: number, month: number, day: number, timezone: string) {
  const desiredWallClock = Date.UTC(year, month - 1, day)
  let candidate = desiredWallClock
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const parts = zonedParts(new Date(candidate), timezone, true)
    const observedWallClock = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second)
    const correction = desiredWallClock - observedWallClock
    candidate += correction
    if (correction === 0) break
  }
  return new Date(candidate)
}

function zonedParts(instant: Date, timezone: string, includeTime = false) {
  const formatter = new Intl.DateTimeFormat("en-CA-u-ca-gregory-nu-latn", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" as const } : {}),
  })
  const values = Object.fromEntries(
    formatter.formatToParts(instant)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  )
  return {
    year: values.year,
    month: values.month,
    day: values.day,
    hour: values.hour ?? 0,
    minute: values.minute ?? 0,
    second: values.second ?? 0,
  }
}

function dateKey(instant: Date, timezone: string) {
  const parts = zonedParts(instant, timezone)
  return localDateKey(parts.year, parts.month, parts.day)
}

function localDateKey(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`
}

function monthLabel(month: CalendarMonth) {
  return new Intl.DateTimeFormat("en", { month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(month.year, month.month - 1, 1)))
}

function formatEventTime(value: string, timezone: string, compact: boolean) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    ...(compact ? {} : { month: "short", day: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value))
}

function platformLabel(platform: CalendarPlatform) {
  return PLATFORM_OPTIONS.find((option) => option.value === platform)?.label ?? platform
}

function humanize(value: string) {
  return value.replaceAll("_", " ")
}

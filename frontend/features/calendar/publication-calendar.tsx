"use client"

import { useQuery } from "@tanstack/react-query"
import { CalendarDays, ChevronLeft, ChevronRight, List } from "lucide-react"
import Link from "next/link"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { PageHeader } from "@/components/ui/page-header"
import { Select } from "@/components/ui/select"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"
import { cn } from "@/lib/utils"
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
    <section className="nc-page" aria-labelledby="publication-calendar-heading">
      <PageHeader
        title="Publication calendar"
        titleId="publication-calendar-heading"
        description="Server-recorded Telegram and manual publication events in the operator timezone."
      />

      <Card aria-label="Calendar controls" size="sm">
        <CardContent className="space-y-3 p-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="grid gap-1 text-sm">
            <span className="text-xs font-medium text-muted-foreground">Platform</span>
            <Select
              aria-label="Platform"
              value={platform}
              onChange={(event) => setPlatform(event.target.value as CalendarPlatform | "all")}
            >
              <option value="all">All platforms</option>
              {PLATFORM_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </Select>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-xs font-medium text-muted-foreground">Status</span>
            <Select
              aria-label="Status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="all">All statuses</option>
              {statuses.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
            </Select>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-xs font-medium text-muted-foreground">Timezone</span>
            <Select
              aria-label="Timezone"
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
            >
              {timezoneOptions.map((value) => <option key={value} value={value}>{value}</option>)}
            </Select>
          </label>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-3">
          <div className="flex gap-1.5" role="group" aria-label="Calendar navigation">
            <Button type="button" variant="outline" onClick={() => moveMonth(-1)} aria-label="Previous month">
              <ChevronLeft aria-hidden="true" />
              <span className="hidden sm:inline">Previous</span>
            </Button>
            <Button type="button" variant="outline" onClick={moveToToday}>Today</Button>
            <Button type="button" variant="outline" onClick={() => moveMonth(1)} aria-label="Next month">
              <span className="hidden sm:inline">Next</span>
              <ChevronRight aria-hidden="true" />
            </Button>
          </div>
          <div className="flex gap-1.5" role="group" aria-label="Calendar view">
            <Button type="button" variant={view === "month" ? "secondary" : "ghost"} aria-pressed={view === "month"} onClick={() => setView("month")} aria-label="Month view">
              <CalendarDays aria-hidden="true" />
              Month
            </Button>
            <Button type="button" variant={view === "list" ? "secondary" : "ghost"} aria-pressed={view === "list"} onClick={() => setView("list")} aria-label="Chronological list view">
              <List aria-hidden="true" />
              List
            </Button>
          </div>
        </div>
        </CardContent>
      </Card>

      <section className="space-y-4" aria-live="polite" aria-busy={!hasProvidedEvents && calendarQuery.isPending}>
        <h2 className="text-lg font-semibold">{monthLabel(month)}</h2>
        {!hasProvidedEvents && calendarQuery.isPending ? (
          <LoadingState aria-label="Loading publication calendar" title="Loading publication calendar…" />
        ) : null}
        {!hasProvidedEvents && calendarQuery.isError ? (
          <ErrorState
            title="Publication calendar unavailable"
            description={getApiErrorMessage(calendarQuery.error, "Publication calendar could not be loaded")}
            action={<Button type="button" variant="outline" onClick={() => void calendarQuery.refetch()}>Retry calendar</Button>}
            dir="auto"
          />
        ) : null}
        {(hasProvidedEvents || calendarQuery.isSuccess) && eventsInWindow.length === 0 ? (
          <EmptyState title="No publication events in this calendar window." description="Scheduled and completed events will appear here." />
        ) : null}
        {(hasProvidedEvents || calendarQuery.isSuccess) && eventsInWindow.length > 0 && visibleEvents.length === 0 ? (
          <EmptyState title="No publication events match these filters." description="Change platform or status filters to see more events." />
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
  const weekCount = Math.ceil((firstWeekday + dayCount) / 7)
  const eventsByDay = new Map<string, CalendarEvent[]>()
  for (const event of events) {
    const key = dateKey(new Date(event.startsAt), timezone)
    eventsByDay.set(key, [...(eventsByDay.get(key) ?? []), event])
  }

  return (
    <div>
      <p className="mb-2 text-xs text-muted-foreground md:hidden">Scroll sideways to view the full month.</p>
      <div className="nc-panel max-w-full overflow-x-auto overscroll-x-contain" role="grid" aria-label={`${monthLabel(month)} calendar grid`}>
      <div className="min-w-[700px] bg-muted/50" role="rowgroup">
        <div className="grid grid-cols-7" role="row">
          {WEEKDAYS.map((weekday) => <div key={weekday} role="columnheader" className="border-b border-border/50 px-2 py-1.5 text-xs font-medium text-muted-foreground">{weekday}</div>)}
        </div>
      </div>
      <div className="min-w-[700px]" role="rowgroup">
        {Array.from({ length: weekCount }, (_, weekIndex) => (
          <div key={`week-${weekIndex}`} className="grid grid-cols-7" role="row">
            {Array.from({ length: 7 }, (_, weekdayIndex) => {
              const day = weekIndex * 7 + weekdayIndex - firstWeekday + 1
              if (day < 1 || day > dayCount) {
                return <div key={`outside-${weekIndex}-${weekdayIndex}`} role="gridcell" aria-label={`Outside ${monthLabel(month)}`} className="min-h-24 border-b border-e border-border/50 bg-muted/20" />
              }
              const key = localDateKey(month.year, month.month, day)
              const dayEvents = eventsByDay.get(key) ?? []
              return (
                <div key={key} role="gridcell" aria-label={key} className="min-h-24 space-y-1.5 border-b border-e border-border/50 p-1.5">
                  <div className="text-xs font-medium tabular-nums">{day}</div>
                  {dayEvents.length ? <ul className="space-y-1.5">{dayEvents.map((event) => <li key={event.id}><CalendarEventSummary event={event} timezone={timezone} compact /></li>)}</ul> : null}
                </div>
              )
            })}
          </div>
        ))}
      </div>
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
  const tone = calendarStatusTone(event.status)
  return (
    <article className={cn(
      "border border-border/50 bg-card",
      compact ? "space-y-1 rounded-md border-s-2 p-1.5 text-xs" : "space-y-2 rounded-lg p-3 shadow-xs",
      compact && statusBorderClass(tone),
    )}>
      <div className={cn("font-medium", compact && "line-clamp-2 leading-4")}><span>{platformLabel(event.platform)}: </span><DirectionBoundary as="span" language={null}>{event.title}</DirectionBoundary></div>
      <div className="flex flex-wrap items-center gap-1.5 text-muted-foreground">
        <time dateTime={event.startsAt}>{formatEventTime(event.startsAt, timezone, compact)}</time>
        {compact ? <span>· {humanize(event.status)}</span> : <StatusBadge tone={tone}>{humanize(event.status)}</StatusBadge>}
      </div>
      <Link className="inline-flex min-h-8 items-center rounded-sm text-primary underline underline-offset-2" href={event.actionUrl} aria-label={`Open ${platformLabel(event.platform)} event: ${event.title} (${event.id})`}>
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

function calendarStatusTone(status: string): StatusTone {
  if (["published", "succeeded", "completed"].includes(status)) return "success"
  if (["failed", "attention", "reconciliation_required"].includes(status)) return "error"
  if (["scheduled", "queued", "pending_review"].includes(status)) return "warning"
  if (["publishing", "running"].includes(status)) return "info"
  return "neutral"
}

function statusBorderClass(tone: StatusTone) {
  if (tone === "success") return "border-s-success"
  if (tone === "error") return "border-s-destructive"
  if (tone === "warning") return "border-s-warning"
  if (tone === "info") return "border-s-primary"
  return "border-s-muted-foreground"
}

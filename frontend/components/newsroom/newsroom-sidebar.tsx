"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import {
  Activity,
  Bot,
  CalendarDays,
  Clock3,
  Database,
  Files,
  Inbox,
  ListTodo,
  Menu,
  Newspaper,
  Settings,
  Trash2,
  X,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import type { JobSummary } from "@/features/jobs/types"
import { cn } from "@/lib/utils"

export type NewsroomNavItem = {
  readonly label: string
  readonly href: string
  readonly activeHref?: string
  readonly icon: LucideIcon
}

export const workflowNavItems = [
  { label: "Today", href: "/", icon: Newspaper },
  { label: "Inbox", href: "/inbox", icon: Inbox },
  { label: "Calendar", href: "/calendar", icon: CalendarDays },
  { label: "Library", href: "/feed", icon: Files },
] as const satisfies readonly NewsroomNavItem[]

const automationNavItems = [
  { label: "Job Queue", href: "/jobs", icon: ListTodo },
  { label: "Automations", href: "/automations", icon: Bot },
] as const satisfies readonly NewsroomNavItem[]

const collectionNavItems = [
  { label: "Sources", href: "/sources", icon: Database },
  { label: "Ingestion Runs", href: "/runs", icon: Clock3 },
] as const satisfies readonly NewsroomNavItem[]

const systemNavItems = [
  { label: "Diagnostics", href: "/diagnostics", icon: Activity },
  { label: "Content Settings", href: "/settings/content", icon: Settings },
  { label: "Retention", href: "/settings/retention", icon: Trash2 },
] as const satisfies readonly NewsroomNavItem[]

export const advancedNavSections = [
  {
    label: "Automation",
    items: automationNavItems,
  },
  {
    label: "Collection",
    items: collectionNavItems,
  },
  {
    label: "System",
    items: systemNavItems,
  },
] as const satisfies readonly { readonly label: string; readonly items: readonly NewsroomNavItem[] }[]

export const newsroomNavItems: readonly NewsroomNavItem[] = [
  ...workflowNavItems,
  ...automationNavItems,
  ...collectionNavItems,
  ...systemNavItems,
] as const

export function NewsroomSidebar({ summary }: { summary?: JobSummary }) {
  const pathname = usePathname()
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const advancedTriggerRef = useRef<HTMLButtonElement>(null)
  const advancedPanelRef = useRef<HTMLDivElement>(null)
  const advancedActive = advancedNavSections.some((section) =>
    section.items.some((item) => isCurrentPath(pathname, item.href)),
  )

  useEffect(() => {
    if (!advancedOpen) return
    queueMicrotask(() => advancedPanelRef.current?.querySelector<HTMLElement>("[data-advanced-item]")?.focus())
    const closeOnOutsidePress = (event: PointerEvent) => {
      const target = event.target as Node
      if (advancedPanelRef.current?.contains(target) || advancedTriggerRef.current?.contains(target)) return
      setAdvancedOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      event.preventDefault()
      setAdvancedOpen(false)
      queueMicrotask(() => advancedTriggerRef.current?.focus())
    }
    document.addEventListener("pointerdown", closeOnOutsidePress)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [advancedOpen])

  useEffect(() => setAdvancedOpen(false), [pathname])

  return (
    <aside aria-label="Global navigation" className="relative z-40 hidden h-screen border-r border-slate-800 bg-slate-950 text-slate-100 min-[900px]:sticky min-[900px]:top-0 min-[900px]:flex min-[900px]:w-[72px] min-[900px]:flex-col">
      <div className="flex h-16 shrink-0 items-center justify-center border-b border-slate-800">
        <div
          aria-label="NewsCraft"
          className="grid size-10 place-items-center rounded-xl bg-teal-700 text-lg font-bold text-white"
          role="img"
          title="NewsCraft"
        >
          N
        </div>
      </div>
      <nav aria-label="Newsroom navigation" className="flex min-h-0 flex-1 flex-col items-center gap-1 px-2 py-3">
        {workflowNavItems.map((item) => (
          <RailLink
            key={item.href}
            item={item}
            active={isNavItemCurrent(pathname, item)}
          />
        ))}

        <div className="my-2 h-px w-8 bg-slate-800" aria-hidden="true" />
        <div className="group/rail relative">
          <button
            aria-controls={advancedOpen ? "advanced-navigation-panel" : undefined}
            aria-current={advancedActive ? "page" : undefined}
            aria-expanded={advancedOpen}
            aria-haspopup="dialog"
            aria-label={summary?.attention
              ? `Advanced navigation, ${summary.attention} need attention`
              : "Advanced navigation"}
            className={cn(
              "relative grid size-11 cursor-pointer place-items-center rounded-lg text-slate-300 transition-colors hover:bg-slate-800 hover:text-white focus-visible:ring-2 focus-visible:ring-teal-400",
              advancedActive && "bg-teal-800/70 text-white",
            )}
            onClick={() => setAdvancedOpen((current) => !current)}
            ref={advancedTriggerRef}
            type="button"
          >
            <Menu className="size-5" aria-hidden="true" />
            {summary?.attention ? (
              <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-amber-400 px-1 text-center text-[10px] font-semibold leading-4 text-slate-950" aria-hidden="true">
                {summary.attention}
              </span>
            ) : null}
          </button>
          {!advancedOpen ? <RailTooltip>Advanced</RailTooltip> : null}
        </div>
      </nav>

      <div className="shrink-0 border-t border-slate-800 p-2">
        {summary ? (
          <div className="grid gap-1 text-[10px]" aria-label="Job summary">
            <div className="flex min-h-7 items-center justify-center gap-1 text-slate-300" title={`${summary.queued} queued`}>
              <ListTodo className="size-3.5" aria-hidden="true" />
              <span className="font-semibold tabular-nums" aria-label={`${summary.queued} queued`}>{summary.queued}</span>
            </div>
            <div className={cn("flex min-h-7 items-center justify-center gap-1 text-slate-400", summary.attention > 0 && "text-amber-300")} title={`${summary.attention} need attention`}>
              <Activity className="size-3.5" aria-hidden="true" />
              <span className="font-semibold tabular-nums" aria-label={`${summary.attention} need attention`}>{summary.attention}</span>
            </div>
          </div>
        ) : null}
      </div>

      {advancedOpen ? (
        <div
          aria-label="Advanced navigation"
          className="fixed left-[72px] top-3 z-40 max-h-[calc(100vh-1.5rem)] w-72 overflow-y-auto rounded-r-xl border bg-background p-3 text-foreground shadow-md"
          id="advanced-navigation-panel"
          onKeyDown={handleAdvancedKeyDown}
          ref={advancedPanelRef}
          role="dialog"
        >
          <div className="mb-3 flex items-center justify-between gap-2 px-1">
            <div>
              <h2 className="font-semibold">Advanced</h2>
              {summary ? (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {summary.queued} queued · {summary.attention} need attention
                </p>
              ) : null}
            </div>
            <button
              aria-label="Close advanced navigation"
              className="grid size-9 cursor-pointer place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => {
                setAdvancedOpen(false)
                queueMicrotask(() => advancedTriggerRef.current?.focus())
              }}
              type="button"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
          <div className="space-y-4">
            {advancedNavSections.map((section) => (
              <section aria-labelledby={`advanced-${section.label}`} key={section.label}>
                <h3 className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground" id={`advanced-${section.label}`}>
                  {section.label === "Collection" ? "Collection operations" : section.label}
                </h3>
                <div className="space-y-1">
                  {section.items.map((item) => (
                    <AdvancedLink
                      active={isCurrentPath(pathname, item.href)}
                      item={item}
                      key={item.href}
                      onNavigate={() => setAdvancedOpen(false)}
                      summary={item.href === "/jobs" ? summary : undefined}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      ) : null}
    </aside>
  )
}

export function isCurrentPath(pathname: string, href: string) {
  return href === "/" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`)
}

export function isNavItemCurrent(pathname: string, item: NewsroomNavItem) {
  return isCurrentPath(pathname, item.href)
    || (item.activeHref !== undefined && isCurrentPath(pathname, item.activeHref))
}

function RailLink({
  item,
  active,
}: {
  item: NewsroomNavItem
  active: boolean
}) {
  const Icon = item.icon

  return (
    <div className="group/rail relative">
      <Link
        href={item.href}
        aria-current={active ? "page" : undefined}
        aria-label={item.label}
        className={cn(
          "grid size-11 place-items-center rounded-lg text-slate-300 transition-colors hover:bg-slate-800 hover:text-white focus-visible:ring-2 focus-visible:ring-teal-400",
          active && "bg-teal-800/70 text-white",
        )}
      >
        <Icon className="size-5" aria-hidden="true" />
      </Link>
      <RailTooltip>{item.label}</RailTooltip>
    </div>
  )
}

function RailTooltip({ children }: { children: React.ReactNode }) {
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none invisible absolute left-[calc(100%+0.625rem)] top-1/2 z-50 w-max -translate-y-1/2 rounded-md bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white opacity-0 shadow-md transition-opacity group-hover/rail:visible group-hover/rail:opacity-100 group-focus-within/rail:visible group-focus-within/rail:opacity-100"
      role="tooltip"
    >
      {children}
    </span>
  )
}

function AdvancedLink({
  active,
  item,
  onNavigate,
  summary,
}: {
  active: boolean
  item: NewsroomNavItem
  onNavigate: () => void
  summary?: JobSummary
}) {
  const Icon = item.icon
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-10 items-center gap-3 rounded-lg px-2.5 text-sm font-medium hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
        active && "bg-accent text-accent-foreground",
      )}
      data-advanced-item
      href={item.href}
      onClick={onNavigate}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">{item.label}</span>
      {summary ? (
        <span className="text-[11px] font-normal tabular-nums text-muted-foreground">
          {summary.queued} queued · {summary.attention} attention
        </span>
      ) : null}
    </Link>
  )
}

function handleAdvancedKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[data-advanced-item]"))
  const index = items.indexOf(document.activeElement as HTMLElement)
  let nextIndex = index
  if (event.key === "ArrowDown") nextIndex = index < 0 ? 0 : (index + 1) % items.length
  if (event.key === "ArrowUp") nextIndex = index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length
  if (event.key === "Home") nextIndex = 0
  if (event.key === "End") nextIndex = items.length - 1
  event.preventDefault()
  items[nextIndex]?.focus()
}

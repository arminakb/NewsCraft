"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  Activity,
  Bot,
  CalendarDays,
  Database,
  Files,
  ListTodo,
  Newspaper,
  Settings,
  Trash2,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import type { JobSummary } from "@/features/jobs/types"
import { ThemeToggle } from "@/components/theme/theme-toggle"
import { cn } from "@/lib/utils"

export type NewsroomNavItem = {
  readonly label: string
  readonly href: string
  readonly activeHref?: string
  readonly icon: LucideIcon
}

export const primaryNavItems = [
  { label: "Today", href: "/", icon: Newspaper },
  { label: "Sources", href: "/sources", icon: Database },
  { label: "Calendar", href: "/calendar", icon: CalendarDays },
  { label: "Library", href: "/feed", icon: Files },
] as const satisfies readonly NewsroomNavItem[]

export const operationalNavItems = [
  { label: "Jobs", href: "/jobs", icon: ListTodo },
  { label: "Automations", href: "/automations", icon: Bot },
  { label: "Diagnostics", href: "/diagnostics", icon: Activity },
  { label: "Retention", href: "/settings/retention", icon: Trash2 },
] as const satisfies readonly NewsroomNavItem[]

export const settingsNavItem = {
  label: "Settings",
  href: "/settings/content",
  icon: Settings,
} as const satisfies NewsroomNavItem

export const newsroomNavItems: readonly NewsroomNavItem[] = [
  ...primaryNavItems,
  ...operationalNavItems,
] as const

export function NewsroomSidebar({ summary }: { summary?: JobSummary }) {
  const pathname = usePathname()

  return (
    <aside
      aria-label="Global navigation"
      className="desktop-newsroom-navigation relative z-40 hidden h-screen border-r border-sidebar-border/70 bg-sidebar text-sidebar-foreground min-[900px]:sticky min-[900px]:top-0 min-[900px]:col-start-1 min-[900px]:row-start-1 min-[900px]:flex min-[900px]:w-[260px] min-[900px]:flex-col"
      onKeyDown={handleRailKeyDown}
    >
      <div className="flex h-16 shrink-0 items-center gap-3 px-4">
        <div
          aria-label="NewsCraft"
          className="grid size-8 place-items-center rounded-[6px] bg-primary text-[13px] font-semibold text-primary-foreground shadow-sm"
          role="img"
          title="NewsCraft"
        >
          N
        </div>
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold leading-4">NewsCraft</div>
          <div className="truncate text-[11px] leading-4 text-muted-foreground">Newsroom operations</div>
        </div>
      </div>

      <nav aria-label="Newsroom navigation" className="flex min-h-0 flex-1 flex-col px-3 pb-3 pt-1">
        <NavGroupLabel>Workspace</NavGroupLabel>
        <div className="space-y-0.5">
          {primaryNavItems.map((item) => (
            <RailLink
              active={isNavItemCurrent(pathname, item)}
              item={item}
              key={item.href}
            />
          ))}
        </div>

        <NavGroupLabel className="mt-3">Operations</NavGroupLabel>
        <div className="space-y-0.5">
          {operationalNavItems.map((item) => (
            <RailLink
              active={isNavItemCurrent(pathname, item)}
              item={item}
              jobSummary={item.href === "/jobs" ? summary : undefined}
              key={item.href}
            />
          ))}
        </div>

        <div className="mt-auto flex shrink-0 flex-col items-start gap-0.5 pt-3" data-sidebar-controls>
          <ThemeToggle placement="sidebar" />
          <SettingsLink active={isNavItemCurrent(pathname, settingsNavItem)} />
        </div>
      </nav>

      {summary ? (
        <div aria-label="Job summary" className="sr-only">
          <span aria-label={`${summary.queued} queued`}>{summary.queued} queued</span>
          <span aria-label={`${summary.attention} need attention`}>{summary.attention} need attention</span>
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
  jobSummary,
}: {
  item: NewsroomNavItem
  active: boolean
  jobSummary?: JobSummary
}) {
  const Icon = item.icon
  const title = jobSummary
    ? `${item.label} · ${jobSummary.queued} queued · ${jobSummary.attention} need attention`
    : item.label

  return (
    <Link
      aria-current={active ? "page" : undefined}
      aria-label={item.label}
      className={cn(
        "group/rail relative flex min-h-9 min-w-0 items-center gap-2.5 rounded-[6px] px-2.5 py-[7px] text-[13px] font-medium leading-5 text-muted-foreground transition-colors duration-200 hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60",
        active && "bg-navigation-active font-semibold text-foreground",
      )}
      data-rail-link
      href={item.href}
      title={title}
    >
      <span className="relative shrink-0">
        <Icon
          className={cn(
            "size-4 text-muted-foreground/70 transition-colors group-hover/rail:text-foreground/70",
            active && "text-foreground",
          )}
          aria-hidden="true"
          strokeWidth={1.5}
        />
        {jobSummary?.attention ? (
          <span
            aria-hidden="true"
            className="absolute -right-2.5 -top-2 min-w-4 rounded-full bg-warning px-1 text-center text-[10px] font-bold leading-4 text-background"
          >
            {jobSummary.attention}
          </span>
        ) : null}
      </span>
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
    </Link>
  )
}

function SettingsLink({ active }: { active: boolean }) {
  return (
    <div className="group/settings relative">
      <Link
        aria-current={active ? "page" : undefined}
        aria-describedby="settings-navigation-tooltip"
        aria-label="Settings"
        className={cn(
          "grid size-11 place-items-center rounded-[7px] text-muted-foreground transition-colors duration-200 hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60",
          active && "bg-navigation-active text-foreground",
        )}
        data-rail-link
        href={settingsNavItem.href}
      >
        <Settings className="size-[17px]" aria-hidden="true" strokeWidth={1.5} />
      </Link>
      <span
        className="pointer-events-none invisible absolute left-[calc(100%+0.5rem)] top-1/2 z-50 w-max -translate-y-1/2 rounded-md bg-foreground px-2.5 py-1.5 text-xs font-medium text-background opacity-0 shadow-sm transition-opacity duration-150 group-hover/settings:visible group-hover/settings:opacity-100 group-focus-within/settings:visible group-focus-within/settings:opacity-100"
        id="settings-navigation-tooltip"
        role="tooltip"
      >
        Settings
      </span>
    </div>
  )
}

function NavGroupLabel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "mb-1 px-2.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground",
        className,
      )}
    >
      {children}
    </div>
  )
}

function handleRailKeyDown(event: React.KeyboardEvent<HTMLElement>) {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return

  const links = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[data-rail-link]"))
  const index = links.indexOf(document.activeElement as HTMLElement)
  let nextIndex = index

  if (event.key === "ArrowDown") nextIndex = index < 0 ? 0 : (index + 1) % links.length
  if (event.key === "ArrowUp") nextIndex = index < 0 ? links.length - 1 : (index - 1 + links.length) % links.length
  if (event.key === "Home") nextIndex = 0
  if (event.key === "End") nextIndex = links.length - 1

  event.preventDefault()
  links[nextIndex]?.focus()
}

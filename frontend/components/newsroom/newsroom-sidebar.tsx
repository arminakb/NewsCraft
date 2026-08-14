"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  Bot,
  Database,
  Files,
  Gauge,
  Newspaper,
  PanelLeftClose,
  Settings,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useEffect, useId, useRef } from "react"

import type { JobSummary } from "@/features/jobs/types"
import { ThemeToggle } from "@/components/theme/theme-toggle"
import {
  NotificationsTrigger,
  type NotificationsPopoverHandle,
} from "@/components/newsroom/notifications-sidebar"
import {
  rememberSettingsReturnPath,
  SETTINGS_RESTORE_FOCUS_KEY,
  settingsHref,
} from "@/features/settings/settings-sections"
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
  { label: "Feed", href: "/feed", icon: Files },
] as const satisfies readonly NewsroomNavItem[]

export const operationalNavItems = [
  { label: "Automations", href: "/automations", icon: Bot },
  { label: "Operations Center", href: "/operations", icon: Gauge },
] as const satisfies readonly NewsroomNavItem[]

export const settingsNavItem = {
  label: "Settings",
  href: settingsHref(),
  activeHref: "/settings",
  icon: Settings,
} as const satisfies NewsroomNavItem

export const newsroomNavItems: readonly NewsroomNavItem[] = [
  ...primaryNavItems,
  ...operationalNavItems,
] as const

export function NewsroomSidebar({
  expanded = false,
  onExpandedChange = () => undefined,
  onNotificationsOpen = () => undefined,
  notificationsHandle,
  notificationsOpen = false,
  summary,
}: {
  expanded?: boolean
  onExpandedChange?: (expanded: boolean) => void
  onNotificationsOpen?: (trigger: HTMLButtonElement, placement: "mobile" | "sidebar") => void
  notificationsHandle?: NotificationsPopoverHandle
  notificationsOpen?: boolean
  summary?: JobSummary
}) {
  const pathname = usePathname()
  const logoRef = useRef<HTMLButtonElement>(null)
  const settingsRef = useRef<HTMLAnchorElement>(null)
  const openTooltipId = useId()
  const closeTooltipId = useId()

  const closeSidebar = () => {
    onExpandedChange(false)
    window.requestAnimationFrame(() => logoRef.current?.focus())
  }

  useEffect(() => {
    if (pathname === "/settings") return
    if (window.sessionStorage.getItem(SETTINGS_RESTORE_FOCUS_KEY) !== "true") return
    window.requestAnimationFrame(() => {
      if (!settingsRef.current?.getClientRects().length) return
      settingsRef.current.focus()
      window.sessionStorage.removeItem(SETTINGS_RESTORE_FOCUS_KEY)
    })
  }, [pathname])

  return (
    <aside
      aria-label="Global navigation"
      className={cn(
        "desktop-newsroom-navigation relative z-40 hidden h-screen border-r border-sidebar-border/70 bg-sidebar text-sidebar-foreground min-[900px]:sticky min-[900px]:top-0 min-[900px]:col-start-1 min-[900px]:row-start-1 min-[900px]:flex min-[900px]:flex-col min-[900px]:transition-[width] min-[900px]:duration-[180ms] min-[900px]:ease-out motion-reduce:min-[900px]:transition-none",
        expanded ? "min-[900px]:w-[260px]" : "min-[900px]:w-[72px]",
      )}
      data-sidebar-state={expanded ? "expanded" : "collapsed"}
      id="newsroom-desktop-sidebar"
      onKeyDown={handleRailKeyDown}
    >
      <div
        className={cn(
          "relative flex h-16 shrink-0 items-center",
          expanded ? "px-3" : "justify-center px-2",
        )}
      >
        <div className="group/sidebar-tooltip min-w-0 flex-1">
          <button
            aria-controls="newsroom-desktop-sidebar"
            aria-describedby={!expanded ? openTooltipId : undefined}
            aria-expanded={expanded}
            aria-hidden={expanded || undefined}
            aria-label="Open sidebar"
            className={cn(
              "flex min-h-11 min-w-11 items-center rounded-[7px] text-left transition-colors duration-[180ms] hover:bg-navigation-hover active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none",
              expanded
                ? "pointer-events-none w-full gap-2.5 px-1 pr-12"
                : "mx-auto justify-center",
            )}
            onClick={() => onExpandedChange(true)}
            ref={logoRef}
            tabIndex={expanded ? -1 : 0}
            type="button"
          >
            <BrandMark />
            <span
              className={cn(
                "min-w-0 overflow-hidden whitespace-nowrap text-[13px] font-semibold leading-4 transition-[max-width,opacity,transform] duration-150 motion-reduce:transition-none",
                expanded
                  ? "max-w-40 translate-x-0 opacity-100 delay-75"
                  : "max-w-0 -translate-x-1 opacity-0",
              )}
            >
              NewsCraft
            </span>
          </button>
          {!expanded ? <SidebarTooltip id={openTooltipId}>Open sidebar</SidebarTooltip> : null}
        </div>

        <div
          aria-hidden={!expanded}
          className={cn(
            "group/sidebar-tooltip absolute right-2 top-2.5 shrink-0 transition-opacity duration-100 motion-reduce:transition-none",
            expanded
              ? "visible opacity-100 delay-75"
              : "invisible pointer-events-none opacity-0",
          )}
        >
          <button
            aria-controls="newsroom-desktop-sidebar"
            aria-describedby={closeTooltipId}
            aria-expanded={expanded}
            aria-label="Close sidebar"
            className="grid size-11 place-items-center rounded-[7px] text-muted-foreground transition-colors duration-[180ms] hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none"
            onClick={closeSidebar}
            tabIndex={expanded ? 0 : -1}
            type="button"
          >
            <PanelLeftClose className="size-[18px]" aria-hidden="true" strokeWidth={1.5} />
          </button>
          <SidebarTooltip align="right" id={closeTooltipId}>
            Close sidebar
          </SidebarTooltip>
        </div>
      </div>

      <nav
        aria-label="Newsroom navigation"
        className={cn(
          "flex min-h-0 flex-1 flex-col pb-3 pt-1",
          expanded ? "px-3" : "px-2",
        )}
      >
        <NavGroupLabel expanded={expanded}>Workspace</NavGroupLabel>
        <div className="space-y-1">
          {primaryNavItems.map((item) => (
            <RailLink
              active={isNavItemCurrent(pathname, item)}
              expanded={expanded}
              item={item}
              key={item.href}
            />
          ))}
        </div>

        <NavGroupLabel className={expanded ? "mt-3" : "mt-2"} expanded={expanded}>
          Operations
        </NavGroupLabel>
        <div className="space-y-1">
          {operationalNavItems.map((item) => (
            <RailLink
              active={isNavItemCurrent(pathname, item)}
              expanded={expanded}
              item={item}
              jobSummary={item.href === "/operations" ? summary : undefined}
              key={item.href}
            />
          ))}
        </div>

        <div
          className={cn(
            "mt-auto flex shrink-0 flex-col gap-1 pt-3",
            expanded ? "items-stretch" : "items-center",
          )}
          data-sidebar-controls
        >
          <NotificationsTrigger
            expanded={expanded}
            handle={notificationsHandle}
            onOpen={onNotificationsOpen}
            open={notificationsOpen}
          />
          <ThemeToggle expanded={expanded} placement="sidebar" />
          <SettingsLink
            active={isNavItemCurrent(pathname, settingsNavItem)}
            expanded={expanded}
            linkRef={settingsRef}
          />
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
  const target = href.split("?", 1)[0]
  return target === "/" ? pathname === target : pathname === target || pathname.startsWith(`${target}/`)
}

export function isNavItemCurrent(pathname: string, item: NewsroomNavItem) {
  return isCurrentPath(pathname, item.href)
    || (item.activeHref !== undefined && isCurrentPath(pathname, item.activeHref))
}

function RailLink({
  item,
  active,
  expanded,
  jobSummary,
}: {
  item: NewsroomNavItem
  active: boolean
  expanded: boolean
  jobSummary?: JobSummary
}) {
  const Icon = item.icon
  const tooltipId = `desktop-${item.href === "/" ? "today" : item.href.slice(1).replaceAll("/", "-")}-tooltip`

  return (
    <div className="group/sidebar-tooltip relative">
      <Link
        aria-current={active ? "page" : undefined}
        aria-describedby={!expanded ? tooltipId : undefined}
        aria-label={item.label}
        className={cn(
          "group/rail relative flex min-h-11 min-w-0 items-center rounded-[7px] text-[13px] font-medium leading-5 text-muted-foreground transition-[background-color,color,padding,gap] duration-[180ms] hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none",
          expanded ? "w-full justify-start gap-2.5 px-2.5" : "mx-auto size-11 justify-center",
          active && "bg-navigation-active font-semibold text-primary",
        )}
        data-rail-link
        href={item.href}
      >
        <span className="relative shrink-0">
          <Icon
            className={cn(
              "size-[18px] text-muted-foreground/80 transition-colors duration-[180ms] group-hover/rail:text-foreground motion-reduce:transition-none",
              active && "text-primary",
            )}
            aria-hidden="true"
            strokeWidth={1.5}
          />
          {expanded && jobSummary?.attention ? (
            <span
              aria-hidden="true"
              className="absolute -right-2.5 -top-2 min-w-4 rounded-full bg-warning px-1 text-center text-[10px] font-bold leading-4 text-background"
            >
              {jobSummary.attention}
            </span>
          ) : null}
        </span>
        <span
          aria-hidden={!expanded}
          className={cn(
            "min-w-0 overflow-hidden whitespace-nowrap transition-[max-width,opacity,transform] duration-150 motion-reduce:transition-none",
            expanded
              ? "max-w-40 translate-x-0 opacity-100 delay-75"
              : "max-w-0 -translate-x-1 opacity-0",
          )}
        >
          {item.label}
        </span>
      </Link>
      {!expanded ? <SidebarTooltip id={tooltipId}>{item.label}</SidebarTooltip> : null}
    </div>
  )
}

function SettingsLink({
  active,
  expanded,
  linkRef,
}: {
  active: boolean
  expanded: boolean
  linkRef: React.Ref<HTMLAnchorElement>
}) {
  const tooltipId = "desktop-settings-tooltip"

  return (
    <div className="group/sidebar-tooltip relative">
      <Link
        aria-current={active ? "page" : undefined}
        aria-describedby={!expanded ? tooltipId : undefined}
        aria-label="Settings"
        className={cn(
          "flex min-h-11 min-w-11 items-center rounded-[7px] text-[13px] font-medium text-muted-foreground transition-[background-color,color,padding,gap] duration-[180ms] hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none",
          expanded ? "w-full justify-start gap-2.5 px-2.5" : "justify-center",
          active && "bg-navigation-active text-primary",
        )}
        data-settings-trigger
        data-rail-link
        href={settingsNavItem.href}
        onClick={rememberSettingsReturnPath}
        ref={linkRef}
      >
        <Settings className="size-[18px] shrink-0" aria-hidden="true" strokeWidth={1.5} />
        <span
          aria-hidden={!expanded}
          className={cn(
            "overflow-hidden whitespace-nowrap transition-[max-width,opacity,transform] duration-150 motion-reduce:transition-none",
            expanded
              ? "max-w-40 translate-x-0 opacity-100 delay-75"
              : "max-w-0 -translate-x-1 opacity-0",
          )}
        >
          Settings
        </span>
      </Link>
      {!expanded ? <SidebarTooltip id={tooltipId}>Settings</SidebarTooltip> : null}
    </div>
  )
}

function NavGroupLabel({
  children,
  className,
  expanded,
}: {
  children: React.ReactNode
  className?: string
  expanded: boolean
}) {
  return (
    <div
      aria-hidden={!expanded}
      className={cn(
        "overflow-hidden whitespace-nowrap px-2.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground transition-[max-height,margin,opacity,transform] duration-150 motion-reduce:transition-none",
        expanded
          ? "mb-1 max-h-5 translate-x-0 opacity-100 delay-75"
          : "mb-0 max-h-0 -translate-x-1 opacity-0",
        className,
      )}
    >
      {children}
    </div>
  )
}

function BrandMark() {
  return (
    <span
      aria-hidden="true"
      className="grid size-8 shrink-0 place-items-center rounded-[6px] bg-primary-solid text-[13px] font-semibold text-primary-solid-foreground shadow-sm"
    >
      N
    </span>
  )
}

function SidebarTooltip({
  align = "center",
  children,
  id,
}: {
  align?: "center" | "right"
  children: React.ReactNode
  id: string
}) {
  return (
    <span
      className={cn(
        "pointer-events-none invisible absolute left-[calc(100%+0.5rem)] z-50 w-max rounded-md border border-border/50 bg-popover px-2.5 py-1.5 text-xs font-medium text-popover-foreground opacity-0 shadow-md transition-opacity duration-150 group-hover/sidebar-tooltip:visible group-hover/sidebar-tooltip:opacity-100 group-focus-within/sidebar-tooltip:visible group-focus-within/sidebar-tooltip:opacity-100 motion-reduce:transition-none",
        align === "right" ? "top-full mt-1" : "top-1/2 -translate-y-1/2",
      )}
      id={id}
      role="tooltip"
    >
      {children}
    </span>
  )
}

function handleRailKeyDown(event: React.KeyboardEvent<HTMLElement>) {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return

  const links = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[data-rail-link]"))
  if (!links.length) return
  const index = links.indexOf(document.activeElement as HTMLElement)
  let nextIndex = index

  if (event.key === "ArrowDown") nextIndex = index < 0 ? 0 : (index + 1) % links.length
  if (event.key === "ArrowUp") nextIndex = index < 0 ? links.length - 1 : (index - 1 + links.length) % links.length
  if (event.key === "Home") nextIndex = 0
  if (event.key === "End") nextIndex = links.length - 1

  event.preventDefault()
  links[nextIndex]?.focus()
}

"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Menu, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import {
  isNavItemCurrent,
  newsroomNavItems,
  primaryNavItems,
  settingsNavItem,
  type NewsroomNavItem,
} from "@/components/newsroom/newsroom-sidebar"
import {
  NotificationsTrigger,
  type NotificationsPopoverHandle,
} from "@/components/newsroom/notifications-sidebar"
import { ThemeToggle } from "@/components/theme/theme-toggle"
import {
  rememberSettingsReturnPath,
  SETTINGS_RESTORE_FOCUS_KEY,
} from "@/features/settings/settings-sections"
import { cn } from "@/lib/utils"

const mobilePrimaryItems = primaryNavItems

export function MobileNewsroomNav({
  notificationsHandle,
  notificationsOpen = false,
  onNotificationsOpen = () => undefined,
}: {
  notificationsHandle?: NotificationsPopoverHandle
  notificationsOpen?: boolean
  onNotificationsOpen?: (trigger: HTMLButtonElement, placement: "mobile" | "sidebar") => void
}) {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const firstLinkRef = useRef<HTMLAnchorElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const menuActive = [...newsroomNavItems.slice(primaryNavItems.length), settingsNavItem]
    .some((item) => isNavItemCurrent(pathname, item))

  const closeAndRestore = useCallback(() => {
    setOpen(false)
    triggerRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!open) return

    const previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    firstLinkRef.current?.focus()

    const keepFocusInDialog = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        closeAndRestore()
        return
      }
      if (event.key !== "Tab") return

      const focusableElements = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )
      if (!focusableElements.length) return

      const first = focusableElements[0]
      const last = focusableElements.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("keydown", keepFocusInDialog)
    return () => {
      document.removeEventListener("keydown", keepFocusInDialog)
      document.body.style.overflow = previousBodyOverflow
    }
  }, [closeAndRestore, open])

  useEffect(() => {
    setOpen(false)
    if (pathname === "/settings") return
    if (window.sessionStorage.getItem(SETTINGS_RESTORE_FOCUS_KEY) !== "true") return
    window.requestAnimationFrame(() => {
      if (!triggerRef.current?.getClientRects().length) return
      triggerRef.current.focus()
      window.sessionStorage.removeItem(SETTINGS_RESTORE_FOCUS_KEY)
    })
  }, [pathname])

  return (
    <>
      {open ? (
        <div className="fixed inset-0 z-50 min-[900px]:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 size-full cursor-default bg-background/45 backdrop-blur-[2px]"
            data-testid="mobile-navigation-backdrop"
            onClick={closeAndRestore}
            type="button"
          />
          <div
            aria-label="Newsroom navigation"
            aria-modal="true"
            className="absolute inset-x-3 bottom-[calc(5rem+env(safe-area-inset-bottom))] flex max-h-[calc(100dvh-6rem-env(safe-area-inset-bottom))] flex-col rounded-xl border border-border/50 bg-card p-3 shadow-md ring-1 ring-foreground/5"
            id="newsroom-mobile-navigation"
            ref={dialogRef}
            role="dialog"
          >
            <div className="mb-2 flex min-h-11 shrink-0 items-center justify-between gap-3 px-1">
              <div>
                <h2 className="text-sm font-semibold">Navigate NewsCraft</h2>
                <p className="text-xs text-muted-foreground">Choose a workspace</p>
              </div>
              <div className="flex items-center gap-2">
                <NotificationsTrigger
                  handle={notificationsHandle}
                  onOpen={(trigger) => {
                    setOpen(false)
                    onNotificationsOpen(triggerRef.current ?? trigger, "mobile")
                  }}
                  open={notificationsOpen}
                  placement="mobile"
                />
                <ThemeToggle placement="mobile" />
                <button
                  aria-label="Close navigation panel"
                  className="grid size-11 place-items-center rounded-[7px] text-muted-foreground transition-colors hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60"
                  onClick={closeAndRestore}
                  type="button"
                >
                  <X className="size-[18px]" aria-hidden="true" strokeWidth={1.5} />
                </button>
              </div>
            </div>
            <nav
              aria-label="Mobile navigation panel"
              className="grid min-h-0 grid-cols-2 gap-1 overflow-y-auto overscroll-contain"
            >
              {[...newsroomNavItems, settingsNavItem].map((item, index) => (
                <MobilePanelLink
                  active={isNavItemCurrent(pathname, item)}
                  item={item}
                  key={item.href}
                  linkRef={index === 0 ? firstLinkRef : undefined}
                  onNavigate={() => setOpen(false)}
                />
              ))}
            </nav>
          </div>
        </div>
      ) : null}

      <nav
        aria-label="Mobile newsroom navigation"
        className="mobile-newsroom-navigation fixed inset-x-0 bottom-0 z-40 grid min-h-16 grid-cols-4 border-t border-sidebar-border/70 bg-sidebar/95 px-2 pb-[max(0.25rem,env(safe-area-inset-bottom))] pt-1 backdrop-blur min-[900px]:hidden"
      >
        {mobilePrimaryItems.map((item) => (
          <MobileBarLink
            active={isNavItemCurrent(pathname, item)}
            item={item}
            key={item.href}
          />
        ))}
        <button
          aria-controls="newsroom-mobile-navigation"
          aria-expanded={open}
          aria-haspopup="dialog"
          aria-label="Open navigation"
          className={cn(
            "relative flex min-h-11 min-w-11 flex-col items-center justify-center gap-0.5 rounded-[7px] px-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60",
            menuActive && "bg-navigation-active font-semibold text-primary",
          )}
          data-settings-trigger
          onClick={() => setOpen(true)}
          ref={triggerRef}
          type="button"
        >
          <Menu className="size-[18px]" aria-hidden="true" strokeWidth={1.5} />
          Menu
        </button>
      </nav>
    </>
  )
}

function MobileBarLink({ item, active }: { item: NewsroomNavItem; active: boolean }) {
  const Icon = item.icon
  return (
    <Link
      aria-current={active ? "page" : undefined}
      aria-label={item.label}
      className={cn(
        "relative flex min-h-11 min-w-11 flex-col items-center justify-center gap-0.5 rounded-[7px] px-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60",
        active && "bg-navigation-active font-semibold text-primary",
      )}
      href={item.href}
    >
      <Icon className="size-[18px]" aria-hidden="true" strokeWidth={1.5} />
      {item.label}
    </Link>
  )
}

function MobilePanelLink({
  active,
  item,
  linkRef,
  onNavigate,
}: {
  active: boolean
  item: NewsroomNavItem
  linkRef?: React.Ref<HTMLAnchorElement>
  onNavigate: () => void
}) {
  const Icon = item.icon
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-12 items-center gap-2.5 rounded-[7px] px-2.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60",
        active && "bg-navigation-active text-primary",
      )}
      href={item.href}
      onClick={() => {
        if (item.label === "Settings") rememberSettingsReturnPath()
        onNavigate()
      }}
      ref={linkRef}
    >
      <Icon className={cn("size-4 text-muted-foreground/70", active && "text-primary")} aria-hidden="true" strokeWidth={1.5} />
      {item.label}
    </Link>
  )
}

"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Menu, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import {
  advancedNavSections,
  isCurrentPath,
  isNavItemCurrent,
  newsroomNavItems,
  workflowNavItems,
} from "@/components/newsroom/newsroom-sidebar"
import { cn } from "@/lib/utils"

export function MobileNewsroomNav() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const firstLinkRef = useRef<HTMLAnchorElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

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
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ) ?? []
      )
      if (focusableElements.length === 0) return

      const firstFocusable = focusableElements[0]
      const lastFocusable = focusableElements.at(-1)
      const activeElement = document.activeElement

      if (event.shiftKey && (activeElement === firstFocusable || !dialogRef.current?.contains(activeElement))) {
        event.preventDefault()
        lastFocusable?.focus()
      } else if (!event.shiftKey && activeElement === lastFocusable) {
        event.preventDefault()
        firstFocusable.focus()
      }
    }
    const closeAtDesktopBreakpoint = () => {
      if (window.innerWidth >= 900) closeAndRestore()
    }
    document.addEventListener("keydown", keepFocusInDialog)
    window.addEventListener("resize", closeAtDesktopBreakpoint)
    return () => {
      document.removeEventListener("keydown", keepFocusInDialog)
      window.removeEventListener("resize", closeAtDesktopBreakpoint)
      document.body.style.overflow = previousBodyOverflow
    }
  }, [closeAndRestore, open])

  return (
    <>
      {open ? (
        <div className="fixed inset-0 z-50 min-[900px]:hidden">
          <div
            aria-hidden="true"
            data-testid="mobile-navigation-backdrop"
            className="absolute inset-0 min-h-11 min-w-11 bg-slate-950/40"
            onClick={closeAndRestore}
          />
          <div
            ref={dialogRef}
            id="newsroom-mobile-navigation"
            role="dialog"
            aria-label="Newsroom navigation"
            aria-modal="true"
            className="absolute inset-x-3 bottom-20 max-h-[calc(100dvh-6rem)] min-w-0 overscroll-contain overflow-y-auto rounded-lg border bg-white p-3 shadow-xl dark:bg-background"
          >
            <div className="mb-2 flex min-h-11 items-center justify-between gap-3 px-2">
              <span className="font-semibold">Navigate NewsCraft</span>
              <button
                type="button"
                aria-label="Close navigation"
                className="inline-flex size-11 items-center justify-center rounded-md hover:bg-muted"
                onClick={closeAndRestore}
              >
                <X className="size-5" aria-hidden="true" />
              </button>
            </div>
            <nav aria-label="Mobile navigation panel">
              <MobileGroupLabel>Workflow</MobileGroupLabel>
              <div className="space-y-1">
                {workflowNavItems.map((item, index) => {
                  const Icon = item.icon
                  const active = isNavItemCurrent(pathname, item)
                  return (
                    <Link
                      key={item.href}
                      ref={index === 0 ? firstLinkRef : undefined}
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex min-h-11 min-w-11 items-center gap-3 rounded-md px-3 text-sm font-medium",
                        active ? "bg-accent text-accent-foreground" : "hover:bg-muted"
                      )}
                      onClick={closeAndRestore}
                    >
                      <Icon className="size-5" aria-hidden="true" />
                      {item.label}
                    </Link>
                  )
                })}
              </div>

              <div className="my-3 border-t" />
              <MobileGroupLabel>Advanced</MobileGroupLabel>
              <div className="space-y-4 pt-1">
                {advancedNavSections.map((section) => (
                  <div key={section.label}>
                    <div className="px-3 pb-1 text-xs font-medium text-slate-600 dark:text-slate-300">{section.label}</div>
                    <div className="space-y-1">
                      {section.items.map((item) => {
                        const Icon = item.icon
                        const active = isCurrentPath(pathname, item.href)
                        return (
                          <Link
                            key={item.href}
                            href={item.href}
                            aria-current={active ? "page" : undefined}
                            className={cn(
                              "flex min-h-11 min-w-11 items-center gap-3 rounded-md px-3 text-sm font-medium",
                              active ? "bg-accent text-accent-foreground" : "hover:bg-muted"
                            )}
                            onClick={closeAndRestore}
                          >
                            <Icon className="size-5" aria-hidden="true" />
                            {item.label}
                          </Link>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </nav>
          </div>
        </div>
      ) : null}

      <nav
        aria-label="Mobile newsroom navigation"
        className="fixed inset-x-0 bottom-0 z-40 grid min-h-16 grid-cols-3 border-t bg-white/95 px-2 py-1 backdrop-blur dark:bg-background/95 min-[900px]:hidden"
      >
        {newsroomNavItems.slice(0, 2).map((item) => {
          const Icon = item.icon
          const active = isCurrentPath(pathname, item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-11 min-w-11 flex-col items-center justify-center gap-0.5 rounded-md px-2 text-xs font-medium",
                active ? "text-primary" : "text-muted-foreground hover:bg-muted"
              )}
            >
              <Icon className="size-5" aria-hidden="true" />
              {item.label}
            </Link>
          )
        })}
        <button
          ref={triggerRef}
          type="button"
          aria-label="Open navigation"
          aria-controls="newsroom-mobile-navigation"
          aria-expanded={open}
          aria-haspopup="dialog"
          className="flex min-h-11 min-w-11 flex-col items-center justify-center gap-0.5 rounded-md px-2 text-xs font-medium text-muted-foreground hover:bg-muted"
          onClick={() => setOpen(true)}
        >
          <Menu className="size-5" aria-hidden="true" />
          Menu
        </button>
      </nav>
    </>
  )
}

function MobileGroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-600 dark:text-slate-300">
      {children}
    </div>
  )
}

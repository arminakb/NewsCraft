"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Menu, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { isCurrentPath, newsroomNavItems } from "@/components/newsroom/newsroom-sidebar"
import { cn } from "@/lib/utils"

export function MobileNewsroomNav() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const firstLinkRef = useRef<HTMLAnchorElement>(null)

  useEffect(() => {
    if (!open) return

    firstLinkRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener("keydown", closeOnEscape)
    return () => document.removeEventListener("keydown", closeOnEscape)
  }, [open])

  const closeAndRestore = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  return (
    <>
      {open ? (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            aria-hidden="true"
            className="absolute inset-0 min-h-11 min-w-11 bg-slate-950/40"
            onClick={closeAndRestore}
          />
          <div
            id="newsroom-mobile-navigation"
            role="dialog"
            aria-label="Newsroom navigation"
            className="absolute inset-x-3 bottom-20 max-h-[calc(100dvh-6rem)] overflow-y-auto rounded-lg border bg-white p-3 shadow-xl"
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
            <nav aria-label="Mobile navigation panel" className="space-y-1">
              {newsroomNavItems.map((item, index) => {
                const Icon = item.icon
                const active = isCurrentPath(pathname, item.href)
                return (
                  <Link
                    key={item.href}
                    ref={index === 0 ? firstLinkRef : undefined}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium",
                      active ? "bg-accent text-accent-foreground" : "hover:bg-muted"
                    )}
                    onClick={() => setOpen(false)}
                  >
                    <Icon className="size-5" aria-hidden="true" />
                    {item.label}
                  </Link>
                )
              })}
            </nav>
          </div>
        </div>
      ) : null}

      <nav
        aria-label="Mobile newsroom navigation"
        className="fixed inset-x-0 bottom-0 z-40 grid min-h-16 grid-cols-3 border-t bg-white/95 px-2 py-1 backdrop-blur md:hidden"
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
                "flex min-h-11 flex-col items-center justify-center gap-0.5 rounded-md px-2 text-xs font-medium",
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
          className="flex min-h-11 flex-col items-center justify-center gap-0.5 rounded-md px-2 text-xs font-medium text-muted-foreground hover:bg-muted"
          onClick={() => setOpen(true)}
        >
          <Menu className="size-5" aria-hidden="true" />
          Menu
        </button>
      </nav>
    </>
  )
}

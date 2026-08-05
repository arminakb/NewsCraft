"use client"

import { Bell } from "lucide-react"
import { useEffect, useId, useRef } from "react"

import { useOptionalNotices } from "@/components/providers/notice-provider"
import { NotificationsMenu, type Notification } from "@/components/ui/notifications-menu"
import { Sheet, SheetContent } from "@/components/ui/sheet"
import { adaptNoticesToNotifications } from "@/features/notifications/adapter"
import { cn } from "@/lib/utils"

export type NotificationRecord = Notification

export function NotificationsSidebar({
  error = null,
  loading = false,
  notifications,
  onOpenChange,
  open,
}: {
  error?: string | null
  loading?: boolean
  notifications?: readonly NotificationRecord[]
  onOpenChange: (open: boolean) => void
  open: boolean
}) {
  const noticeContext = useOptionalNotices()
  const closeRef = useRef<HTMLButtonElement>(null)
  const noticeRecords = noticeContext ? adaptNoticesToNotifications(noticeContext.notices) : []
  const records = notifications ?? noticeRecords
  const canManageNoticeState = notifications === undefined && noticeContext !== null

  useEffect(() => {
    if (open) closeRef.current?.focus()
  }, [open])

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        aria-label="Your notifications"
        className="h-dvh w-[min(100vw,32.5rem)] max-w-none translate-x-0 rounded-none border-y-0 border-r-0 border-l border-border/70 bg-card p-0 shadow-lg transition-[transform,opacity] duration-300 ease-out data-ending-style:translate-x-full data-ending-style:opacity-0 data-starting-style:translate-x-full data-starting-style:opacity-0 motion-reduce:transition-none"
        id="newsroom-notifications"
        initialFocus={() => closeRef.current}
        side="right"
      >
        <div className="h-full overflow-y-auto overscroll-contain">
          <NotificationsMenu
            closeButtonRef={closeRef}
            error={error}
            loading={loading}
            notifications={records}
            onClearAll={canManageNoticeState ? noticeContext.clearNotices : undefined}
            onClose={() => onOpenChange(false)}
            onDismiss={canManageNoticeState ? (id) => noticeContext.dismissNotice(String(id)) : undefined}
          />
        </div>
      </SheetContent>
    </Sheet>
  )
}

export function NotificationsTrigger({
  expanded = false,
  onOpen,
  open = false,
  placement = "sidebar",
}: {
  expanded?: boolean
  onOpen: (trigger: HTMLButtonElement) => void
  open?: boolean
  placement?: "mobile" | "sidebar"
}) {
  const tooltipId = useId()
  const noticeContext = useOptionalNotices()
  const count = noticeContext?.notices.length ?? 0
  const showLabel = placement === "sidebar" && expanded
  const showTooltip = !showLabel
  const countDescriptionId = `${tooltipId}-count`

  return (
    <div className="group/notifications relative">
      <button
        aria-controls="newsroom-notifications"
        aria-describedby={count > 0 ? countDescriptionId : showTooltip ? tooltipId : undefined}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="Open notifications"
        className={cn(
          "relative flex min-h-11 min-w-11 items-center rounded-[7px] text-[13px] font-medium text-muted-foreground transition-[background-color,color,padding,gap] duration-[180ms] hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none",
          showLabel ? "w-full justify-start gap-2.5 px-2.5" : "justify-center",
          open && "bg-navigation-active text-primary",
          placement === "mobile" && "shrink-0",
        )}
        data-notifications-trigger
        onClick={(event) => onOpen(event.currentTarget)}
        type="button"
      >
        <span className="relative grid size-[18px] shrink-0 place-items-center">
          <Bell aria-hidden="true" className="size-[17px]" strokeWidth={1.5} />
          {count > 0 ? (
            <span
              aria-hidden="true"
              className="absolute -right-2 -top-2 min-w-4 rounded-full bg-primary-solid px-1 text-center text-[10px] font-bold leading-4 text-primary-solid-foreground"
            >
              {count > 99 ? "99+" : count}
            </span>
          ) : null}
        </span>
        {placement === "sidebar" ? (
          <span
            aria-hidden={!showLabel}
            className={cn(
              "overflow-hidden whitespace-nowrap transition-[max-width,opacity,transform] duration-150 motion-reduce:transition-none",
              showLabel
                ? "max-w-40 translate-x-0 opacity-100 delay-75"
                : "max-w-0 -translate-x-1 opacity-0",
            )}
          >
            Notifications
          </span>
        ) : null}
      </button>
      {count > 0 ? (
        <span className="sr-only" id={countDescriptionId}>
          {count} active {count === 1 ? "notification" : "notifications"}
        </span>
      ) : null}
      {showTooltip ? (
        <span
          className={cn(
            "pointer-events-none invisible absolute z-50 w-max rounded-md border border-border/50 bg-popover px-2.5 py-1.5 text-xs font-medium text-popover-foreground opacity-0 shadow-md transition-opacity duration-150 group-hover/notifications:visible group-hover/notifications:opacity-100 group-focus-within/notifications:visible group-focus-within/notifications:opacity-100 motion-reduce:transition-none",
            placement === "sidebar"
              ? "left-[calc(100%+0.5rem)] top-1/2 -translate-y-1/2"
              : "right-0 top-[calc(100%+0.5rem)]",
          )}
          id={tooltipId}
          role="tooltip"
        >
          Notifications
        </span>
      ) : null}
    </div>
  )
}

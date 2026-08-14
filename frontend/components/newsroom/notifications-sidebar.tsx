"use client"

import { Popover } from "@base-ui/react/popover"
import { Bell } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"

import { useOptionalNotices } from "@/components/providers/notice-provider"
import { NotificationsMenu, type Notification } from "@/components/ui/notifications-menu"
import { adaptNoticesToNotifications } from "@/features/notifications/adapter"
import { getDevelopmentNotificationFixture } from "@/features/notifications/dev-fixture"
import { cn } from "@/lib/utils"

export type NotificationRecord = Notification
export type NotificationsPopoverHandle = Popover.Handle<unknown>

export function NotificationsSidebar({
  error = null,
  loading = false,
  notifications,
  handle,
  onOpenChange,
  open,
  placement = "sidebar",
  trigger,
}: {
  error?: string | null
  handle?: NotificationsPopoverHandle
  loading?: boolean
  notifications?: readonly NotificationRecord[]
  onOpenChange: (open: boolean) => void
  open: boolean
  placement?: "mobile" | "sidebar"
  trigger?: HTMLElement | null
}) {
  const noticeContext = useOptionalNotices()
  const closeRef = useRef<HTMLButtonElement>(null)
  const [developmentFixtures, setDevelopmentFixtures] = useState<readonly NotificationRecord[]>([])
  const noticeRecords = noticeContext ? adaptNoticesToNotifications(noticeContext.retainedNotices) : []
  const fixtureRecords = notifications === undefined ? developmentFixtures : []
  const records = notifications ?? [...noticeRecords, ...fixtureRecords]
  const canDismissNoticeState = notifications === undefined && noticeContext !== null

  useEffect(() => {
    setDevelopmentFixtures(getDevelopmentNotificationFixture())
  }, [])

  useEffect(() => {
    if (open) closeRef.current?.focus()
  }, [open])

  const popupAnchor =
    placement === "sidebar"
      ? trigger?.closest<HTMLElement>("#newsroom-desktop-sidebar") ?? trigger
      : trigger

  return (
    <Popover.Root handle={handle} modal="trap-focus" onOpenChange={onOpenChange} open={open}>
      <Popover.Portal>
        <Popover.Backdrop
          className="nc-dialog-scrim fixed inset-0 z-40 bg-background/45 backdrop-blur-[2px] transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0 motion-reduce:transition-none"
          onClick={() => onOpenChange(false)}
        />
        <Popover.Positioner
          anchor={popupAnchor ?? undefined}
          align="end"
          className="z-50"
          collisionAvoidance={{ align: "shift", fallbackAxisSide: "end", side: "flip" }}
          collisionPadding={8}
          data-notifications-positioner
          side={placement === "mobile" ? "top" : "left"}
          sideOffset={12}
        >
          <Popover.Popup
            aria-label="Your notifications"
            aria-modal="true"
            className="nc-notifications-popup h-[575px] w-[450px] min-h-0 min-w-0 max-h-[calc(100dvh-1rem)] max-w-[calc(100vw-1rem)] overflow-hidden rounded-xl border border-border/70 bg-card p-0 text-card-foreground shadow-lg outline-none transition-[scale,opacity] duration-180 ease-out data-ending-style:scale-[0.98] data-ending-style:opacity-0 data-starting-style:scale-[0.98] data-starting-style:opacity-0 motion-reduce:transition-none"
            finalFocus={trigger ? () => trigger : undefined}
            id="newsroom-notifications"
            initialFocus={() => closeRef.current}
            role="dialog"
          >
            <NotificationsMenu
              closeButtonRef={closeRef}
              closeWithPopover
              error={error}
              loading={loading}
              notifications={records}
              onClose={() => onOpenChange(false)}
              onDismiss={canDismissNoticeState ? (id) => noticeContext.dismissNotice(String(id)) : undefined}
            />
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  )
}

export function NotificationsTrigger({
  expanded = false,
  handle,
  onOpen,
  open = false,
  placement = "sidebar",
}: {
  expanded?: boolean
  handle?: NotificationsPopoverHandle
  onOpen: (trigger: HTMLButtonElement, placement: "mobile" | "sidebar") => void
  open?: boolean
  placement?: "mobile" | "sidebar"
}) {
  const tooltipId = useId()
  const noticeContext = useOptionalNotices()
  const count = noticeContext?.retainedNotices.length ?? 0
  const showLabel = placement === "sidebar" && expanded
  const showTooltip = !showLabel
  const countDescriptionId = `${tooltipId}-count`

  const button = (
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
      onClick={(event) => onOpen(event.currentTarget, placement)}
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
  )

  return (
    <div className="group/notifications relative">
      {handle ? <Popover.Trigger handle={handle} render={button} /> : button}
      {count > 0 ? (
        <span className="sr-only" id={countDescriptionId}>
          {count} retained {count === 1 ? "notification" : "notifications"}
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

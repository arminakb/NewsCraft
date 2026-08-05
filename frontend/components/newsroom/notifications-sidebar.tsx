"use client"

import {
  Bell,
  CheckCheck,
  CheckCircle2,
  CircleAlert,
  Info,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react"
import { useEffect, useId, useMemo, useRef, useState } from "react"

import { useOptionalNotices } from "@/components/providers/notice-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Tabs, TabsList, TabsTab } from "@/components/ui/tabs"
import type { AlertTone } from "@/components/ui/alert"
import { cn } from "@/lib/utils"

export type NotificationRecord = {
  id: string
  title: string
  message: string
  tone: AlertTone
  createdAt: number
}

type NotificationFilter = "all" | "success" | "attention"

const toneConfig: Record<AlertTone, { Icon: LucideIcon; className: string }> = {
  error: { Icon: CircleAlert, className: "bg-[var(--error-surface)] text-destructive" },
  info: { Icon: Info, className: "bg-muted text-muted-foreground" },
  success: { Icon: CheckCircle2, className: "bg-[var(--success-surface)] text-success" },
  warning: { Icon: TriangleAlert, className: "bg-[var(--warning-surface)] text-warning" },
}

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
  const [filter, setFilter] = useState<NotificationFilter>("all")

  useEffect(() => {
    if (open) closeRef.current?.focus()
  }, [open])

  const noticeRecords = useMemo(
    () =>
      [...(noticeContext?.notices ?? [])]
        .reverse()
        .map<NotificationRecord>((notice) => ({
          createdAt: notice.createdAt,
          id: notice.id,
          message: notice.message,
          title: notice.title,
          tone: notice.tone,
        })),
    [noticeContext?.notices],
  )
  const records = notifications ?? noticeRecords
  const successCount = records.filter((notification) => notification.tone === "success").length
  const attentionCount = records.length - successCount
  const visibleRecords = records.filter((notification) => {
    if (filter === "success") return notification.tone === "success"
    if (filter === "attention") return notification.tone !== "success"
    return true
  })
  const canManageNoticeState = notifications === undefined && noticeContext !== null

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        aria-label="Your notifications"
        className="h-dvh w-[min(100vw,32.5rem)] max-w-none translate-x-0 rounded-none border-y-0 border-r-0 border-l border-border/70 bg-card p-0 shadow-lg transition-[transform,opacity] duration-300 ease-out data-ending-style:translate-x-full data-ending-style:opacity-0 data-starting-style:translate-x-full data-starting-style:opacity-0 motion-reduce:transition-none"
        id="newsroom-notifications"
        initialFocus={() => closeRef.current}
        side="right"
      >
        <div className="flex h-full min-h-0 flex-col">
          <SheetHeader className="shrink-0 border-b border-border/60 p-4 md:p-6">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <SheetTitle>Your notifications</SheetTitle>
                <SheetDescription>Recent system activity and action results.</SheetDescription>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {canManageNoticeState ? (
                  <Button
                    aria-label="Clear all notifications"
                    className="text-muted-foreground"
                    disabled={records.length === 0}
                    onClick={() => noticeContext.clearNotices()}
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    <CheckCheck aria-hidden="true" />
                  </Button>
                ) : null}
                <button
                  autoFocus
                  aria-label="Close notifications"
                  className="grid size-11 place-items-center rounded-[7px] text-muted-foreground transition-colors hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none"
                  onClick={() => onOpenChange(false)}
                  ref={closeRef}
                  type="button"
                >
                  <X aria-hidden="true" strokeWidth={1.5} />
                </button>
              </div>
            </div>
          </SheetHeader>

          <Tabs
            className="flex min-h-0 flex-1 flex-col"
            onValueChange={(value) => setFilter(value as NotificationFilter)}
            value={filter}
          >
            <TabsList className="w-full shrink-0 px-4 md:px-6">
              <TabsTab value="all">
                View all
                <Badge data-slot="badge" variant="secondary">
                  {records.length}
                </Badge>
              </TabsTab>
              <TabsTab value="success">
                Success
                <Badge data-slot="badge" variant="secondary">
                  {successCount}
                </Badge>
              </TabsTab>
              <TabsTab value="attention">
                Attention
                <Badge data-slot="badge" variant="secondary">
                  {attentionCount}
                </Badge>
              </TabsTab>
            </TabsList>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 md:px-6">
              {loading ? (
                <LoadingState
                  aria-label="Loading notifications"
                  className="my-6 border-0 bg-transparent"
                  title="Loading notifications…"
                />
              ) : error ? (
                <ErrorState
                  className="my-6 border-0 bg-transparent"
                  description={error}
                  title="Unable to load notifications"
                />
              ) : visibleRecords.length > 0 ? (
                <ul aria-label="Notification list" className="divide-y divide-dashed divide-border">
                  {visibleRecords.map((notification) => (
                    <NotificationItem
                      dismiss={canManageNoticeState ? () => noticeContext.dismissNotice(notification.id) : undefined}
                      key={notification.id}
                      notification={notification}
                    />
                  ))}
                </ul>
              ) : (
                <EmptyState
                  className="my-6 min-h-64 border-0 bg-transparent px-4"
                  description={filter === "all" ? "New activity will appear here." : "Nothing in this view yet."}
                  icon={Bell}
                  title="No notifications yet."
                />
              )}
            </div>
          </Tabs>
        </div>
      </SheetContent>
    </Sheet>
  )
}

function NotificationItem({
  dismiss,
  notification,
}: {
  dismiss?: () => void
  notification: NotificationRecord
}) {
  const { Icon, className } = toneConfig[notification.tone]

  return (
    <li className="w-full py-4 first:pt-5 last:pb-5">
      <div className="flex gap-3">
        <div aria-hidden="true" className={cn("grid size-11 shrink-0 place-items-center rounded-full", className)}>
          <Icon className="size-5" strokeWidth={1.5} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="min-w-0 text-sm font-medium leading-5">{notification.title}</h3>
            {dismiss ? (
              <Button
                aria-label={`Dismiss ${notification.title}`}
                className="-mt-1 -me-1 text-muted-foreground"
                onClick={dismiss}
                size="icon-sm"
                type="button"
                variant="ghost"
              >
                <X aria-hidden="true" />
              </Button>
            ) : null}
          </div>
          <p className="mt-1 rounded-lg bg-muted p-2.5 text-sm tracking-[-0.006em] text-foreground" dir="auto">
            {notification.message}
          </p>
          <time
            className="mt-1.5 block text-xs text-muted-foreground"
            dateTime={new Date(notification.createdAt).toISOString()}
          >
            {formatRelativeTime(notification.createdAt)}
          </time>
        </div>
      </div>
    </li>
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

function formatRelativeTime(createdAt: number) {
  const seconds = Math.max(0, Math.floor((Date.now() - createdAt) / 1_000))
  if (seconds < 60) return "Just now"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

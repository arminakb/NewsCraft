"use client"

import React from "react"
import { Popover } from "@base-ui/react/popover"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
import { Tabs, TabsList, TabsTab } from "@/components/ui/tabs"

export type Notification = {
  id: string | number
  type: string
  user: {
    name: string
    avatar: string
    fallback: string
  }
  action: string
  target?: string
  content?: string
  title?: string
  category?: string
  timestamp: string
  timeAgo: string
  isRead: boolean
  dismissLabel?: string
  hasActions?: boolean
  file?: {
    name: string
    size: string
    type: string
  }
}

export type NotificationsMenuProps = {
  notifications?: readonly Notification[]
  loading?: boolean
  error?: string | null
  onDismiss?: (id: Notification["id"]) => void
  onClose?: () => void
  closeButtonRef?: React.Ref<HTMLButtonElement>
  closeWithPopover?: boolean
  className?: string
}

export function NotificationsMenu({
  className,
  closeButtonRef,
  error = null,
  loading = false,
  notifications = [],
  onClose,
  onDismiss,
  closeWithPopover = false,
}: NotificationsMenuProps) {
  const [activeTab, setActiveTab] = React.useState<string>("all")

  const approvalCount = notifications.filter(
    (notification) =>
      notification.type === "approval"
      || notification.type === "follow"
      || notification.type === "like",
  ).length
  const issueCount = notifications.filter((notification) => notification.type === "mention").length

  const getFilteredNotifications = () => {
    switch (activeTab) {
      case "verified":
        return notifications.filter(
          (notification) =>
            notification.type === "approval"
            || notification.type === "follow"
            || notification.type === "like",
        )
      case "mentions":
        return notifications.filter((notification) => notification.type === "mention")
      default:
        return notifications
    }
  }

  const filteredNotifications = getFilteredNotifications()

  return (
    <Card
      className={`h-full w-full min-h-0 min-w-0 max-w-none flex-col gap-3 rounded-xl border-0 bg-transparent p-3 shadow-none sm:p-4 ${className ?? ""}`}
    >
      <CardHeader className="p-0">
        <div className="flex items-center justify-between gap-2">
          <h3 className="min-w-0 text-base leading-none font-semibold tracking-[-0.006em]">Your notifications</h3>
          {onClose ? (
            closeWithPopover ? (
              <Popover.Close
                autoFocus
                aria-label="Close notifications"
                className="ms-auto grid size-8 place-items-center rounded-[6px] text-muted-foreground transition-colors hover:bg-black/5 hover:text-foreground active:bg-black/10 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 dark:hover:bg-white/5 dark:active:bg-white/10"
                onClick={onClose}
                ref={closeButtonRef}
                type="button"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="1em"
                  height="1em"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path fill="currentColor" d="M18.3 5.71a1 1 0 0 0-1.41 0L12 10.59L7.11 5.7A1 1 0 0 0 5.7 7.11L10.59 12L5.7 16.89a1 1 0 1 0 1.41 1.41L12 13.41l4.89 4.89a1 1 0 0 0 1.41-1.41L13.41 12l4.89-4.89a1 1 0 0 0 0-1.4Z" />
                </svg>
              </Popover.Close>
            ) : (
              <Button
                autoFocus
                aria-label="Close notifications"
                className="ms-auto size-8"
                onClick={onClose}
                ref={closeButtonRef}
                type="button"
                variant="ghost"
                size="icon"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="1em"
                  height="1em"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path fill="currentColor" d="M18.3 5.71a1 1 0 0 0-1.41 0L12 10.59L7.11 5.7A1 1 0 0 0 5.7 7.11L10.59 12L5.7 16.89a1 1 0 1 0 1.41 1.41L12 13.41l4.89 4.89a1 1 0 0 0 1.41-1.41L13.41 12l4.89-4.89a1 1 0 0 0 0-1.4Z" />
                </svg>
              </Button>
            )
          ) : null}
        </div>

        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="w-full flex-col justify-start"
        >
          <div className="flex items-center justify-between">
            <TabsList className="**:data-[slot=badge]:size-5 **:data-[slot=badge]:rounded-full **:data-[slot=badge]:bg-muted-foreground/30 [&_button]:gap-1 [&_button]:px-2 [&_button]:whitespace-nowrap">
              <TabsTab value="all">
                All
                <Badge variant="secondary">{notifications.length}</Badge>
              </TabsTab>
              <TabsTab value="verified">
                Approvals <Badge variant="secondary">{approvalCount}</Badge>
              </TabsTab>
              <TabsTab value="mentions">
                Issues <Badge variant="secondary">{issueCount}</Badge>
              </TabsTab>
            </TabsList>
          </div>
        </Tabs>
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        {loading ? (
          <div className="flex min-h-0 flex-1 items-center justify-center">
            <LoadingState
              aria-label="Loading notifications"
              className="w-full border-0 bg-transparent py-8"
              title="Loading notifications…"
            />
          </div>
        ) : error ? (
          <div className="flex min-h-0 flex-1 items-center justify-center">
            <ErrorState
              className="w-full border-0 bg-transparent py-8"
              description={error}
              title="Unable to load notifications"
            />
          </div>
        ) : (
          <div
            className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain"
            data-notifications-scroll
          >
            <div className="min-h-full space-y-0 divide-y divide-dashed divide-border">
              {filteredNotifications.length > 0 ? (
                filteredNotifications.map((notification) => (
                  <NotificationItem
                    dismiss={onDismiss ? () => onDismiss(notification.id) : undefined}
                    key={notification.id}
                    notification={notification}
                  />
                ))
              ) : (
                <div className="flex min-h-full items-center justify-center px-4 py-8 text-center">
                  <p className="max-w-[18rem] text-sm font-medium tracking-[-0.006em] text-muted-foreground">
                    We'll let you know when we have news for you.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function NotificationItem({
  dismiss,
  notification,
}: {
  dismiss?: () => void
  notification: Notification
}) {
  return (
    <article className="w-full py-3 first:pt-0 last:pb-0" data-notification-row>
      <div className="flex gap-2.5">
        <Avatar className={notification.title ? "size-9" : "size-11"}>
          {notification.user.avatar ? (
            <AvatarImage
              src={notification.user.avatar}
              alt={`${notification.user.name}'s profile picture`}
              className="object-cover ring-1 ring-border"
            />
          ) : null}
          <AvatarFallback>{notification.user.fallback}</AvatarFallback>
        </Avatar>

        <div className="min-w-0 flex-1 space-y-1.5">
          {notification.title ? (
            <>
              <div className="flex items-start justify-between gap-2">
                <h4 className="min-w-0 break-words text-sm leading-5 font-semibold">{notification.title}</h4>
                {!notification.isRead ? <UnreadIndicator /> : null}
              </div>
              {notification.category ? (
                <Badge className="h-5 rounded-full px-2 text-[11px]" variant="secondary">
                  {notification.category}
                </Badge>
              ) : null}
            </>
          ) : (
            <div className="w-full items-start">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 break-words text-sm">
                  <span className="font-medium">{notification.user.name}</span>
                  <span className="text-muted-foreground"> {notification.action} </span>
                  {notification.target && <span className="font-medium">{notification.target}</span>}
                </div>
                {!notification.isRead ? <UnreadIndicator /> : null}
              </div>
            </div>
          )}

          {notification.content && (
            <div className="break-words rounded-lg bg-muted p-2.5 text-sm tracking-[-0.006em]" dir="auto">
              {notification.content}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
            <time>{notification.timestamp}</time>
            {notification.timeAgo !== notification.timestamp ? <span>{notification.timeAgo}</span> : null}
          </div>

          {notification.file && (
            <div className="flex items-center gap-2 rounded-lg bg-muted p-2">
              <svg
                width="34"
                height="34"
                viewBox="0 0 40 40"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className="relative shrink-0"
                aria-hidden="true"
              >
                <path
                  d="M30 39.25H10C7.10051 39.25 4.75 36.8995 4.75 34V6C4.75 3.10051 7.10051 0.75 10 0.75H20.5147C21.9071 0.75 23.2425 1.30312 24.227 2.28769L33.7123 11.773C34.6969 12.7575 35.25 14.0929 35.25 15.4853V34C35.25 36.8995 32.8995 39.25 30 39.25Z"
                  className="fill-white stroke-border dark:fill-card/70"
                  strokeWidth="1.5"
                />
                <path
                  d="M23 1V9C23 11.2091 24.7909 13 27 13H35"
                  className="stroke-border dark:fill-muted-foreground"
                  strokeWidth="1.5"
                />
                <foreignObject x="0" y="0" width="40" height="40">
                  <div className="absolute bottom-1.5 left-0 flex h-4 items-center rounded bg-primary px-[3px] py-0.5 text-[11px] leading-none font-semibold text-white dark:bg-muted">
                    {notification.file.type}
                  </div>
                </foreignObject>
              </svg>
              <div className="flex-1">
                <div className="text-sm font-medium">{notification.file.name}</div>
                <div className="text-xs text-muted-foreground">
                  {notification.file.type} • {notification.file.size}
                </div>
              </div>
              <Button
                aria-label={`Download ${notification.file.name}`}
                variant="ghost"
                size="icon"
                type="button"
                className="size-8"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="1em"
                  height="1em"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    fill="currentColor"
                    d="M12.554 16.506a.75.75 0 0 1-1.107 0l-4-4.375a.75.75 0 0 1 1.107-1.012l2.696 2.95V3a.75.75 0 0 1 1.5 0v11.068l2.697-2.95a.75.75 0 1 1 1.107 1.013z"
                  />
                  <path
                    fill="currentColor"
                    d="M3.75 15a.75.75 0 0 0-1.5 0v.055c0 1.367 0 2.47.117 3.337c.12.9.38 1.658.981 2.26c.602.602 1.36.86 2.26.982c.867.116 1.97.116 3.337.116h6.11c1.367 0 2.47 0 3.337-.116c.9-.122 1.658-.38 2.26-.982s.86-1.36.982-2.26c.116-.867.116-1.97.116-3.337V15a.75.75 0 0 0-1.5 0c0 1.435-.002 2.436-.103 3.192c-.099.734-.28 1.122-.556 1.399c-.277.277-.665.457-1.4.556c-.755.101-1.756.103-3.191.103H9c-1.435 0-2.437-.002-3.192-.103c-.734-.099-1.122-.38-1.399-.556c-.099-.277-.457-.665-.556-1.4c-.101-.755-.103-1.756-.103-3.191"
                  />
                </svg>
              </Button>
            </div>
          )}

          {notification.hasActions && (
            <div className="flex gap-2">
              <Button variant="outline" size="sm" className="h-7 text-xs" type="button">
                Decline
              </Button>
              <Button size="sm" className="h-7 text-xs" type="button">
                Accept
              </Button>
            </div>
          )}
        </div>

        {dismiss ? (
          <Button
            aria-label={`Dismiss ${notification.dismissLabel ?? notification.user.name}`}
            className="-mt-1 self-start text-muted-foreground"
            onClick={dismiss}
            size="icon-sm"
            type="button"
            variant="ghost"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="currentColor" d="M18.3 5.71a1 1 0 0 0-1.41 0L12 10.59L7.11 5.7A1 1 0 0 0 5.7 7.11L10.59 12L5.7 16.89a1 1 0 1 0 1.41 1.41L12 13.41l4.89 4.89a1 1 0 0 0 1.41-1.41L13.41 12l4.89-4.89a1 1 0 0 0 0-1.4Z" />
            </svg>
          </Button>
        ) : null}
      </div>
    </article>
  )
}

function UnreadIndicator() {
  return (
    <span
      aria-label="Unread notification"
      className="mt-1.5 size-1.5 shrink-0 rounded-full bg-emerald-500"
      data-unread-indicator
      role="img"
    />
  )
}

export const Component = NotificationsMenu

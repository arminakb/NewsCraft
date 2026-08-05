"use client"

import React from "react"

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
  onClearAll?: () => void
  onDismiss?: (id: Notification["id"]) => void
  onClose?: () => void
  closeButtonRef?: React.Ref<HTMLButtonElement>
  className?: string
}

export function NotificationsMenu({
  className,
  closeButtonRef,
  error = null,
  loading = false,
  notifications = [],
  onClearAll,
  onClose,
  onDismiss,
}: NotificationsMenuProps) {
  const [activeTab, setActiveTab] = React.useState<string>("all")

  const verifiedCount = notifications.filter(
    (notification) => notification.type === "follow" || notification.type === "like",
  ).length
  const mentionCount = notifications.filter((notification) => notification.type === "mention").length

  const getFilteredNotifications = () => {
    switch (activeTab) {
      case "verified":
        return notifications.filter(
          (notification) => notification.type === "follow" || notification.type === "like",
        )
      case "mentions":
        return notifications.filter((notification) => notification.type === "mention")
      default:
        return notifications
    }
  }

  const filteredNotifications = getFilteredNotifications()

  return (
    <Card className={`flex w-full max-w-[520px] flex-col gap-6 p-4 shadow-none md:p-8 ${className ?? ""}`}>
      <CardHeader className="p-0">
        <div className="flex items-center justify-between">
          <h3 className="text-base leading-none font-semibold tracking-[-0.006em]">Your notifications</h3>
          <div className="flex items-center gap-2">
            <Button
              aria-label={onClearAll ? "Clear all notifications" : "Mark all notifications as read"}
              className="size-8"
              disabled={onClearAll ? notifications.length === 0 : undefined}
              onClick={onClearAll}
              type="button"
              variant="ghost"
              size="icon"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="1em"
                height="1em"
                viewBox="0 0 24 24"
                className="size-4.5 text-muted-foreground"
                aria-hidden="true"
              >
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M15.493 6.935a.75.75 0 0 1 .072 1.058l-7.857 9a.75.75 0 0 1-1.13 0l-3.143-3.6a.75.75 0 0 1 1.13-.986l2.578 2.953l7.292-8.353a.75.75 0 0 1 1.058-.072m5.025.085c.3.285.311.76.025 1.06l-8.571 9a.75.75 0 0 1-1.14-.063l-.429-.563a.75.75 0 0 1 1.076-1.032l7.978-8.377a.75.75 0 0 1 1.06-.026"
                  clipRule="evenodd"
                />
              </svg>
            </Button>
            <Button
              aria-label="Notification settings"
              className="size-8"
              type="button"
              variant="ghost"
              size="icon"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="1em"
                height="1em"
                viewBox="0 0 24 24"
                className="size-4.5 text-muted-foreground"
                aria-hidden="true"
              >
                <g fill="currentColor" fillRule="evenodd" clipRule="evenodd">
                  <path d="M12 8.25a3.75 3.75 0 1 0 0 7.5a3.75 3.75 0 0 0 0-7.5M9.75 12a2.25 2.25 0 1 1 4.5 0a2.25 2.25 0 0 1-4.5 0" />
                  <path d="M11.975 1.25c-.445 0-.816 0-1.12.02a2.8 2.8 0 0 0-.907.19a2.75 2.75 0 0 0-1.489 1.488c-.145.35-.184.72-.2 1.122a.87.87 0 0 1-.415.731a.87.87 0 0 1-.841-.005c-.356-.188-.696-.339-1.072-.389a2.75 2.75 0 0 0-2.033.545a2.8 2.8 0 0 0-.617.691c-.17.254-.356.575-.578.96l-.025.044c-.223.385-.408.706-.542.98c-.14.286-.25.568-.29.88a2.75 2.75 0 0 0 .544 2.033c.231.301.532.52.872.734a.87.87 0 0 1 .426.726a.87.87 0 0 1-.426.726c-.34.214-.64.433-.872.734a2.75 2.75 0 0 0-.545 2.033c.041.312.15.594.29.88c.135.274.32.595.543.98l.025.044c.222.385.408.706.578.96c.177.263.367.5.617.69a2.75 2.75 0 0 0 2.033.546c.376-.05.716-.2 1.072-.389a.87.87 0 0 1 .84-.005a.86.86 0 0 1 .417.731c.015.402.054.772.2 1.122a2.75 2.75 0 0 0 1.488 1.489c.29.12.59.167.907.188c.304.021.675.021 1.12.021h.05c.445 0 .816 0 1.12-.02c.318-.022.617-.069.907-.19a2.75 2.75 0 0 0 1.489-1.488c.145-.35.184-.72.2-1.122a.87.87 0 0 1 .415-.732a.87.87 0 0 1 .841.006c.356.188.696.339 1.072.388a2.75 2.75 0 0 0 2.033-.544c.25-.192.44-.428.617-.691c.17-.254.356-.575.578-.96l.025-.044c.223-.385.408-.706.542-.98c.14-.286.25-.569.29-.88a2.75 2.75 0 0 0-.544-2.033c-.231-.301-.532-.52-.872-.734a.87.87 0 0 1-.426-.726c0-.278.152-.554.426-.726c.34-.214.64-.433.872-.734a2.75 2.75 0 0 0 .545-2.033a2.8 2.8 0 0 0-.29-.88a18 18 0 0 0-.543-.98l-.025-.044a18 18 0 0 0-.578-.96a2.8 2.8 0 0 0-.617-.69a2.75 2.75 0 0 0-2.033-.546c-.376.05-.716.2-1.072.389a.87.87 0 0 1-.84.005a.87.87 0 0 1-.417-.731c-.015-.402-.054-.772-.2-1.122a2.75 2.75 0 0 0-1.488-1.489c-.29-.12-.59-.167-.907-.188c-.304-.021-.675-.021-1.12-.021zm-1.453 1.595c.077-.032.194-.061.435-.078c.247-.017.567-.017 1.043-.017s.796 0 1.043.017c.241.017.358.046.435.078c.307.127.55.37.677.677c.04.096.073.247.086.604c.03.792.439 1.555 1.165 1.974s1.591.392 2.292.022c.316-.167.463-.214.567-.227a1.25 1.25 0 0 1 .924.247c.066.051.15.138.285.338c.139.206.299.483.537.895s.397.69.506.912c.107.217.14.333.15.416a1.25 1.25 0 0 1-.247.924c-.064.083-.178.187-.48.377c-.672.422-1.128 1.158-1.128 1.996s.456 1.574 1.128 1.996c.302.19.416.294.48.377c.202.263.29.595.247.924c-.01.083-.044.2-.15.416c-.109.223-.268.5-.506.912s-.399.689-.537.895c-.135.2-.219.287-.285.338a1.25 1.25 0 0 1-.924.247c-.104-.013-.25-.06-.567-.227c-.7-.37-1.566-.398-2.292.021s-1.135 1.183-1.165 1.975c-.013.357-.046.508-.086.604a1.25 1.25 0 0 1-.677.677c-.077.032-.194.061-.435.078c-.247.017-.567.017-1.043.017s-.796 0-1.043-.017c-.241-.017-.358-.046-.435-.078a1.25 1.25 0 0 1-.677-.677c-.04-.096-.073-.247-.086-.604c-.03-.792-.439-1.555-1.165-1.974s-1.591-.392-2.292-.022c-.316.167-.463.214-.567.227a1.25 1.25 0 0 1-.924-.247c-.066-.051-.15-.138-.285-.338a17 17 0 0 1-.537-.895c-.238-.412-.397-.69-.506-.912c-.107-.217-.14-.333-.15-.416a1.25 1.25 0 0 1 .247-.924c.064-.083.178-.187.48-.377c.672-.422 1.128-1.158 1.128-1.996s-.456-1.574-1.128-1.996c-.302-.19-.416-.294-.48-.377a1.25 1.25 0 0 1-.247-.924c.01-.083.044-.2.15-.416c.109-.223.268-.5.506-.912s.399-.689.537-.895c.135-.2.219-.287.285-.338a1.25 1.25 0 0 1 .924-.247c.104.013.25.06.567.227c.7.37 1.566.398 2.292-.022c.726-.419 1.135-1.182 1.165-1.974c.013-.357.046-.508.086-.604c.127-.307.37-.55.677-.677" />
                </g>
              </svg>
            </Button>
            {onClose ? (
              <Button
                autoFocus
                aria-label="Close notifications"
                className="size-8"
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
            ) : null}
          </div>
        </div>

        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="w-full flex-col justify-start"
        >
          <div className="flex items-center justify-between">
            <TabsList className="**:data-[slot=badge]:size-5 **:data-[slot=badge]:rounded-full **:data-[slot=badge]:bg-muted-foreground/30 [&_button]:gap-1.5">
              <TabsTab value="all">
                View all
                <Badge variant="secondary">{notifications.length}</Badge>
              </TabsTab>
              <TabsTab value="verified">
                Verified <Badge variant="secondary">{verifiedCount}</Badge>
              </TabsTab>
              <TabsTab value="mentions">
                Mentions <Badge variant="secondary">{mentionCount}</Badge>
              </TabsTab>
            </TabsList>
          </div>
        </Tabs>
      </CardHeader>

      <CardContent className="h-full p-0">
        {loading ? (
          <LoadingState
            aria-label="Loading notifications"
            className="border-0 bg-transparent py-12"
            title="Loading notifications…"
          />
        ) : error ? (
          <ErrorState
            className="border-0 bg-transparent py-12"
            description={error}
            title="Unable to load notifications"
          />
        ) : (
          <div className="space-y-0 divide-y divide-dashed divide-border">
            {filteredNotifications.length > 0 ? (
              filteredNotifications.map((notification) => (
                <NotificationItem
                  dismiss={onDismiss ? () => onDismiss(notification.id) : undefined}
                  key={notification.id}
                  notification={notification}
                />
              ))
            ) : (
              <div className="flex flex-col items-center justify-center space-y-2.5 py-12 text-center">
                <div className="rounded-full bg-muted p-4">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="24"
                    height="24"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="text-muted-foreground"
                    aria-hidden="true"
                  >
                    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                    <path d="m13.73 21a2 2 0 0 1-3.46 0" />
                  </svg>
                </div>
                <p className="text-sm font-medium tracking-[-0.006em] text-muted-foreground">
                  No notifications yet.
                </p>
              </div>
            )}
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
    <div className="w-full py-4 first:pt-0 last:pb-0">
      <div className="flex gap-3">
        <Avatar className="size-11">
          {notification.user.avatar ? (
            <AvatarImage
              src={notification.user.avatar}
              alt={`${notification.user.name}'s profile picture`}
              className="object-cover ring-1 ring-border"
            />
          ) : null}
          <AvatarFallback>{notification.user.fallback}</AvatarFallback>
        </Avatar>

        <div className="flex flex-1 flex-col space-y-2">
          <div className="w-full items-start">
            <div>
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm">
                  <span className="font-medium">{notification.user.name}</span>
                  <span className="text-muted-foreground"> {notification.action} </span>
                  {notification.target && <span className="font-medium">{notification.target}</span>}
                </div>
                {!notification.isRead && <div className="size-1.5 rounded-full bg-emerald-500" />}
              </div>
              <div className="flex items-center justify-between gap-2">
                <div className="mt-0.5 text-xs text-muted-foreground">{notification.timestamp}</div>
                <div className="text-xs text-muted-foreground">{notification.timeAgo}</div>
              </div>
            </div>
          </div>

          {notification.content && (
            <div className="rounded-lg bg-muted p-2.5 text-sm tracking-[-0.006em]">
              {notification.content}
            </div>
          )}

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
            className="-mt-1 -me-1 self-start text-muted-foreground"
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
    </div>
  )
}

export const Component = NotificationsMenu

import type { Notice } from "@/components/providers/notice-provider"
import type { Notification } from "@/components/ui/notifications-menu"

/**
 * Temporary boundary for NewsCraft's current in-app notice source.
 * Replace this adapter with the notification API mapper when that backend exists.
 */
export function adaptNoticesToNotifications(
  notices: readonly Notice[],
  now = Date.now(),
): Notification[] {
  return [...notices].reverse().map((notice) => ({
    action: notice.title,
    content: notice.message,
    dismissLabel: notice.title,
    id: notice.id,
    isRead: false,
    timeAgo: formatRelativeTime(notice.createdAt, now),
    timestamp: formatTimestamp(notice.createdAt),
    type: "system",
    user: {
      avatar: "",
      fallback: "N",
      name: "NewsCraft",
    },
  }))
}

function formatTimestamp(createdAt: number) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    weekday: "long",
  }).format(createdAt)
}

function formatRelativeTime(createdAt: number, now: number) {
  const seconds = Math.max(0, Math.floor((now - createdAt) / 1_000))
  if (seconds < 60) return "Just now"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} minutes ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hours ago`
  const days = Math.floor(hours / 24)
  return `${days} days ago`
}

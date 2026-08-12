import type { Notification } from "@/components/ui/notifications-menu"

/**
 * Development-only visual fixture for the anchored notifications popup.
 */
const workflowApprovalNotification: Notification = {
  action: "",
  category: "Approvals",
  content: '“AI Daily Brief” has completed and is waiting for your approval.',
  id: "dev-workflow-approval-required",
  isRead: false,
  timeAgo: "Just now",
  timestamp: "Just now",
  title: "Workflow approval required",
  type: "approval",
  user: { avatar: "", fallback: "N", name: "NewsCraft" },
}

export function getDevelopmentNotificationFixture(): Notification[] {
  if (process.env.NODE_ENV === "production" || process.env.NODE_ENV === "test") {
    return []
  }

  const isOverflowReview =
    typeof window !== "undefined"
    && new URLSearchParams(window.location.search).get("notifications") === "overflow"

  if (!isOverflowReview) return [workflowApprovalNotification]

  return [
    workflowApprovalNotification,
    ...Array.from({ length: 8 }, (_, index): Notification => ({
      action: "",
      category: "Approvals",
      content:
        index === 0
          ? "This temporary review notification contains deliberately long text so the popup can prove that content wraps inside its bounded width instead of expanding toward the edge of the viewport."
          : `Temporary development notification ${index + 2} for scroll verification.`,
      id: `dev-overflow-notification-${index + 2}`,
      isRead: true,
      timeAgo: `${index + 2} minutes ago`,
      timestamp: `Today ${10 + index}:0${index} AM`,
      title: `Temporary approval item ${index + 2}`,
      type: "approval",
      user: { avatar: "", fallback: "N", name: "NewsCraft" },
    })),
  ]
}

import type { StatusTone } from "@/components/ui/status-badge"

const terminalStatuses = new Set(["succeeded", "warning", "failed", "cancelled"])

export function isTerminalRun(status: string) {
  return terminalStatuses.has(status)
}

export function runTone(status: string): StatusTone {
  if (status === "succeeded") return "success"
  if (["failed", "cancelled"].includes(status)) return "error"
  if (["queued", "running"].includes(status)) return "info"
  if (["warning", "waiting_for_review"].includes(status)) return "warning"
  return "neutral"
}

export function cursorTone(status: string): StatusTone {
  if (status === "ready") return "success"
  if (["failed", "error"].includes(status)) return "error"
  if (["initializing", "checking"].includes(status)) return "warning"
  return "neutral"
}

export function dispatchTone(status: string): StatusTone {
  if (["succeeded", "published", "generated"].includes(status)) return "success"
  if (["failed", "cancelled"].includes(status)) return "error"
  if (["needs_review", "ambiguous"].includes(status)) return "warning"
  if (["queued", "running", "dispatching"].includes(status)) return "info"
  return "neutral"
}

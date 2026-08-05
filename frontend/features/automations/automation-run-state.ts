const terminalStatuses = new Set(["succeeded", "warning", "failed", "cancelled"])

export function isTerminalRun(status: string) {
  return terminalStatuses.has(status)
}

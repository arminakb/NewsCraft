export type AutomationControl = {
  globalPause: boolean
  dryRun: boolean
  pauseReason: string | null
  pausedAt: string | null
  updatedAt: string
}

export type AutomationControlPatch = {
  globalPause?: boolean
  dryRun?: boolean
  pauseReason?: string | null
}

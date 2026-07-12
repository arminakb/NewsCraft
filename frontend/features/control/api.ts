import { apiRequest } from "@/lib/http"

import type { AutomationControl, AutomationControlPatch } from "./types"

type BackendAutomationControl = {
  global_pause: boolean
  dry_run: boolean
  pause_reason: string | null
  paused_at: string | null
  updated_at: string
}

export async function getAutomationControl(): Promise<AutomationControl> {
  return mapAutomationControl(await apiRequest<BackendAutomationControl>("/automation-control"))
}

export async function updateAutomationControl(input: AutomationControlPatch): Promise<AutomationControl> {
  const body: {
    global_pause?: boolean
    dry_run?: boolean
    pause_reason?: string | null
  } = {}
  if (input.globalPause !== undefined) body.global_pause = input.globalPause
  if (input.dryRun !== undefined) body.dry_run = input.dryRun
  if (input.pauseReason !== undefined || "pauseReason" in input) body.pause_reason = input.pauseReason

  const row = await apiRequest<BackendAutomationControl>("/automation-control", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  })
  return mapAutomationControl(row)
}

function mapAutomationControl(row: BackendAutomationControl): AutomationControl {
  return {
    globalPause: row.global_pause,
    dryRun: row.dry_run,
    pauseReason: row.pause_reason,
    pausedAt: row.paused_at,
    updatedAt: row.updated_at,
  }
}

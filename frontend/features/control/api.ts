import type { components } from "@/lib/api/generated"
import { camelize } from "@/lib/camelize"
import { apiRequest } from "@/lib/http"

import type { AutomationControl, AutomationControlPatch } from "./types"

type BackendAutomationControl = components["schemas"]["AutomationControlOut"]

export async function getAutomationControl(): Promise<AutomationControl> {
  return camelize(await apiRequest<BackendAutomationControl>("/automation-control"))
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

  return camelize(await apiRequest<BackendAutomationControl>("/automation-control", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }))
}

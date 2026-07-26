import type { components } from "@/lib/api/generated"
import type { Camelized } from "@/lib/camelize"

type Schemas = components["schemas"]

export type AutomationControl = Camelized<Schemas["AutomationControlOut"]>
export type AutomationControlPatch = {
  globalPause?: boolean
  dryRun?: boolean
  pauseReason?: string | null
}

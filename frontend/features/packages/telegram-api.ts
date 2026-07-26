import type { JobAccepted } from "@/features/jobs/types"
import type { components } from "@/lib/api/generated"
import { apiRequest } from "@/lib/http"

import { decodePlatformRevision } from "./api"
import type { TelegramPayload, TelegramRevision } from "./types"

export type TelegramEditRequest = {
  baseRevisionId: string
  baseContentHash: string
  content: Pick<TelegramPayload, "body" | "parseMode" | "buttons">
  mediaAssetIds: string[]
  editNote: string
}

export async function saveTelegramPlatformRevision(
  variantId: string,
  input: TelegramEditRequest,
): Promise<TelegramRevision> {
  const body: components["schemas"]["EditVariantRequest"] = {
    base_revision_id: input.baseRevisionId,
    base_content_hash: input.baseContentHash,
    content: {
      body: input.content.body,
      parse_mode: input.content.parseMode,
      buttons: input.content.buttons,
    },
    media_asset_ids: input.mediaAssetIds,
    edit_note: input.editNote,
  }
  const revision = decodePlatformRevision(
    await apiRequest<unknown>(
      `/platform-variants/${variantId}/revisions`,
      jsonRequest(body),
    ),
  )
  if (revision.variantId !== variantId || revision.platform !== "telegram") {
    throw new Error("Telegram edit response identity mismatch")
  }
  return revision
}

export async function regeneratePlatformVariant(
  variantId: string,
  input: { providerProfileId: string; instruction: string | null },
): Promise<JobAccepted> {
  const body: components["schemas"]["RegenerateVariantRequest"] = {
    generation_provider_profile_id: input.providerProfileId,
    instruction: input.instruction,
  }
  const row = await apiRequest<components["schemas"]["JobAcceptedOut"]>(
    `/platform-variants/${variantId}/regenerate`,
    jsonRequest(body),
  )
  return {
    jobId: row.job_id,
    status: row.status,
    deduplicated: row.deduplicated,
  }
}

function jsonRequest(body: object): RequestInit {
  return {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }
}

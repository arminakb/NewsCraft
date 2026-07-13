import { BlogPreview } from "@/features/packages/components/blog-preview"
import { InstagramPreview } from "@/features/packages/components/instagram-preview"
import { TelegramPreview } from "@/features/packages/components/telegram-preview"
import { XPreview } from "@/features/packages/components/x-preview"
import type { PlatformRevision } from "@/features/packages/types"

function unsupportedPlatform(value: never): never {
  const platform = (value as { platform?: unknown }).platform
  throw new Error(`Unsupported platform preview: ${String(platform)}`)
}

export function PlatformPreview({ revision }: { revision: PlatformRevision }) {
  switch (revision.platform) {
    case "telegram":
      return <TelegramPreview revision={revision} />
    case "instagram":
      return <InstagramPreview revision={revision} />
    case "x":
      return <XPreview revision={revision} />
    case "blog":
      return <BlogPreview revision={revision} />
    default:
      return unsupportedPlatform(revision)
  }
}

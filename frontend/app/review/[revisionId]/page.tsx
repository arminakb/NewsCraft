import { TelegramReviewWorkspace } from "@/features/review/telegram-review-workspace"

export default async function TelegramReviewPage({ params }: { params: Promise<{ revisionId: string }> }) {
  const { revisionId } = await params
  return <TelegramReviewWorkspace revisionId={revisionId} />
}

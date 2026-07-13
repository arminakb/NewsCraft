import { ExactRevisionReview } from "@/components/editorial/exact-revision-review"

export default async function TelegramReviewPage({ params }: { params: Promise<{ revisionId: string }> }) {
  const { revisionId } = await params
  return <ExactRevisionReview revisionId={revisionId} />
}

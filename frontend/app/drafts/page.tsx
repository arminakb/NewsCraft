import { TelegramDraftList } from "@/features/drafts/telegram-draft-list"

export default async function DraftsPage({ searchParams }: { searchParams: Promise<{ approval_state?: string }> }) {
  const params = await searchParams
  const allowed = ["draft", "pending_review", "approved", "rejected"] as const
  const approvalState = allowed.find((value) => value === params.approval_state)
  return <TelegramDraftList approvalState={approvalState} />
}

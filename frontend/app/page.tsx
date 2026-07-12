import { TodayPage } from "@/features/today/today-page"
import { TelegramOutcomes } from "@/features/today/telegram-outcomes"

export default function Page() {
  return <TodayPage outcomes={<TelegramOutcomes />} />
}

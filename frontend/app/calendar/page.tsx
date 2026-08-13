import { redirect } from "next/navigation"

export default function CalendarPage() {
  redirect("/settings?section=date-time")
}

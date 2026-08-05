import { redirect } from "next/navigation"

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const query = await searchParams
  const params = new URLSearchParams()
  params.set("view", "diagnostics")
  for (const [key, value] of Object.entries(query)) {
    if (key === "view") continue
    for (const item of Array.isArray(value) ? value : value ? [value] : []) params.append(key, item)
  }
  return redirect(`/operations?${params.toString()}`)
}

import { redirect } from "next/navigation"

type ArticlesRedirectProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}

export default async function Page({ searchParams }: ArticlesRedirectProps) {
  const values = await searchParams
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, item)
    } else if (value !== undefined) {
      params.set(key, value)
    }
  }
  const query = params.toString()
  redirect(`/feed${query ? `?${query}` : ""}`)
}

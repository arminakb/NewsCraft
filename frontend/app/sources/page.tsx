import { SourcesPage } from "@/components/dashboard/pages/sources-page"

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ source?: string | string[] }>
}) {
  const query = await searchParams
  const source = Array.isArray(query.source) ? query.source[0] : query.source
  return <SourcesPage initialSourceId={source ?? null} />
}

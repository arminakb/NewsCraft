import { JobsPage } from "@/features/jobs/jobs-page"

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ status?: string | string[]; job?: string | string[] }>
}) {
  const query = await searchParams
  return (
    <JobsPage
      initialStatus={first(query.status)}
      initialJobId={first(query.job)}
    />
  )
}

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] ?? null : value ?? null
}

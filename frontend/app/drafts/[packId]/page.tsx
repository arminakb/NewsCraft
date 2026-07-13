import { ContentPackWorkspace } from "@/components/editorial/content-pack-workspace"

export default async function ContentPackPage({ params }: { params: Promise<{ packId: string }> }) {
  const { packId } = await params
  return <ContentPackWorkspace packId={packId} />
}

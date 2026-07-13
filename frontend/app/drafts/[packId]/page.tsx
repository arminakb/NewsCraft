import { ContentPackWorkspace } from "@/components/editorial/content-pack-workspace"

export default async function MultiPlatformContentPackPage({ params }: { params: Promise<{ packId: string }> }) {
  const { packId } = await params
  return <ContentPackWorkspace packId={packId} />
}

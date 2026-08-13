/**
 * Client mirror of the backend's article-collection name rule. It lives in one
 * place because the three creation/rename dialogs must reject exactly what the
 * API rejects — drift here turns a server 422 into an unexplained failure.
 */
export const MAX_COLLECTION_NAME_LENGTH = 60

export function validateCollectionName(raw: string): string | null {
  const trimmed = raw.trim()
  if (trimmed.length === 0) return "Enter a collection name."
  if (trimmed.length > MAX_COLLECTION_NAME_LENGTH) {
    return `Collection name must be ${MAX_COLLECTION_NAME_LENGTH} characters or fewer.`
  }
  return null
}

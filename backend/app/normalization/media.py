from urllib.parse import urlsplit

IMAGE_EXTENSIONS = (".apng", ".avif", ".gif", ".jpg", ".jpeg", ".png", ".webp")
VIDEO_EXTENSIONS = (".m4v", ".mov", ".mp4", ".webm")
AUDIO_EXTENSIONS = (".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav")
DOCUMENT_EXTENSIONS = (".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx")


def is_http_media_url(url: str) -> bool:
    scheme = urlsplit(url).scheme.lower()
    return scheme in {"http", "https"}


def infer_media_kind(url: str, mime_type: str | None = None, medium: str | None = None) -> str:
    normalized_medium = (medium or "").lower()
    normalized_mime = (mime_type or "").lower()
    path = urlsplit(url).path.lower()

    if normalized_medium == "image" or normalized_mime.startswith("image/") or path.endswith(IMAGE_EXTENSIONS):
        return "image"
    if normalized_medium == "video" or normalized_mime.startswith("video/") or path.endswith(VIDEO_EXTENSIONS):
        return "video"
    if normalized_medium == "audio" or normalized_mime.startswith("audio/") or path.endswith(AUDIO_EXTENSIONS):
        return "audio"
    if normalized_mime in {"application/pdf"} or path.endswith(DOCUMENT_EXTENSIONS):
        return "document"
    return "document"


def parse_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None

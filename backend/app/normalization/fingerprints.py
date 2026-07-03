from app.normalization.text import fingerprint_text
from app.normalization.urls import hash_value


def content_hash(value: str) -> str:
    return hash_value(fingerprint_text(value))


def title_date_fingerprint(title: str, date_key: str) -> str:
    return hash_value(fingerprint_text(f"{title} {date_key}"))

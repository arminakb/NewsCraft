from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "cmpid", "ref"}


def normalize_url(url: str, base_url: str | None = None) -> str:
    absolute = urljoin(base_url, url.strip()) if base_url else url.strip()
    parts = urlsplit(absolute)
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in TRACKING_PARAMS or any(lowered.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items))
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((scheme, host, path, query, ""))


def hash_value(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()

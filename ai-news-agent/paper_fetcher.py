"""arXiv PDF fetching helpers."""

import os
import re
from urllib.parse import quote, urlparse

import requests


ARXIV_ID_RE = re.compile(r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z-]+(\.[A-Z]{2})?/\d{7}(v\d+)?)$")


def extract_arxiv_id(url_or_id):
    value = str(url_or_id or "").strip()
    if not value:
        raise ValueError("Missing arXiv ID")

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        if "arxiv.org" not in parsed.netloc:
            raise ValueError("Invalid arXiv URL")
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2 or parts[0] not in {"abs", "pdf"}:
            raise ValueError("Missing arXiv ID")
        value = "/".join(parts[1:])

    value = value.strip().removesuffix(".pdf")
    if not ARXIV_ID_RE.match(value):
        raise ValueError(f"Invalid arXiv ID: {value}")
    return value


def build_arxiv_pdf_url(arxiv_id):
    return f"https://arxiv.org/pdf/{quote(extract_arxiv_id(arxiv_id), safe='/')}"


def _safe_filename(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def download_arxiv_pdf(arxiv_id, output_dir="data/papers", force=False):
    arxiv_id = extract_arxiv_id(arxiv_id)
    paper_dir = os.path.join(output_dir, _safe_filename(arxiv_id))
    pdf_path = os.path.join(paper_dir, "paper.pdf")
    if os.path.exists(pdf_path) and not force:
        return pdf_path

    try:
        os.makedirs(paper_dir, exist_ok=True)
        response = requests.get(build_arxiv_pdf_url(arxiv_id), timeout=30)
        response.raise_for_status()
        if not response.content:
            raise ValueError("Empty PDF response")
        with open(pdf_path, "wb") as handle:
            handle.write(response.content)
        return pdf_path
    except Exception as exc:
        raise RuntimeError(f"PDF download failed for {arxiv_id}: {exc}") from exc

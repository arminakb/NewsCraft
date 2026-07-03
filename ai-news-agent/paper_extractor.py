"""PDF text extraction and simple paper section detection."""

import re
from collections import Counter


SECTION_NAMES = [
    "Abstract",
    "Introduction",
    "Related Work",
    "Method",
    "Methods",
    "Experiments",
    "Results",
    "Limitations",
    "Conclusion",
]


def extract_text_from_pdf(pdf_path):
    try:
        import fitz

        with fitz.open(pdf_path) as document:
            text = "\n".join(page.get_text("text") for page in document)
    except Exception as exc:
        raise RuntimeError(f"PDF extraction failed for {pdf_path}: {exc}") from exc

    if not text.strip():
        raise ValueError("Empty extracted text")
    return text


def clean_paper_text(text):
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    repeated = {line for line, count in Counter(lines).items() if count > 2 and len(line) < 120}
    useful = [line for line in lines if line not in repeated and not re.fullmatch(r"\d+", line)]
    cleaned = "\n".join(useful)
    cleaned = re.split(r"(?im)^\s*(references|bibliography)\s*$", cleaned, maxsplit=1)[0]
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_basic_sections(clean_text):
    text = str(clean_text or "")
    matches = []
    for name in SECTION_NAMES:
        pattern = re.compile(rf"(?im)^\s*(\d+(\.\d+)?\s+)?{re.escape(name)}\s*$")
        for match in pattern.finditer(text):
            canonical = "Method" if name == "Methods" else name
            matches.append((match.start(), match.end(), canonical))
    matches.sort()

    sections = {}
    for index, (start, end, name) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        body = text[end:next_start].strip()
        if body and name not in sections:
            sections[name] = body
    return sections

import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from fastapi import HTTPException

from newscraft.core.config import settings
from newscraft.repositories.article_repository import ArticleRepository
from newscraft.repositories.paper_asset_repository import PaperAssetRepository

ARXIV_ID_RE = re.compile(r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z-]+(\.[A-Z]{2})?/\d{7}(v\d+)?)$")
SECTION_NAMES = ["Abstract", "Introduction", "Related Work", "Method", "Methods", "Experiments", "Results", "Limitations", "Conclusion"]
REVIEW_NOTE = "This brief was generated using rule-based extraction and should be reviewed before publishing."


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

    value = value.removesuffix(".pdf")
    if not ARXIV_ID_RE.match(value):
        raise ValueError(f"Invalid arXiv ID: {value}")
    return value


def build_arxiv_pdf_url(arxiv_id):
    return f"https://arxiv.org/pdf/{quote(extract_arxiv_id(arxiv_id), safe='/')}"


def _safe_filename(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def download_arxiv_pdf(arxiv_id, output_dir="data/papers", force=False):
    arxiv_id = extract_arxiv_id(arxiv_id)
    paper_dir = Path(output_dir) / _safe_filename(arxiv_id)
    pdf_path = paper_dir / "paper.pdf"
    if pdf_path.exists() and not force:
        return str(pdf_path)

    paper_dir.mkdir(parents=True, exist_ok=True)
    response = requests.get(build_arxiv_pdf_url(arxiv_id), timeout=30)
    response.raise_for_status()
    if not response.content:
        raise ValueError("Empty PDF response")
    pdf_path.write_bytes(response.content)
    return str(pdf_path)


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
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def extract_basic_sections(clean_text):
    text = str(clean_text or "")
    matches = []
    for name in SECTION_NAMES:
        pattern = re.compile(rf"(?im)^\s*(\d+(\.\d+)?\s+)?{re.escape(name)}\s*$")
        for match in pattern.finditer(text):
            matches.append((match.start(), match.end(), "Method" if name == "Methods" else name))
    matches.sort()

    sections = {}
    for index, (_start, end, name) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        body = text[end:next_start].strip()
        if body and name not in sections:
            sections[name] = body
    return sections


def _sentences(text, limit=3):
    chunks = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", str(text or "")).strip())
    return [chunk.strip() for chunk in chunks if len(chunk.strip()) > 20][:limit]


def _section(sections, *names):
    for name in names:
        if sections.get(name):
            return sections[name]
    return ""


def _authors(article):
    return article.get("authors") or (article.get("metrics") or {}).get("authors") or []


def generate_research_brief(article, full_text, sections=None):
    sections = sections or {}
    title = article.get("title", "Untitled paper")
    abstract = article.get("summary") or _section(sections, "Abstract")
    intro = _section(sections, "Introduction")
    method = _section(sections, "Method")
    results = _section(sections, "Results", "Experiments")
    conclusion = _section(sections, "Conclusion")
    limitations = _section(sections, "Limitations")
    summary_source = abstract or intro or full_text

    return {
        "one_line_summary": f"{title}: {(_sentences(summary_source, 1) or ['review needed'])[0]}",
        "main_problem": (_sentences(intro or abstract, 1) or ["The main problem was not clearly detected."])[0],
        "core_idea": (_sentences(method, 1) or _sentences(intro, 1) or ["Review the method section for the core idea."])[0],
        "why_it_matters": (_sentences(conclusion or intro or abstract, 1) or ["The impact should be reviewed manually."])[0],
        "method": (_sentences(method, 2) or ["Method details were not clearly detected."])[0],
        "key_findings": _sentences(results or conclusion or summary_source, 3) or ["Review the extracted paper text for detailed findings."],
        "limitations": _sentences(limitations, 2) or ["Limitations were not clearly detected by the rule-based extractor."],
        "content_angles": [
            f"What {title} changes for AI builders",
            "The paper's main idea explained simply",
            "What to verify before using this research",
        ],
        "instagram_hook": f"New arXiv paper: {title}",
        "podcast_brief": f"Discuss what problem {title} tackles, how the method works, and what the results mean.",
        "notebooklm_source_note": "For NotebookLM, upload: 1. paper.pdf 2. research_brief.md",
        "review_note": REVIEW_NOTE,
    }


def _bullets(items):
    return "\n".join(f"- {item}" for item in items)


def write_markdown_assets(article, brief, output_dir, pdf_path):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    authors = ", ".join(_authors(article)) or "Unknown"
    title = article.get("title", "Untitled paper")
    arxiv_link = article.get("url", "")
    paths = {
        "research_brief_path": output_dir / "research_brief.md",
        "instagram_brief_path": output_dir / "instagram_brief.md",
        "podcast_brief_path": output_dir / "podcast_brief.md",
    }
    paths["research_brief_path"].write_text(
        f"""# {title}

**Authors:** {authors}
**arXiv link:** {arxiv_link}
**PDF path:** {pdf_path}

## One-line summary
{brief['one_line_summary']}

## Main problem
{brief['main_problem']}

## Core idea
{brief['core_idea']}

## Why it matters
{brief['why_it_matters']}

## Method
{brief['method']}

## Key findings
{_bullets(brief['key_findings'])}

## Limitations
{_bullets(brief['limitations'])}

## Content angles
{_bullets(brief['content_angles'])}

## Source notes
{brief['notebooklm_source_note']}

{brief['review_note']}
""",
        encoding="utf-8",
    )
    paths["instagram_brief_path"].write_text(
        f"""# Instagram Brief: {title}

## Instagram post idea
Explain the paper's practical takeaway for AI builders.

## Hook
{brief['instagram_hook']}

## Carousel outline
1. The problem
2. Why current approaches fall short
3. The core idea
4. How the method works
5. Key finding
6. Limitation to watch
7. What to try next

## Caption draft
{brief['one_line_summary']}

{brief['review_note']}

## Suggested hashtags
#AI #MachineLearning #arXiv #Research #TechNews

## Source attribution
{title} - {arxiv_link}
""",
        encoding="utf-8",
    )
    paths["podcast_brief_path"].write_text(
        f"""# Podcast Brief: {title}

## Podcast episode angle
{brief['podcast_brief']}

## Opening hook
{brief['instagram_hook']}

## Talking points
{_bullets(brief['key_findings'])}

## Questions to explore
- What problem does this paper solve?
- What would make the results more convincing?
- Who should care about this work?

## Simple explanation for general audience
{brief['core_idea']}

## Source attribution
{title} - {arxiv_link}

{brief['review_note']}
""",
        encoding="utf-8",
    )
    return {key: str(path) for key, path in paths.items()}


class AssetService:
    def __init__(self, db, article_repo=None, asset_repo=None):
        self.article_repo = article_repo or ArticleRepository(db)
        self.asset_repo = asset_repo or PaperAssetRepository(db)

    def get_assets(self, article_id: int):
        return self.asset_repo.get_for_article(article_id)

    def prepare_arxiv_assets(self, article_id: int, output_dir: str | None = None):
        article = self.article_repo.get(article_id)
        if not article:
            raise HTTPException(status_code=404, detail="article not found")
        if article.source_type != "arxiv":
            raise HTTPException(status_code=400, detail="article is not an arXiv item")

        arxiv_id = None
        try:
            arxiv_id = extract_arxiv_id(article.url)
            pdf_path = download_arxiv_pdf(arxiv_id, output_dir=output_dir or settings.paper_data_dir)
            full_text = clean_paper_text(extract_text_from_pdf(pdf_path))
            if not full_text:
                raise ValueError("Empty extracted text")

            paper_dir = Path(pdf_path).parent
            text_path = paper_dir / "full_text.txt"
            text_path.write_text(full_text, encoding="utf-8")
            sections = extract_basic_sections(full_text)
            payload = self._article_payload(article)
            paths = write_markdown_assets(payload, generate_research_brief(payload, full_text, sections), paper_dir, pdf_path)
            created_files = [pdf_path, str(text_path), paths["research_brief_path"], paths["instagram_brief_path"], paths["podcast_brief_path"]]
            return self.asset_repo.upsert(
                {
                    "article_id": article.id,
                    "pdf_path": pdf_path,
                    "text_path": str(text_path),
                    "notebooklm_brief_path": paths["research_brief_path"],
                    "instagram_brief_path": paths["instagram_brief_path"],
                    "podcast_brief_path": paths["podcast_brief_path"],
                    "metadata": {
                        "status": "ready",
                        "article_id": article.id,
                        "arxiv_id": arxiv_id,
                        "pdf_url": build_arxiv_pdf_url(arxiv_id),
                        "sections": sections,
                        "created_files": created_files,
                    },
                }
            )
        except Exception as exc:
            return self.asset_repo.upsert(
                {
                    "article_id": article.id,
                    "metadata": {
                        "status": "failed",
                        "article_id": article.id,
                        "arxiv_id": arxiv_id,
                        "error": str(exc),
                    },
                }
            )

    def _article_payload(self, article):
        metadata = article.article_metadata or {}
        authors = metadata.get("authors") or (metadata.get("metrics") or {}).get("authors") or []
        return {
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "summary": article.summary,
            "authors": authors,
            "metrics": {"authors": authors},
        }

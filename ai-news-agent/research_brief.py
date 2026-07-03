"""Rule-based research/content brief generation."""

import os
import re


REVIEW_NOTE = "This brief was generated using rule-based extraction and should be reviewed before publishing."


def _sentences(text, limit=3):
    chunks = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", str(text or "")).strip())
    return [chunk.strip() for chunk in chunks if len(chunk.strip()) > 20][:limit]


def _section(sections, *names):
    sections = sections or {}
    for name in names:
        if sections.get(name):
            return sections[name]
    return ""


def _authors(article):
    return (article.get("metrics") or {}).get("authors") or article.get("authors") or []


def generate_research_brief(article, full_text, sections=None):
    title = article.get("title", "Untitled paper")
    abstract = article.get("summary") or _section(sections, "Abstract")
    intro = _section(sections, "Introduction")
    method = _section(sections, "Method")
    results = _section(sections, "Results", "Experiments")
    conclusion = _section(sections, "Conclusion")
    limitations = _section(sections, "Limitations")

    summary_source = abstract or intro or full_text
    findings = _sentences(results or conclusion or summary_source, 3) or ["Review the extracted paper text for detailed findings."]
    limits = _sentences(limitations, 2) or ["Limitations were not clearly detected by the rule-based extractor."]
    core = (_sentences(method, 1) or _sentences(intro, 1) or ["Review the method section for the core idea."])[0]

    return {
        "one_line_summary": f"{title}: {(_sentences(summary_source, 1) or ['review needed'])[0]}",
        "main_problem": (_sentences(intro or abstract, 1) or ["The main problem was not clearly detected."])[0],
        "core_idea": core,
        "why_it_matters": (_sentences(conclusion or intro or abstract, 1) or ["The impact should be reviewed manually."])[0],
        "method": (_sentences(method, 2) or ["Method details were not clearly detected."])[0],
        "key_findings": findings,
        "limitations": limits,
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
    os.makedirs(output_dir, exist_ok=True)
    authors = ", ".join(_authors(article)) or "Unknown"
    title = article.get("title", "Untitled paper")
    arxiv_link = article.get("url", "")

    research = f"""# {title}

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
"""

    instagram = f"""# Instagram Brief: {title}

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
"""

    podcast = f"""# Podcast Brief: {title}

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
"""

    paths = {
        "research_brief_path": os.path.join(output_dir, "research_brief.md"),
        "instagram_brief_path": os.path.join(output_dir, "instagram_brief.md"),
        "podcast_brief_path": os.path.join(output_dir, "podcast_brief.md"),
    }
    for key, content in (
        ("research_brief_path", research),
        ("instagram_brief_path", instagram),
        ("podcast_brief_path", podcast),
    ):
        with open(paths[key], "w", encoding="utf-8") as handle:
            handle.write(content)
    return paths

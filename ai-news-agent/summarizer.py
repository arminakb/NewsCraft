"""Rule-based summaries for source cards."""

from utils import normalize_date_for_storage

USEFUL_TAGS = {
    "text-generation",
    "text-to-image",
    "text-to-video",
    "automatic-speech-recognition",
    "speech",
    "multimodal",
    "agent",
    "agents",
    "rag",
    "reasoning",
    "coding",
    "vision",
    "robotics",
    "embedding",
    "embeddings",
    "reranker",
    "audio",
    "computer-vision",
    "image-to-text",
    "conversational",
    "chat",
    "llm",
    "machine-learning",
    "generative-ai",
    "artificial-intelligence",
}
NOISY_TAGS = {
    "safetensors",
    "transformers",
    "pytorch",
    "tensorflow",
    "endpoints_compatible",
    "eval-results",
    "onnx",
}
NOISY_PREFIXES = ("license:", "arxiv:", "region:", "base_model:", "dataset:")


def truncate_text(text, max_chars):
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def filter_useful_tags(tags, source_type):
    useful = []
    for tag in tags or []:
        tag = str(tag).strip().lower()
        if not tag or tag in useful or tag in NOISY_TAGS or tag.startswith(NOISY_PREFIXES):
            continue
        if len(tag) <= 2:
            continue
        if source_type == "huggingface" and (tag in USEFUL_TAGS or any(word in tag for word in ("agent", "rag", "vision", "audio", "speech", "coding"))):
            useful.append(tag)
        elif source_type == "github" and (tag in USEFUL_TAGS or any(word in tag for word in ("agent", "rag", "llm", "ai"))):
            useful.append(tag)
        if len(useful) >= 5:
            break
    return useful


def _number(value):
    return f"{int(value or 0):,}"


def _use_cases(tags, default):
    tags = set(tags or [])
    cases = []
    if tags & {"text-generation", "conversational", "chat", "llm"}:
        cases.extend(["Chatbot experiments", "Text generation"])
    if tags & {"agent", "agents"}:
        cases.append("Agentic workflows")
    if "rag" in tags:
        cases.append("RAG applications")
    if tags & {"text-to-image", "vision", "computer-vision", "image-to-text"}:
        cases.append("Vision or image workflows")
    if tags & {"audio", "speech", "automatic-speech-recognition"}:
        cases.append("Speech or audio workflows")
    return (cases or default)[:3]


def build_huggingface_structured_summary(model_data):
    tags = filter_useful_tags(model_data.get("tags", []), "huggingface")
    task = model_data.get("pipeline_tag") or (tags[0] if tags else "AI model")
    likes = int(model_data.get("likes") or 0)
    downloads = int(model_data.get("downloads") or 0)
    what = model_data.get("description") or f"A {task} model hosted on Hugging Face."
    signals = []
    if likes:
        signals.append(f"{_number(likes)} likes")
    if downloads:
        signals.append(f"{_number(downloads)} downloads")
    if model_data.get("last_modified"):
        signals.append("Recently modified")
    if task:
        signals.append(f"Task: {task}")
    if tags:
        signals.append("Tags: " + ", ".join(tags[:3]))
    return {
        "what_it_is": truncate_text(what, 180),
        "why_it_matters": truncate_text(
            "It has useful community or freshness signals, making it worth checking for AI experiments.",
            220,
        ),
        "best_use_cases": _use_cases(tags + [task], ["Model evaluation", "AI prototyping"]),
        "key_signals": signals[:4],
        "visible_tags": tags[:5],
    }


def build_github_structured_summary(repo_data):
    topics = filter_useful_tags(repo_data.get("topics", []), "github")
    stars = int(repo_data.get("stars") or 0)
    forks = int(repo_data.get("forks") or 0)
    language = repo_data.get("language") or ""
    description = repo_data.get("description") or repo_data.get("readme_snippet") or "An AI-related repository worth reviewing."
    signals = []
    if stars:
        signals.append(f"{_number(stars)} stars")
    if forks:
        signals.append(f"{_number(forks)} forks")
    if repo_data.get("published_at"):
        signals.append("Recently pushed")
    if topics:
        signals.append("Topics: " + ", ".join(topics[:3]))
    if language:
        signals.append(language)
    return {
        "what_it_is": truncate_text(description, 180),
        "why_it_matters": truncate_text(
            "It has GitHub traction, relevant AI topics, or recent activity, suggesting active developer interest.",
            220,
        ),
        "best_use_cases": _use_cases(topics, ["AI development", "Developer tooling", "Automation prototypes"]),
        "key_signals": signals[:4],
        "visible_tags": topics[:5],
        "last_modified": normalize_date_for_storage(repo_data.get("published_at")),
    }

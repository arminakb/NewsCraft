"""Keyword ranking and classification."""

AI_KEYWORDS = [
    "ai",
    "artificial intelligence",
    "openai",
    "anthropic",
    "google deepmind",
    "llm",
    "large language model",
    "chatgpt",
    "claude",
    "gemini",
    "machine learning",
    "deep learning",
    "neural",
    "agent",
    "agents",
    "automation",
    "robotics",
    "computer vision",
    "generative ai",
    "multimodal",
    "model",
]

TECH_KEYWORDS = [
    "startup",
    "github",
    "developer",
    "software",
    "api",
    "cloud",
    "cybersecurity",
    "security",
    "chip",
    "nvidia",
    "apple",
    "meta",
    "microsoft",
    "google",
    "database",
    "framework",
    "open source",
]


def _keyword_score(text, keywords):
    return sum(text.count(keyword) for keyword in keywords)


def classify_and_score(article):
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    ai_score = _keyword_score(text, AI_KEYWORDS)
    tech_score = _keyword_score(text, TECH_KEYWORDS)
    metrics = article.get("metrics") or {}
    source_type = article.get("source_type", "rss")

    if source_type == "huggingface":
        article["category"] = "Model"
        article["score"] = max(1, int(metrics.get("likes", 0) or 0) + int(metrics.get("downloads", 0) or 0) // 100 + ai_score * 3)
        return article
    if source_type == "github":
        article["category"] = "Tool"
        article["score"] = max(1, int(metrics.get("stars", 0) or 0) + int(metrics.get("forks", 0) or 0) * 2 + ai_score * 3 + tech_score)
        return article
    if source_type == "youtube":
        article["category"] = "Video"
        article["score"] = ai_score * 3 + tech_score
        return article

    article["score"] = ai_score + tech_score
    if ai_score > tech_score:
        article["category"] = "AI"
    elif tech_score:
        article["category"] = "Tech"
    else:
        article["category"] = "General"
    return article

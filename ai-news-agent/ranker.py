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

    article["score"] = ai_score + tech_score
    if ai_score > tech_score:
        article["category"] = "AI"
    elif tech_score:
        article["category"] = "Tech"
    else:
        article["category"] = "General"
    return article

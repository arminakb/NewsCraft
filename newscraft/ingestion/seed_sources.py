from urllib.parse import urlsplit


def _homepage(feed_url: str) -> str:
    parts = urlsplit(feed_url)
    return f"{parts.scheme}://{parts.netloc}/"


def _source(name: str, source_group: str, language: str, feed_url: str, media_strategy: str, homepage_url: str | None = None) -> dict:
    return {
        "name": name,
        "source_type": "rss",
        "connector": "rss_public",
        "url": feed_url,
        "language": language,
        "category": source_group,
        "enabled": True,
        "config": {
            "homepage_url": homepage_url or _homepage(feed_url),
            "default_timezone": "UTC",
            "media_strategy": media_strategy,
            "source_group": source_group,
        },
    }


SEED_SOURCES = [
    _source("OpenAI News", "ai", "en", "https://openai.com/news/rss.xml", "rss_first_og_fallback", "https://openai.com/news/"),
    _source("Google AI Blog", "ai", "en", "https://blog.google/technology/ai/rss/", "media_tags"),
    _source("Hugging Face Blog", "ai", "en", "https://huggingface.co/blog/feed.xml", "og_fallback"),
    _source("MIT Technology Review AI", "ai", "en", "https://www.technologyreview.com/topic/artificial-intelligence/feed/", "og_fallback"),
    _source("VentureBeat AI", "ai", "en", "https://venturebeat.com/category/ai/feed/", "media_tags"),
    _source("The Verge AI", "ai", "en", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "og_fallback"),
    _source("TechCrunch AI", "ai", "en", "https://techcrunch.com/category/artificial-intelligence/feed/", "og_fallback"),
    _source("The Gradient", "ai", "en", "https://thegradient.pub/rss/", "media_tags"),
    _source("BAIR Blog", "ai", "en", "https://bair.berkeley.edu/blog/feed.xml", "media_tags"),
    _source("Google Research Blog", "ai", "en", "https://research.google/blog/rss/", "media_tags"),
    _source("AWS Machine Learning Blog", "ai", "en", "https://aws.amazon.com/blogs/machine-learning/feed/", "media_tags"),
    _source("NVIDIA Blog", "ai", "en", "https://blogs.nvidia.com/feed/", "media_tags"),
    _source("Microsoft Research Blog", "ai", "en", "https://www.microsoft.com/en-us/research/feed/", "media_tags"),
    _source("IEEE Spectrum AI", "ai", "en", "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", "media_tags"),
    _source("The Decoder", "ai", "en", "https://the-decoder.com/feed/", "media_tags"),
    _source("TechCrunch", "tech", "en", "https://techcrunch.com/feed/", "og_fallback"),
    _source("The Verge", "tech", "en", "https://www.theverge.com/rss/index.xml", "og_fallback"),
    _source("Ars Technica", "tech", "en", "https://feeds.arstechnica.com/arstechnica/index", "media_tags"),
    _source("WIRED", "tech", "en", "https://www.wired.com/feed/rss", "media_tags"),
    _source("Engadget", "tech", "en", "https://www.engadget.com/rss.xml", "media_tags"),
    _source("ZDNET", "tech", "en", "https://www.zdnet.com/news/rss.xml", "og_fallback"),
    _source("InfoQ", "tech", "en", "https://feed.infoq.com/", "media_tags"),
    _source("Hacker News", "tech", "en", "https://news.ycombinator.com/rss", "no_media_expected"),
    _source("Y Combinator Blog", "tech", "en", "https://www.ycombinator.com/blog/rss", "media_tags"),
    _source("GitHub Blog", "tech", "en", "https://github.blog/feed/", "media_tags"),
    _source("Stack Overflow Blog", "tech", "en", "https://stackoverflow.blog/feed/", "og_fallback"),
    _source("Cloudflare Blog", "tech", "en", "https://blog.cloudflare.com/rss/", "media_tags"),
    _source("Federal Reserve Press", "economy", "en", "https://www.federalreserve.gov/feeds/press_all.xml", "no_media_expected"),
    _source("US Treasury", "economy", "en", "https://home.treasury.gov/rss.xml", "no_media_expected"),
    _source("SEC Press Releases", "economy", "en", "https://www.sec.gov/news/pressreleases.rss", "no_media_expected"),
    _source("BEA", "economy", "en", "https://apps.bea.gov/rss/rss.xml", "no_media_expected"),
    _source("ECB Latest Releases", "economy", "en", "https://www.ecb.europa.eu/rss/press.html", "no_media_expected"),
    _source("Bank of England News", "economy", "en", "https://www.bankofengland.co.uk/rss/news", "no_media_expected"),
    _source("BIS Press Releases", "economy", "en", "https://www.bis.org/doclist/all_pressrels.rss", "no_media_expected"),
    _source("FRED Blog", "economy", "en", "https://fredblog.stlouisfed.org/feed/", "inline_chart_images"),
    _source("NY Fed Liberty Street Economics", "economy", "en", "https://libertystreeteconomics.newyorkfed.org/feed/", "inline_chart_images"),
    _source("FT Markets", "economy", "en", "https://www.ft.com/markets?format=rss", "og_fallback"),
    _source("CNBC Economy", "economy", "en", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "og_fallback"),
    _source("MarketWatch Top Stories", "economy", "en", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "media_tags"),
    _source("Yahoo Finance", "economy", "en", "https://finance.yahoo.com/news/rss", "media_tags"),
    _source("Investing.com News", "economy", "en", "https://www.investing.com/rss/news.rss", "image_enclosures"),
    _source("IRNA", "farsi_news", "fa", "https://www.irna.ir/rss", "media_tags"),
    _source("ISNA", "farsi_news", "fa", "https://www.isna.ir/rss", "media_tags"),
    _source("Mehr News", "farsi_news", "fa", "https://www.mehrnews.com/rss", "media_tags"),
    _source("Tasnim", "farsi_news", "fa", "https://tasnimnews.ir/fa/rss/feed/0/8/0/%D9%85%D9%87%D9%85%D8%AA%D8%B1%DB%8C%D9%86-%D8%A7%D8%AE%D8%A8%D8%A7%D8%B1-%D8%AA%D8%B3%D9%86%DB%8C%D9%85", "media_tags"),
    _source("KhabarOnline", "farsi_news", "fa", "https://www.khabaronline.ir/rss", "media_tags"),
    _source("Hamshahri Online", "farsi_news", "fa", "https://www.hamshahrionline.ir/rss", "media_tags"),
    _source("Mashregh News", "farsi_news", "fa", "https://www.mashreghnews.ir/rss", "media_tags"),
    _source("Donya-e-Eqtesad", "farsi_economy", "fa", "https://donya-e-eqtesad.com/rss", "media_tags"),
    _source("Zoomit", "farsi_tech", "fa", "https://www.zoomit.ir/feed/", "media_tags"),
]

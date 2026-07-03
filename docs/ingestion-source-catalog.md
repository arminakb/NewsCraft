# Ingestion Source Catalog

validated date: 2026-07-03
validation method: curl/feed parsing with local SOCKS proxy when needed
50 active seed feeds

## Active Seed Feeds

The backend seed catalog contains 50 active RSS sources across AI, tech, economy, Farsi news, Farsi economy, and Farsi tech groups. Each source includes a media strategy in `normalization_profile.media_strategy` so parsers can prefer feed media, inline images, or OG fallback behavior.

## Secondary Candidate Feeds

- Digiato: `https://digiato.com/feed`
- Peivast: `https://peivast.com/feed`
- Way2Pay: `https://way2pay.ir/feed/`
- IRIB News: `https://www.iribnews.ir/fa/rss/allnews`
- Asr Iran: `https://www.asriran.com/fa/rss/allnews`
- Tabnak: `https://www.tabnak.ir/fa/rss/allnews`
- Krebs on Security: `https://krebsonsecurity.com/feed/`
- Dark Reading: `https://www.darkreading.com/rss.xml`
- The Register: `https://www.theregister.com/headlines.atom`
- Tom's Hardware: `https://www.tomshardware.com/feeds/all`

## Excluded Feeds And Reason

- Reuters legacy RSS: unresolved or stale in checks.
- WSJ section feeds: stale January 2025 items in checks.
- Old Microsoft AI blog feed: Cloudflare or blocking in checks.
- Old NVIDIA AI category feed: failed in checks; use `https://blogs.nvidia.com/feed/` instead.
- BLS/Census: valuable but blocked from current host; add when fetch policy is confirmed.

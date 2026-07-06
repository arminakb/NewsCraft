# Requested Source Proxy Validation

Date: 2026-07-06

## Summary

The first validation pass against the requested Telegram and RSS sources failed because Docker containers could not reach the host proxy. The sources themselves were not all bad: after fetching through the working host proxy and replaying the captured responses through the normal ingestion pipeline, 10 of 13 requested sources fetched successfully and produced usable content.

## Benchmark

| Run | Checked | Fetched | Failed | Items | Media candidates |
|---|---:|---:|---:|---:|---:|
| Docker without reachable proxy | 13 | 0 | 13 | 0 | 0 |
| Host proxy capture plus ingestion replay | 13 | 10 | 3 | 220 | 426 |

Current database totals after replay:

| Metric | Value |
|---|---:|
| Content items | 248 |
| Rewrite-ready items | 94 |
| Primary media coverage | 77 |
| Media assets | 370 |
| Good media assets | 342 |

## Connection Issue

The working proxy was available on the host as:

```bash
https_proxy=socks5://127.0.0.1:12334
```

That address works for host commands, but inside Docker `127.0.0.1` is the container itself. The running Compose containers also had empty proxy configuration, so ingestion attempted direct outbound connections and marked sources as broken with `ConnectTimeout` or `Network is unreachable`.

Additional observations:

- Host `curl` through the proxy reached Telegram public pages with `HTTP 200`.
- Docker bridge containers could not reach the host-loopback proxy directly.
- `OpenAI Blog` returned `HTTP 403` even through the proxy.
- `Expert System - Artificial Intelligence` returned `HTTP 404`.
- `Machine Learnings` failed with a TLS EOF error.
- `AITopics` fetched but parsed as malformed/zero items.

## Solution

Compose now passes `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY` into the API and worker containers, and maps `host.docker.internal` to the Docker host gateway.

For Docker Compose runs, use a Docker-reachable proxy URL, for example:

```bash
export HTTPS_PROXY=socks5://host.docker.internal:12334
export ALL_PROXY=socks5://host.docker.internal:12334
export NO_PROXY=postgres,localhost,127.0.0.1
```

If the proxy application only listens on host loopback and Docker bridge containers still cannot reach it, configure the proxy to listen on a Docker-reachable interface or run a controlled local forwarder from a Docker-reachable host address to `127.0.0.1:12334`.

## Source Quality Result

Strong sources from the requested batch:

- `https://t.me/cvision`: 20 parsed, 13 rewrite-ready.
- `https://t.me/llm_huggingface`: 20 parsed, 13 rewrite-ready.
- `https://t.me/zarinacc_com`: 19 parsed, 16 rewrite-ready.
- `Machine Learning Mastery Blog`: 10 parsed, 8 rewrite-ready.
- `AWS Machine Learning Blog - AI Feed`: 20 parsed, 9 rewrite-ready.
- `DeepMind Blog`: 100 parsed, 32 rewrite-ready.

Sources to fix or replace:

- `https://openai.com/feed.xml?format=xml`: blocked by `HTTP 403`.
- `http://www.expertsystem.com/blog/feed`: broken with `HTTP 404`.
- `https://machinelearnings.co/feed`: TLS failure.
- `http://feeds.feedburner.com/AIInTheNews`: malformed/zero parsed items.

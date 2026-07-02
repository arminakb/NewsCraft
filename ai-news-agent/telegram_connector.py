"""Telegram channel connector using Telethon user sessions."""

import asyncio
import os
import re
from datetime import datetime

from config import TELEGRAM_CHANNELS
from utils import clean_token, is_within_date_range, normalize_date_for_storage, parse_article_date, redact_sensitive_text

try:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError, RPCError, SessionPasswordNeededError
except ImportError:  # pragma: no cover - exercised when dependency is absent
    TelegramClient = None
    FloodWaitError = RPCError = SessionPasswordNeededError = Exception


def _clean_username(username):
    return str(username or "").strip().lstrip("@")


def _channel_configs(channels):
    configs = []
    for item in TELEGRAM_CHANNELS if channels is None else channels:
        if isinstance(item, dict):
            username = _clean_username(item.get("username"))
            if username:
                configs.append({**item, "username": username})
        else:
            username = _clean_username(item)
            if username:
                configs.append({"name": username, "username": username, "source_group": "social_news", "quality_weight": 1.0})
    return configs


def parse_channel_usernames(text):
    return [_clean_username(line) for line in str(text or "").splitlines() if _clean_username(line)]


def _session_exists(session_name):
    return bool(session_name and (os.path.exists(session_name) or os.path.exists(f"{session_name}.session")))


def _clean_message_text(text):
    text = re.sub(r"[\U00010000-\U0010ffff]", "", str(text or ""))
    text = re.sub(r"\butm_[A-Za-z0-9_=-]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _title_from_text(text):
    for line in str(text or "").splitlines():
        line = _clean_message_text(line)
        if line:
            return line[:120]
    return "Telegram post"


def _post_url(username, message_id):
    return f"https://t.me/{_clean_username(username)}/{message_id}"


def _message_metrics(message):
    replies = getattr(getattr(message, "replies", None), "replies", 0) or 0
    return {
        "views": int(getattr(message, "views", 0) or 0),
        "forwards": int(getattr(message, "forwards", 0) or 0),
        "replies": int(replies),
    }


def _normalize_message(message, channel):
    text = _clean_message_text(getattr(message, "message", "") or getattr(message, "text", ""))
    if not text:
        return None
    username = channel["username"]
    published = parse_article_date(getattr(message, "date", None))
    return {
        "source": f"Telegram - {channel.get('name') or username}",
        "source_type": "telegram",
        "connector": "telegram",
        "source_group": channel.get("source_group", "social_news"),
        "title": _title_from_text(text),
        "url": _post_url(username, getattr(message, "id", "")),
        "published_at": normalize_date_for_storage(published),
        "summary": text,
        "category": "General",
        "score": 0,
        "metrics": {**_message_metrics(message), "quality_weight": float(channel.get("quality_weight", 1.0) or 1.0)},
    }


async def fetch_telegram_channel_posts(
    channels,
    start_datetime=None,
    end_datetime=None,
    limit_per_channel=20,
    telegram_api_id=None,
    telegram_api_hash=None,
    telegram_session_name="telegram_news_session",
    diagnostics=None,
):
    diagnostics = diagnostics if diagnostics is not None else {}
    telegram_api_id = clean_token(telegram_api_id)
    telegram_api_hash = clean_token(telegram_api_hash)
    telegram_session_name = clean_token(telegram_session_name) or "telegram_news_session"
    channel_configs = _channel_configs(channels)
    diagnostics.update(
        {
            "session_exists": _session_exists(telegram_session_name),
            "api_id_configured": bool(telegram_api_id),
            "api_hash_configured": bool(telegram_api_hash),
            "channels_configured": len(channel_configs),
            "channels_reachable": 0,
            "raw_messages_found": 0,
            "after_date_filter": 0,
            "normalized": 0,
            "errors": [],
        }
    )
    if not telegram_api_id or not telegram_api_hash:
        diagnostics["errors"].append("Telegram API ID/API Hash are required.")
        return []
    if TelegramClient is None:
        diagnostics["errors"].append("Telethon is not installed. Run pip install -r requirements.txt.")
        return []
    if not _session_exists(telegram_session_name):
        diagnostics["errors"].append("Telegram session file not found. Run python telegram_login.py first.")
        return []

    articles = []
    try:
        api_id = int(telegram_api_id)
        async with TelegramClient(telegram_session_name, api_id, telegram_api_hash) as client:
            if not await client.is_user_authorized():
                diagnostics["errors"].append("Telegram login required. Run python telegram_login.py.")
                return []
            for channel in channel_configs:
                try:
                    entity = await client.get_entity(channel["username"])
                    diagnostics["channels_reachable"] += 1
                    async for message in client.iter_messages(entity, limit=limit_per_channel):
                        diagnostics["raw_messages_found"] += 1
                        published = parse_article_date(getattr(message, "date", None))
                        if not is_within_date_range(published, start_datetime, end_datetime):
                            continue
                        diagnostics["after_date_filter"] += 1
                        article = _normalize_message(message, channel)
                        if article:
                            articles.append(article)
                            diagnostics["normalized"] += 1
                except FloodWaitError as exc:
                    diagnostics["errors"].append(f"{channel['username']}: flood wait {getattr(exc, 'seconds', '?')}s")
                except (RPCError, ValueError, TypeError) as exc:
                    diagnostics["errors"].append(f"{channel['username']}: {redact_sensitive_text(exc)}")
    except SessionPasswordNeededError:
        diagnostics["errors"].append("Telegram two-factor password required. Run python telegram_login.py.")
    except Exception as exc:
        diagnostics["errors"].append(redact_sensitive_text(exc))
    return articles


def fetch_telegram_posts_sync(
    channels=None,
    start_datetime=None,
    end_datetime=None,
    limit_per_channel=20,
    telegram_api_id=None,
    telegram_api_hash=None,
    telegram_session_name="telegram_news_session",
    diagnostics=None,
):
    return asyncio.run(
        fetch_telegram_channel_posts(
            TELEGRAM_CHANNELS if channels is None else channels,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            limit_per_channel=limit_per_channel,
            telegram_api_id=telegram_api_id,
            telegram_api_hash=telegram_api_hash,
            telegram_session_name=telegram_session_name,
            diagnostics=diagnostics,
        )
    )

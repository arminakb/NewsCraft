"""Streamlit dashboard entry point."""

import os
import re
from datetime import date, datetime, timedelta

import streamlit as st

from agent import run_news_agent
from approved_storage import (
    delete_approved_article,
    get_approved_articles,
    init_approved_db,
    save_approved_article,
)
from diagnostics import (
    test_arxiv_connector,
    test_github_connection,
    test_github_connector,
    test_hacker_news_connector,
    test_huggingface_connection,
    test_huggingface_connector,
    test_telegram_connection,
    test_telegram_connector,
)
from summarizer import truncate_text
from storage import clear_articles, get_articles, get_search_sessions, init_db, update_article_status
from telegram_connector import parse_channel_usernames
from utils import clean_token, humanize_time_ago

SOURCE_OPTIONS = ["rss", "hacker_news", "arxiv", "huggingface", "github", "youtube", "telegram"]
DEFAULT_SOURCES = ["rss", "hacker_news", "arxiv"]
SOURCE_OPTION_LABELS = {
    "rss": "RSS feeds",
    "hacker_news": "Hacker News",
    "arxiv": "arXiv",
    "huggingface": "Hugging Face",
    "github": "GitHub",
    "youtube": "YouTube",
    "telegram": "Telegram Channels",
}
SOURCE_TYPE_LABELS = {
    "rss": "RSS Feed",
    "hacker_news": "Hacker News API",
    "arxiv": "arXiv API",
    "github": "GitHub API",
    "huggingface": "Hugging Face API",
    "youtube": "YouTube RSS",
    "telegram": "Telegram API",
}
SOURCE_GROUP_LABELS = {
    "company_news": "Company News",
    "startup_news": "Startup News",
    "ai_industry_news": "AI Industry News",
    "developer_trends": "Developer Trends",
    "research": "Research",
    "model_trends": "Model Trends",
    "video": "Video",
    "social_news": "Social News",
}


def summary_preview(summary, limit=500):
    clean = re.sub(r"<[^>]+>", "", summary or "")
    clean = " ".join(clean.split())
    return clean[:limit]


def filter_articles(articles, category, status):
    return [
        article
        for article in articles
        if (category == "All" or article.get("category") == category)
        and (status == "All" or article.get("status") == status)
    ]


def resolve_time_range(choice, today=None):
    now = datetime.now()
    today = today or now.date()
    if choice == "Last 24 hours":
        return now - timedelta(hours=24), now, False
    if choice == "Last 3 days":
        return now - timedelta(days=3), now, False
    if choice == "Last 7 days":
        return now - timedelta(days=7), now, False
    return today - timedelta(days=1), today, True


def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _approve_button(article, key):
    if st.button("Approve", key=key):
        save_approved_article(article)
        st.session_state.review_message = "Article approved and saved to approved_articles.db."
        update_article_status(article["id"], "approved")
        _rerun()


def metrics_text(metrics):
    labels = {
        "stars": "Stars",
        "forks": "Forks",
        "open_issues": "Open issues",
        "likes": "Likes",
        "downloads": "Downloads",
        "task": "Task",
        "language": "Language",
        "channel": "Channel",
        "hn_score": "HN score",
        "comments": "Comments",
        "views": "Views",
        "forwards": "Forwards",
        "replies": "Replies",
    }
    return " | ".join(
        f"{labels.get(key, key)}: {', '.join(value[:5]) if isinstance(value, list) else value}"
        for key, value in (metrics or {}).items()
        if key not in {"useful_tags", "useful_topics", "quality_weight"} and value not in ("", None, 0)
    )


def resolve_tokens(session_state, environ=os.environ):
    return {
        "github_token": clean_token(session_state.get("github_token")) or clean_token(environ.get("GITHUB_TOKEN")),
        "huggingface_token": clean_token(session_state.get("huggingface_token")) or clean_token(environ.get("HUGGINGFACE_TOKEN")),
        "youtube_api_key": clean_token(session_state.get("youtube_api_key")) or clean_token(environ.get("YOUTUBE_API_KEY")),
        "telegram_api_id": clean_token(session_state.get("telegram_api_id")) or clean_token(environ.get("TELEGRAM_API_ID")),
        "telegram_api_hash": clean_token(session_state.get("telegram_api_hash")) or clean_token(environ.get("TELEGRAM_API_HASH")),
        "telegram_session_name": clean_token(session_state.get("telegram_session_name")) or clean_token(environ.get("TELEGRAM_SESSION_NAME")) or "telegram_news_session",
    }


def _clean_session_token(key):
    st.session_state[key] = clean_token(st.session_state.get(key)) or ""


def _configuration_contents(selected_sources, start_date, end_date):
    st.text_input(
        "GitHub API Token",
        type="password",
        key="github_token",
        help="Optional. Used to increase GitHub API rate limits.",
        on_change=_clean_session_token,
        args=("github_token",),
    )
    st.text_input(
        "Hugging Face API Token",
        type="password",
        key="huggingface_token",
        help="Optional. Used for authenticated Hugging Face requests if needed.",
        on_change=_clean_session_token,
        args=("huggingface_token",),
    )
    st.text_input(
        "YouTube API Key",
        type="password",
        key="youtube_api_key",
        help="Optional. Not required for YouTube RSS feeds. Reserved for future YouTube Data API support.",
        on_change=_clean_session_token,
        args=("youtube_api_key",),
    )
    st.divider()
    st.text_input(
        "Telegram API ID",
        key="telegram_api_id",
        help="Required for Telegram Channels. Get it from my.telegram.org.",
        on_change=_clean_session_token,
        args=("telegram_api_id",),
    )
    st.text_input(
        "Telegram API Hash",
        type="password",
        key="telegram_api_hash",
        help="Required for Telegram Channels. Stored only in this Streamlit session.",
        on_change=_clean_session_token,
        args=("telegram_api_hash",),
    )
    st.text_input(
        "Telegram Session Name",
        key="telegram_session_name",
        value=st.session_state.get("telegram_session_name", "telegram_news_session"),
        help="Local Telethon session name created by python telegram_login.py.",
        on_change=_clean_session_token,
        args=("telegram_session_name",),
    )
    st.text_area(
        "Telegram Channel Usernames",
        key="telegram_channels_text",
        help="One trusted channel username per line, with or without @.",
        placeholder="@OpenAINews\n@SomeAIChannel",
    )
    tokens = resolve_tokens(st.session_state)
    st.caption(f"GitHub token: {'configured' if tokens['github_token'] else 'not configured'}")
    st.caption(f"Hugging Face token: {'configured' if tokens['huggingface_token'] else 'not configured'}")
    st.caption(f"YouTube API key: {'configured' if tokens['youtube_api_key'] else 'not configured'}")
    st.caption(f"Telegram API ID: {'configured' if tokens['telegram_api_id'] else 'not configured'}")
    st.caption(f"Telegram API hash: {'configured' if tokens['telegram_api_hash'] else 'not configured'}")
    st.caption(f"Telegram session: {tokens['telegram_session_name']}")
    st.caption(f"Telegram channels: {len(parse_channel_usernames(st.session_state.get('telegram_channels_text')))} configured")
    with st.expander("Debug", expanded=False):
        st.write(f"Selected sources: {', '.join(selected_sources) or 'none'}")
        st.write(f"Active date range: {start_date} to {end_date}")
        st.write(f"Stored articles: {len(get_articles(limit=1000))}")
        if st.button("Test GitHub Connection"):
            st.json(test_github_connection(tokens["github_token"]))
        if st.button("Test Hugging Face Connection"):
            st.json(test_huggingface_connection(tokens["huggingface_token"]))
        if st.button("Test GitHub Connector"):
            st.json(test_github_connector(start_date, end_date, tokens["github_token"]))
        if st.button("Test Hugging Face Connector"):
            st.json(test_huggingface_connector(start_date, end_date, tokens["huggingface_token"]))
        if st.button("Test Hacker News Connector"):
            st.json(test_hacker_news_connector(start_date, end_date))
        if st.button("Test arXiv Connector"):
            st.json(test_arxiv_connector(start_date, end_date))
        if st.button("Test Telegram Connection"):
            st.json(
                test_telegram_connection(
                    telegram_api_id=tokens["telegram_api_id"],
                    telegram_api_hash=tokens["telegram_api_hash"],
                    telegram_session_name=tokens["telegram_session_name"],
                )
            )
        if st.button("Test Telegram Connector"):
            st.json(
                test_telegram_connector(
                    start_date,
                    end_date,
                    telegram_api_id=tokens["telegram_api_id"],
                    telegram_api_hash=tokens["telegram_api_hash"],
                    telegram_session_name=tokens["telegram_session_name"],
                    telegram_channels=parse_channel_usernames(st.session_state.get("telegram_channels_text")),
                )
            )


def _configuration_panel(selected_sources, start_date, end_date):
    if hasattr(st, "popover"):
        try:
            popover = st.popover("⚙️ Configuration", use_container_width=True)
        except TypeError:
            popover = st.popover("⚙️ Configuration")
        with popover:
            _configuration_contents(selected_sources, start_date, end_date)
    else:
        # Streamlit versions without popover cannot close on outside click; expander is the closest native fallback.
        with st.expander("⚙️ Configuration", expanded=False):
            _configuration_contents(selected_sources, start_date, end_date)


def _structured_text(article):
    summary = article.get("structured_summary") or {}
    if not summary:
        return
    st.markdown("**What it is:**")
    st.write(truncate_text(summary.get("what_it_is", ""), 180))
    if summary.get("why_it_matters"):
        st.markdown("**Why it matters:**")
        st.write(truncate_text(summary["why_it_matters"], 220))
    if summary.get("best_use_cases"):
        st.markdown("**Best use cases:**")
        for item in summary["best_use_cases"][:3]:
            st.write(f"- {truncate_text(item, 80)}")
    if summary.get("key_signals"):
        st.markdown("**Key signals:**")
        for item in summary["key_signals"][:4]:
            st.write(f"- {truncate_text(item, 100)}")
    if summary.get("visible_tags"):
        st.caption("Tags: " + ", ".join(summary["visible_tags"][:5]))


def _article_card(article, approved=False):
    with st.container(border=True):
        st.markdown(f"#### [{article['title']}]({article['url']})")
        source_type = article.get("source_type", "rss")
        source_group = article.get("source_group", "")
        st.caption(
            f"Source: {article.get('source', 'Unknown')} | Type: {SOURCE_TYPE_LABELS.get(source_type, source_type)} | "
            f"Group: {SOURCE_GROUP_LABELS.get(source_group, source_group or 'Unsorted')}"
        )
        st.caption(
            f"Score: {article['score']} | {humanize_time_ago(article.get('published_at'))} | "
            f"{article.get('published_at') or 'No date'} | {article.get('status', 'approved')}"
        )
        _structured_text(article)
        metrics = metrics_text(article.get("metrics"))
        if metrics and not article.get("structured_summary"):
            st.caption(metrics)
        if not article.get("structured_summary"):
            st.write(summary_preview(article.get("summary")))
        with st.expander("Raw details"):
            st.write(f"Source: {article['source']}")
            st.write(f"Type: {SOURCE_TYPE_LABELS.get(source_type, source_type)}")
            st.write(f"Group: {SOURCE_GROUP_LABELS.get(source_group, source_group or 'Unsorted')}")
            st.write(f"Category: {article['category']}")
            if metrics:
                st.write(metrics)
            if article.get("summary"):
                st.write(summary_preview(article.get("summary")))
        if approved:
            if st.button("Delete from approved list", key=f"delete-approved-{article['id']}"):
                delete_approved_article(article["id"])
                st.session_state.review_message = "Approved article deleted."
                _rerun()
        else:
            if article.get("status") == "approved":
                st.caption("Approved")
            else:
                _approve_button(article, f"approve-{article['id']}")


def main():
    st.set_page_config(page_title="AI & Tech News Agent Dashboard", layout="wide")
    init_db()
    init_approved_db()

    header_left, header_spacer, header_right = st.columns([4, 1, 2])
    with header_left:
        st.title("AI & Tech News Agent Dashboard")
        st.caption("Collect, rank, and review AI/tech news from selected sources.")
        if st.session_state.get("review_message"):
            st.success(st.session_state.pop("review_message"))

    today = date.today()
    with st.expander("Collection Controls", expanded=True):
        time_range = st.selectbox("Time range", ["Last 24 hours", "Last 3 days", "Last 7 days", "Custom range"], index=0)
        default_start, default_end, custom_range = resolve_time_range(time_range, today)
        if custom_range:
            start_col, end_col = st.columns(2)
            start_date = start_col.date_input("Start Date", value=default_start)
            end_date = end_col.date_input("End Date", value=default_end)
        else:
            start_date, end_date = default_start, default_end
            st.caption(f"Active time range: {start_date:%Y-%m-%d %H:%M} to {end_date:%Y-%m-%d %H:%M}")
        selected_sources = st.multiselect(
            "Select sources to collect from",
            options=SOURCE_OPTIONS,
            default=DEFAULT_SOURCES,
            format_func=lambda value: SOURCE_OPTION_LABELS.get(value, value),
        )
        st.caption(f"Showing articles from {start_date} to {end_date}")
        tokens = resolve_tokens(st.session_state)
        run_col, clear_col = st.columns([2, 2])
        if run_col.button("Run Agent for Selected Sources", type="primary"):
            articles = run_news_agent(
                start_date=start_date,
                end_date=end_date,
                selected_sources=selected_sources,
                github_token=tokens["github_token"],
                huggingface_token=tokens["huggingface_token"],
                youtube_api_key=tokens["youtube_api_key"],
                telegram_api_id=tokens["telegram_api_id"],
                telegram_api_hash=tokens["telegram_api_hash"],
                telegram_session_name=tokens["telegram_session_name"],
                telegram_channels=parse_channel_usernames(st.session_state.get("telegram_channels_text")),
            )
            st.session_state.current_search_session_id = articles.search_session_id
            st.success(f"Collected {len(articles)} relevant articles.")
            if hasattr(articles, "report"):
                articles.report["time_range"] = time_range
                st.json(articles.report)
        confirm_clear = clear_col.checkbox("I understand this clears stored collected items.")
        if clear_col.button("Clear Results Database", disabled=not confirm_clear):
            clear_articles()
            st.session_state.current_search_session_id = None
            st.success("Collected results cleared. Approved articles were not deleted.")
            _rerun()

    with header_right:
        _configuration_panel(selected_sources, start_date, end_date)

    with st.expander("Display Filters", expanded=False):
        col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
        category = col1.selectbox("Category", ["All", "AI", "Tech", "Research", "Tool", "Model", "Video", "General"])
        status = col2.selectbox("Status", ["All", "new", "approved", "rejected"])
        sort_by = col3.selectbox("Sort by", ["Latest first", "Highest score", "Most popular", "Source"])
        limit = col4.slider("Limit", 10, 100, 50, 10)

    main_tab, approved_tab = st.tabs(["Collected Articles", "Approved Articles"])

    with main_tab:
        st.subheader("Current Search Results")
        current_session = st.session_state.get("current_search_session_id")
        if not current_session:
            sessions = get_search_sessions(limit=1)
            current_session = sessions[0]["session_id"] if sessions else None
            st.session_state.current_search_session_id = current_session
        if current_session:
            st.caption(f"Search session: {current_session}")
        articles = get_articles(
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            category=category,
            status=status,
            search_session_id=current_session,
            sort_by=sort_by,
        )
        if not articles:
            st.info("No items found. Run a search, expand the date range, or run connector diagnostics from Configuration.")
        for article in articles:
            _article_card(article)

    with approved_tab:
        st.subheader("Approved Articles")
        approved = get_approved_articles(limit=limit, category=category)
        if not approved:
            st.info("No approved articles yet.")
        for article in approved:
            _article_card(article, approved=True)


if __name__ == "__main__":
    main()

"""Streamlit dashboard entry point."""

import os
import re
from datetime import date, timedelta

import streamlit as st

from agent import run_news_agent
from storage import clear_articles, get_articles, init_db, update_article_status

SOURCE_OPTIONS = ["rss", "hacker_news", "arxiv", "huggingface", "github", "youtube"]
DEFAULT_SOURCES = ["rss", "hacker_news", "arxiv"]


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


def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _status_button(label, article_id, status, key):
    if st.button(label, key=key):
        update_article_status(article_id, status)
        _rerun()


def metrics_text(metrics):
    labels = {"stars": "Stars", "forks": "Forks", "open_issues": "Open issues", "likes": "Likes", "downloads": "Downloads", "channel": "Channel"}
    return " | ".join(
        f"{labels.get(key, key)}: {value}" for key, value in (metrics or {}).items() if value not in ("", None, 0)
    )


def resolve_tokens(session_state, environ=os.environ):
    return {
        "github_token": session_state.get("github_token") or environ.get("GITHUB_TOKEN"),
        "huggingface_token": session_state.get("huggingface_token") or environ.get("HUGGINGFACE_TOKEN"),
        "youtube_api_key": session_state.get("youtube_api_key") or environ.get("YOUTUBE_API_KEY"),
    }


def _settings_panel(selected_sources, start_date, end_date):
    with st.container(border=True):
        st.subheader("Settings")
        token_tab, data_tab, debug_tab = st.tabs(["API Tokens", "Data", "Debug"])
        with token_tab:
            github_token = st.text_input(
                "GitHub API Token",
                value=st.session_state.get("github_token", ""),
                type="password",
                help="Optional. Used to increase GitHub API rate limits.",
            )
            huggingface_token = st.text_input(
                "Hugging Face API Token",
                value=st.session_state.get("huggingface_token", ""),
                type="password",
                help="Optional. Used for authenticated Hugging Face requests if needed.",
            )
            youtube_api_key = st.text_input(
                "YouTube API Key",
                value=st.session_state.get("youtube_api_key", ""),
                type="password",
                help="Optional. Not required for YouTube RSS feeds. Reserved for future YouTube Data API support.",
            )
            if st.button("Save Settings"):
                st.session_state.github_token = github_token
                st.session_state.huggingface_token = huggingface_token
                st.session_state.youtube_api_key = youtube_api_key
                st.success("Settings saved for this session.")
        with data_tab:
            st.write("Clear saved articles if old rows or old date formats still appear.")
            if st.button("Clear Old Database"):
                clear_articles()
                st.success("Stored articles cleared.")
                _rerun()
            st.caption("YouTube RSS feeds use channel IDs from config.py.")
        with debug_tab:
            tokens = resolve_tokens(st.session_state)
            st.write(f"Selected sources: {', '.join(selected_sources) or 'none'}")
            st.write(f"Active date range: {start_date} to {end_date}")
            st.write(f"Stored articles shown by current debug limit: {len(get_articles(limit=1000))}")
            st.write(f"GitHub token: {'configured' if tokens['github_token'] else 'not configured'}")
            st.write(f"Hugging Face token: {'configured' if tokens['huggingface_token'] else 'not configured'}")
            st.write(f"YouTube API key: {'configured' if tokens['youtube_api_key'] else 'not configured'}")


def main():
    st.set_page_config(page_title="AI & Tech News Agent Dashboard", layout="wide")
    init_db()

    if "show_settings" not in st.session_state:
        st.session_state.show_settings = False

    top_left, top_right = st.columns([4, 1])
    with top_left:
        st.title("AI & Tech News Agent Dashboard")
        st.caption("Collect, rank, and review AI/tech news from selected sources.")
    with top_right:
        if st.button("Settings"):
            st.session_state.show_settings = not st.session_state.show_settings

    today = date.today()
    with st.expander("Collection Controls", expanded=True):
        start_col, end_col = st.columns(2)
        start_date = start_col.date_input("Start Date", value=today - timedelta(days=1))
        end_date = end_col.date_input("End Date", value=today)
        selected_sources = st.multiselect(
            "Select sources to collect from",
            options=SOURCE_OPTIONS,
            default=DEFAULT_SOURCES,
        )
        st.caption(f"Showing articles from {start_date} to {end_date}")
        tokens = resolve_tokens(st.session_state)
        if st.button("Run Agent for Selected Sources", type="primary"):
            articles = run_news_agent(
                start_date=start_date,
                end_date=end_date,
                selected_sources=selected_sources,
                github_token=tokens["github_token"],
                huggingface_token=tokens["huggingface_token"],
                youtube_api_key=tokens["youtube_api_key"],
            )
            st.success(f"Collected {len(articles)} relevant articles.")

    if st.session_state.show_settings:
        _settings_panel(selected_sources, start_date, end_date)

    with st.expander("Display Filters", expanded=False):
        col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
        category = col1.selectbox("Category", ["All", "AI", "Tech", "Research", "Tool", "Model", "Video", "General"])
        status = col2.selectbox("Status", ["All", "new", "approved", "rejected"])
        source_type = col3.selectbox("Source Type", ["All", *SOURCE_OPTIONS])
        limit = col4.slider("Limit", 10, 100, 50, 10)

    st.subheader("Articles")

    articles = get_articles(
        limit=limit,
        start_date=start_date,
        end_date=end_date,
        category=category,
        status=status,
        source_type=source_type,
    )
    if not articles:
        st.info("No articles found for this date range. Try expanding the date range or running the agent again.")
        return

    for article in articles:
        with st.container(border=True):
            st.markdown(f"#### [{article['title']}]({article['url']})")
            st.caption(
                f"{article.get('source_type', 'rss')} | Score: {article['score']} | "
                f"{article.get('published_at') or 'No date'} | {article['status']}"
            )
            metrics = metrics_text(article.get("metrics"))
            if metrics:
                st.caption(metrics)
            st.write(summary_preview(article.get("summary")))
            with st.expander("Details"):
                st.write(f"Source: {article['source']}")
                st.write(f"Category: {article['category']}")
            a, b, c = st.columns(3)
            with a:
                _status_button("Approve", article["id"], "approved", f"approve-{article['id']}")
            with b:
                _status_button("Reject", article["id"], "rejected", f"reject-{article['id']}")
            with c:
                _status_button("Reset to New", article["id"], "new", f"reset-{article['id']}")


if __name__ == "__main__":
    main()

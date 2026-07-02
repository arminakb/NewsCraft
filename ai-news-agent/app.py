"""Streamlit dashboard entry point."""

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
    return " | ".join(f"{key}: {value}" for key, value in (metrics or {}).items() if value not in ("", None, 0))


def main():
    st.set_page_config(page_title="AI & Tech News Agent Dashboard", layout="wide")
    init_db()

    st.title("AI & Tech News Agent Dashboard")

    today = date.today()
    selected_sources = st.multiselect(
        "Select sources to collect from",
        options=SOURCE_OPTIONS,
        default=DEFAULT_SOURCES,
    )

    col1, col2, col3, col4, col5, col6 = st.columns([1, 1, 1, 1, 1, 2])
    category = col1.selectbox("Category", ["All", "AI", "Tech", "General"])
    status = col2.selectbox("Status", ["All", "new", "approved", "rejected"])
    source_type = col3.selectbox("Source Type", ["All", *SOURCE_OPTIONS])
    start_date = col4.date_input("Start Date", value=today - timedelta(days=1))
    end_date = col5.date_input("End Date", value=today)
    limit = col6.slider("Limit", 10, 100, 50, 10)

    st.caption(f"Showing articles from {start_date} to {end_date}")

    a, b = st.columns([2, 1])
    if a.button("Run Agent for Selected Sources", type="primary"):
        articles = run_news_agent(start_date=start_date, end_date=end_date, selected_sources=selected_sources)
        st.success(f"Collected {len(articles)} relevant articles.")
    if b.button("Clear Old Database"):
        clear_articles()
        st.success("Stored articles cleared.")
        _rerun()

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
            st.markdown(f"### [{article['title']}]({article['url']})")
            st.caption(
                f"{article['source']} | {article.get('source_type', 'rss')} | {article['category']} | Score: {article['score']} | "
                f"Status: {article['status']} | {article.get('published_at') or 'No date'}"
            )
            metrics = metrics_text(article.get("metrics"))
            if metrics:
                st.caption(metrics)
            st.write(summary_preview(article.get("summary")))
            a, b, c = st.columns(3)
            with a:
                _status_button("Approve", article["id"], "approved", f"approve-{article['id']}")
            with b:
                _status_button("Reject", article["id"], "rejected", f"reject-{article['id']}")
            with c:
                _status_button("Reset to New", article["id"], "new", f"reset-{article['id']}")


if __name__ == "__main__":
    main()

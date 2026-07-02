"""Streamlit dashboard entry point."""

import re
from datetime import date, timedelta

import streamlit as st

from agent import run_news_agent
from storage import clear_articles, get_articles, init_db, update_article_status


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


def main():
    st.set_page_config(page_title="AI & Tech News Agent Dashboard", layout="wide")
    init_db()

    st.title("AI & Tech News Agent Dashboard")

    today = date.today()
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 2])
    category = col1.selectbox("Category", ["All", "AI", "Tech", "General"])
    status = col2.selectbox("Status", ["All", "new", "approved", "rejected"])
    start_date = col3.date_input("Start Date", value=today - timedelta(days=1))
    end_date = col4.date_input("End Date", value=today)
    limit = col5.slider("Limit", 10, 100, 50, 10)

    st.caption(f"Showing articles from {start_date} to {end_date}")

    a, b = st.columns([2, 1])
    if a.button("Run News Agent for Selected Date Range", type="primary"):
        articles = run_news_agent(start_date=start_date, end_date=end_date)
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
    )
    if not articles:
        st.info("No articles found for this date range. Try expanding the date range or running the agent again.")
        return

    for article in articles:
        with st.container(border=True):
            st.markdown(f"### [{article['title']}]({article['url']})")
            st.caption(
                f"{article['source']} | {article['category']} | Score: {article['score']} | "
                f"Status: {article['status']} | {article.get('published_at') or 'No date'}"
            )
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

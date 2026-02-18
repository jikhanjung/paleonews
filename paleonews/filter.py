import logging
import re

logger = logging.getLogger(__name__)


def is_dedicated_feed(feed_url: str, patterns: list[str]) -> bool:
    """Check if feed_url matches any dedicated feed pattern."""
    feed_lower = feed_url.lower()
    return any(p.lower() in feed_lower for p in patterns)


def keyword_match(title: str, summary: str, keywords: list[str]) -> bool:
    """Return True if any keyword appears in title or summary (case-insensitive)."""
    text = f"{title} {summary}".lower()
    return any(re.search(rf"\b{re.escape(kw.lower())}\b", text) for kw in keywords)


def filter_articles(db, config: dict) -> int:
    """Filter unfiltered articles and update DB. Returns count of relevant articles."""
    dedicated = config.get("dedicated_feeds", [])
    keywords = config.get("filter", {}).get("keywords", [])

    unfiltered = db.get_unfiltered()
    relevant_count = 0

    for article in unfiltered:
        feed_url = article.get("feed_url", "") or ""

        if is_dedicated_feed(feed_url, dedicated):
            is_relevant = True
        else:
            title = article.get("title", "") or ""
            summary = article.get("summary", "") or ""
            is_relevant = keyword_match(title, summary, keywords)

        db.mark_relevant(article["id"], is_relevant)
        if is_relevant:
            relevant_count += 1

    logger.info(
        "Filtered %d articles: %d relevant, %d irrelevant",
        len(unfiltered), relevant_count, len(unfiltered) - relevant_count,
    )
    return relevant_count

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import mktime

import feedparser

logger = logging.getLogger(__name__)

USER_AGENT = "PaleoNews/0.1 (+https://github.com/paleonews)"


@dataclass
class Article:
    url: str
    title: str
    summary: str
    source: str
    feed_url: str
    published: datetime | None


def load_sources(path: str) -> list[str]:
    """Load feed URLs from sources file, one per line."""
    lines = Path(path).read_text().strip().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def fetch_feed(url: str) -> list[Article]:
    """Parse a single RSS/Atom feed and return Article list."""
    feed = feedparser.parse(url, agent=USER_AGENT)

    if feed.bozo and not feed.entries:
        logger.warning("Failed to parse feed %s: %s", url, feed.bozo_exception)
        return []

    source = feed.feed.get("title", url)
    articles = []

    for entry in feed.entries:
        link = entry.get("link", "")
        if not link:
            continue

        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published = datetime.fromtimestamp(
                    mktime(entry.published_parsed), tz=timezone.utc
                )
            except (ValueError, OverflowError):
                pass

        summary = entry.get("summary", "") or entry.get("description", "")
        # Strip HTML tags from summary (simple approach)
        if "<" in summary:
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()

        articles.append(
            Article(
                url=link,
                title=entry.get("title", ""),
                summary=summary,
                source=source,
                feed_url=url,
                published=published,
            )
        )

    logger.info("Fetched %d articles from %s", len(articles), source)
    return articles


def fetch_all(sources: list[str]) -> list[Article]:
    """Fetch all feeds and return combined article list."""
    all_articles = []
    for url in sources:
        try:
            articles = fetch_feed(url)
            all_articles.extend(articles)
        except Exception:
            logger.exception("Error fetching %s", url)
    return all_articles

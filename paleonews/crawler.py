import logging
import re
import time

import httpx
from readability import Document

logger = logging.getLogger(__name__)

USER_AGENT = "PaleoNews/0.1 (+https://github.com/paleonews)"
MAX_BODY_LENGTH = 5000  # characters, to limit LLM token cost
REQUEST_DELAY = 1.5  # seconds between requests


def extract_text(html: str) -> str:
    """Extract main article text from HTML using readability."""
    doc = Document(html)
    content_html = doc.summary()
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", content_html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_BODY_LENGTH]


def crawl_article(url: str) -> str | None:
    """Fetch article URL and extract body text. Returns None on failure."""
    try:
        with httpx.Client(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(url)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            logger.warning("Skipping %s: content-type %s", url, content_type)
            return None

        text = extract_text(response.text)
        if len(text) < 100:
            logger.warning("Skipping %s: extracted only %d chars", url, len(text))
            return None

        return text
    except Exception as e:
        logger.warning("Failed to crawl %s: %s", url, e)
        return None


def crawl_articles(db, max_crawl: int = 20, max_attempts: int = 3) -> int:
    """Crawl body text for relevant articles that haven't been crawled yet.
    Returns count of successfully crawled articles."""
    uncrawled = db.get_uncrawled(max_attempts=max_attempts)
    targets = uncrawled[:max_crawl]
    crawled = 0

    for i, article in enumerate(targets):
        logger.info("Crawling (%d/%d) %s", i + 1, len(targets), article["url"][:80])
        body = crawl_article(article["url"])
        if body:
            db.save_body(article["id"], body)
            crawled += 1
        else:
            # Count the failure so a permanently dead URL retires from the queue
            db.record_crawl_failure(article["id"])

        if i < len(targets) - 1:
            time.sleep(REQUEST_DELAY)

    if targets and crawled == 0:
        logger.error("Crawled 0/%d articles — every fetch failed", len(targets))
    else:
        logger.info("Crawled %d/%d articles", crawled, len(targets))
    return crawled

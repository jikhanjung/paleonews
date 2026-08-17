"""Tests for the crawl queue — ordering, attempt cap, and starvation regression."""

import sqlite3
from datetime import datetime, timezone

from paleonews.crawler import crawl_articles
from paleonews.db import Database
from paleonews.fetcher import Article


def make_article(n: int):
    return Article(
        url=f"https://example.com/{n}",
        title=f"Article {n}",
        summary="A test summary",
        source="Test Source",
        feed_url="https://example.com/feed",
        published=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def make_db(count: int) -> Database:
    """DB with `count` relevant, uncrawled, unsummarized articles (oldest id first)."""
    db = Database(":memory:")
    db.init_tables()
    db.save_articles([make_article(n) for n in range(1, count + 1)])
    for article in db.get_unfiltered():
        db.mark_relevant(article["id"], True)
    return db


def test_uncrawled_is_newest_first():
    db = make_db(3)
    ids = [a["id"] for a in db.get_uncrawled()]
    assert ids == sorted(ids, reverse=True)
    db.close()


def test_uncrawled_skips_summarized():
    db = make_db(2)
    oldest = db.get_uncrawled()[-1]
    db.save_summary(oldest["id"], "제목", "요약")

    remaining = [a["id"] for a in db.get_uncrawled()]
    assert oldest["id"] not in remaining
    db.close()


def test_uncrawled_retires_after_max_attempts():
    db = make_db(1)
    article_id = db.get_uncrawled()[0]["id"]

    for _ in range(3):
        db.record_crawl_failure(article_id)

    assert db.get_uncrawled(max_attempts=3) == []
    assert len(db.get_uncrawled(max_attempts=4)) == 1
    db.close()


def test_dead_urls_do_not_starve_newer_articles(monkeypatch):
    """Regression: a block of permanently failing URLs used to sit at the head of
    the queue forever, so newer articles were never reached (crawled = 0 for months)."""
    db = make_db(5)
    dead = {f"https://example.com/{n}" for n in (1, 2)}  # oldest two always fail

    monkeypatch.setattr("paleonews.crawler.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "paleonews.crawler.crawl_article",
        lambda url: None if url in dead else "body text",
    )

    # Only two slots per run — under the old ordering the dead pair consumed both.
    crawled = crawl_articles(db, max_crawl=2, max_attempts=3)
    assert crawled == 2

    bodies = db.conn.execute(
        "SELECT url FROM articles WHERE body IS NOT NULL ORDER BY id"
    ).fetchall()
    assert [r["url"] for r in bodies] == [
        "https://example.com/4",
        "https://example.com/5",
    ]
    db.close()


def test_failed_crawl_increments_attempts(monkeypatch):
    db = make_db(1)
    monkeypatch.setattr("paleonews.crawler.time.sleep", lambda _: None)
    monkeypatch.setattr("paleonews.crawler.crawl_article", lambda url: None)

    assert crawl_articles(db, max_crawl=5) == 0
    attempts = db.conn.execute("SELECT crawl_attempts FROM articles").fetchone()[0]
    assert attempts == 1
    db.close()


def test_migration_adds_crawl_attempts(tmp_path):
    """An existing DB without crawl_attempts gains the column with 0 for every row."""
    db_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT UNIQUE NOT NULL,
            title       TEXT NOT NULL,
            summary     TEXT,
            source      TEXT,
            feed_url    TEXT,
            published   TEXT,
            fetched_at  TEXT NOT NULL,
            is_relevant BOOLEAN,
            summary_ko  TEXT,
            title_ko    TEXT,
            body        TEXT
        );
    """)
    conn.execute(
        "INSERT INTO articles (url, title, fetched_at, is_relevant) VALUES (?, ?, ?, 1)",
        ("https://example.com/old", "Old article", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    db.init_tables()

    cols = [row[1] for row in db.conn.execute("PRAGMA table_info(articles)")]
    assert "crawl_attempts" in cols
    assert db.conn.execute("SELECT crawl_attempts FROM articles").fetchone()[0] == 0
    assert len(db.get_uncrawled()) == 1
    db.close()

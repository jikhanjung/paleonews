from datetime import datetime, timezone

from paleonews.db import Database
from paleonews.fetcher import Article


def make_article(url="https://example.com/1", title="Test Article"):
    return Article(
        url=url,
        title=title,
        summary="A test summary",
        source="Test Source",
        feed_url="https://example.com/feed",
        published=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_init_tables():
    db = Database(":memory:")
    db.init_tables()
    # Should not raise on second call
    db.init_tables()
    db.close()


def test_save_articles_dedup():
    db = Database(":memory:")
    db.init_tables()

    articles = [make_article(), make_article()]
    inserted = db.save_articles(articles)
    assert inserted == 1

    # Insert again — should be 0 new
    inserted = db.save_articles([make_article()])
    assert inserted == 0
    db.close()


def test_unfiltered_flow():
    db = Database(":memory:")
    db.init_tables()
    db.save_articles([make_article()])

    unfiltered = db.get_unfiltered()
    assert len(unfiltered) == 1
    assert unfiltered[0]["is_relevant"] is None

    db.mark_relevant(unfiltered[0]["id"], True)
    assert len(db.get_unfiltered()) == 0
    db.close()


def test_summary_flow():
    db = Database(":memory:")
    db.init_tables()
    db.save_articles([make_article()])
    db.mark_relevant(1, True)

    unsummarized = db.get_unsummarized()
    assert len(unsummarized) == 1

    db.save_summary(1, "테스트 제목", "테스트 요약")
    assert len(db.get_unsummarized()) == 0
    db.close()


def test_dispatch_flow():
    db = Database(":memory:")
    db.init_tables()
    db.save_articles([make_article()])
    db.mark_relevant(1, True)
    db.save_summary(1, "테스트 제목", "테스트 요약")

    unsent = db.get_unsent("telegram")
    assert len(unsent) == 1

    db.record_dispatch(1, "telegram", "success")
    assert len(db.get_unsent("telegram")) == 0
    db.close()


def test_stats():
    db = Database(":memory:")
    db.init_tables()
    db.save_articles([
        make_article("https://example.com/1"),
        make_article("https://example.com/2"),
    ])
    db.mark_relevant(1, True)
    db.mark_relevant(2, False)
    db.save_summary(1, "제목", "요약")
    db.record_dispatch(1, "telegram", "success")

    stats = db.get_stats()
    assert stats["total"] == 2
    assert stats["relevant"] == 1
    assert stats["summarized"] == 1
    assert stats["sent"] == 1
    db.close()

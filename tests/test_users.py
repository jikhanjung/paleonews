"""Tests for multi-user support (Phase 4)."""

import json

from paleonews.db import Database
from paleonews.filter import filter_articles_for_user


# --- DB user CRUD tests ---

def _make_db():
    db = Database(":memory:")
    db.init_tables()
    return db


def test_add_and_get_user():
    db = _make_db()
    uid = db.add_user("12345", username="testuser", display_name="Test User")
    assert uid is not None

    user = db.get_user_by_chat_id("12345")
    assert user is not None
    assert user["chat_id"] == "12345"
    assert user["username"] == "testuser"
    assert user["is_active"] == 1
    assert user["is_admin"] == 0
    assert user["keywords"] is None
    db.close()


def test_add_user_duplicate():
    db = _make_db()
    db.add_user("12345")
    try:
        db.add_user("12345")
        assert False, "Should have raised"
    except Exception:
        pass
    db.close()


def test_get_active_users():
    db = _make_db()
    db.add_user("111")
    db.add_user("222")
    uid3 = db.add_user("333")
    db.update_user_active(uid3, False)

    active = db.get_active_users()
    assert len(active) == 2
    chat_ids = {u["chat_id"] for u in active}
    assert chat_ids == {"111", "222"}
    db.close()


def test_update_user_keywords():
    db = _make_db()
    uid = db.add_user("12345")

    # Initially None (all articles)
    assert db.get_user_keywords(uid) is None

    # Set keywords
    db.update_user_keywords(uid, ["fossil", "dinosaur"])
    kw = db.get_user_keywords(uid)
    assert kw == ["fossil", "dinosaur"]

    # Reset to all
    db.update_user_keywords(uid, None)
    assert db.get_user_keywords(uid) is None
    db.close()


def test_remove_user():
    db = _make_db()
    uid = db.add_user("12345")
    assert db.get_user(uid) is not None
    db.remove_user(uid)
    assert db.get_user(uid) is None
    db.close()


def test_seed_admin():
    db = _make_db()
    admin_id = db.seed_admin("99999", username="admin")
    user = db.get_user(admin_id)
    assert user["is_admin"] == 1
    assert user["chat_id"] == "99999"

    # Calling again should not create duplicate
    admin_id2 = db.seed_admin("99999")
    assert admin_id == admin_id2
    db.close()


def test_seed_admin_upgrades_existing():
    db = _make_db()
    uid = db.add_user("99999")
    user = db.get_user(uid)
    assert user["is_admin"] == 0

    admin_id = db.seed_admin("99999")
    assert admin_id == uid
    user = db.get_user(uid)
    assert user["is_admin"] == 1
    db.close()


# --- Per-user dispatch tests ---

def _setup_articles(db):
    """Insert test articles and mark as summarized."""
    from datetime import datetime, timezone
    from paleonews.fetcher import Article

    articles = [
        Article(url="https://example.com/1", title="New dinosaur fossil found",
                summary="A fossil discovery", source="Nature", feed_url="https://nature.com/feed",
                published=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        Article(url="https://example.com/2", title="Mammoth DNA sequenced",
                summary="Mammoth genome study", source="Science", feed_url="https://science.com/feed",
                published=datetime(2026, 1, 2, tzinfo=timezone.utc)),
        Article(url="https://example.com/3", title="Trilobite evolution",
                summary="Study on trilobite morphology", source="PNAS", feed_url="https://pnas.com/feed",
                published=datetime(2026, 1, 3, tzinfo=timezone.utc)),
    ]
    db.save_articles(articles)
    for i in range(1, 4):
        db.mark_relevant(i, True)
        db.save_summary(i, f"제목{i}", f"요약{i}")


def test_get_unsent_for_user():
    db = _make_db()
    _setup_articles(db)
    uid = db.add_user("12345")

    unsent = db.get_unsent_for_user("telegram", uid)
    assert len(unsent) == 3

    # Record dispatch for one article
    db.record_dispatch(1, "telegram", "success", user_id=uid)
    unsent = db.get_unsent_for_user("telegram", uid)
    assert len(unsent) == 2
    assert all(a["id"] != 1 for a in unsent)
    db.close()


def test_get_unsent_for_user_independent():
    """Each user has independent dispatch tracking."""
    db = _make_db()
    _setup_articles(db)
    uid1 = db.add_user("111")
    uid2 = db.add_user("222")

    # Send article 1 to user 1 only
    db.record_dispatch(1, "telegram", "success", user_id=uid1)

    assert len(db.get_unsent_for_user("telegram", uid1)) == 2
    assert len(db.get_unsent_for_user("telegram", uid2)) == 3
    db.close()


# --- Per-user keyword filter tests ---

def test_filter_articles_for_user_none_keywords():
    """None keywords = receive all."""
    articles = [
        {"title_ko": "공룡 화석 발견", "summary_ko": "새로운 화석"},
        {"title_ko": "매머드 DNA", "summary_ko": "유전체 연구"},
    ]
    result = filter_articles_for_user(articles, None)
    assert len(result) == 2


def test_filter_articles_for_user_empty_keywords():
    """Empty keywords list = receive nothing."""
    articles = [{"title_ko": "공룡 화석", "summary_ko": "발견"}]
    result = filter_articles_for_user(articles, [])
    assert len(result) == 0


def test_filter_articles_for_user_with_keywords():
    """Keywords filter applied to title_ko and summary_ko."""
    articles = [
        {"id": 1, "title": "New dinosaur fossil", "title_ko": "공룡 화석", "summary_ko": "fossil 발견", "summary": ""},
        {"id": 2, "title": "Mammoth DNA", "title_ko": "매머드 DNA", "summary_ko": "mammoth 연구", "summary": ""},
        {"id": 3, "title": "Trilobite study", "title_ko": "삼엽충 연구", "summary_ko": "trilobite morphology", "summary": ""},
    ]

    # Only articles matching "fossil" or "mammoth"
    result = filter_articles_for_user(articles, ["fossil", "mammoth"])
    assert len(result) == 2
    ids = {a["id"] for a in result}
    assert ids == {1, 2}


def test_filter_articles_for_user_fallback_to_title():
    """When title_ko is empty, falls back to title."""
    articles = [
        {"id": 1, "title": "Dinosaur fossil found", "title_ko": "", "summary_ko": "", "summary": "A discovery"},
    ]
    result = filter_articles_for_user(articles, ["dinosaur"])
    assert len(result) == 1


# --- Migration tests ---

def test_dispatches_user_id_column():
    """Dispatches table should have user_id column."""
    db = _make_db()
    cols = [row[1] for row in db.conn.execute("PRAGMA table_info(dispatches)")]
    assert "user_id" in cols
    db.close()


def test_users_table_exists():
    db = _make_db()
    tables = [row[0] for row in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )]
    assert "users" in tables
    db.close()


def test_record_dispatch_with_user_id():
    db = _make_db()
    _setup_articles(db)
    uid = db.add_user("12345")

    db.record_dispatch(1, "telegram", "success", user_id=uid)
    row = db.conn.execute(
        "SELECT user_id FROM dispatches WHERE article_id = 1"
    ).fetchone()
    assert row["user_id"] == uid
    db.close()


def test_record_dispatch_without_user_id():
    """Email/Slack dispatches still work without user_id."""
    db = _make_db()
    _setup_articles(db)

    db.record_dispatch(1, "email", "success")
    row = db.conn.execute(
        "SELECT user_id FROM dispatches WHERE article_id = 1"
    ).fetchone()
    assert row["user_id"] is None
    db.close()


def test_seed_admin_backfills_dispatches():
    db = _make_db()
    _setup_articles(db)

    # Record dispatches without user_id (old behavior)
    db.record_dispatch(1, "telegram", "success")
    db.record_dispatch(2, "telegram", "success")

    # Seed admin — should backfill
    admin_id = db.seed_admin("99999")

    rows = db.conn.execute(
        "SELECT user_id FROM dispatches WHERE channel = 'telegram'"
    ).fetchall()
    for row in rows:
        assert row["user_id"] == admin_id
    db.close()

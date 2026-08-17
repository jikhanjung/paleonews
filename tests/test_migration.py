"""Tests for DB migration from old schema (pre-Phase 4) to new schema."""

import sqlite3

from paleonews.db import Database


def _create_old_schema_db() -> sqlite3.Connection:
    """Create an in-memory DB with old schema (no users table, no user_id in dispatches)."""
    conn = sqlite3.connect(":memory:")
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

        CREATE TABLE dispatches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id  INTEGER NOT NULL REFERENCES articles(id),
            channel     TEXT NOT NULL,
            sent_at     TEXT NOT NULL,
            status      TEXT NOT NULL
        );

        CREATE TABLE pipeline_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            fetched     INTEGER DEFAULT 0,
            new_articles INTEGER DEFAULT 0,
            relevant    INTEGER DEFAULT 0,
            crawled     INTEGER DEFAULT 0,
            summarized  INTEGER DEFAULT 0,
            sent        INTEGER DEFAULT 0,
            errors      TEXT,
            status      TEXT NOT NULL DEFAULT 'running'
        );
    """)
    return conn


def _insert_old_data(conn: sqlite3.Connection):
    """Insert test data in old schema format."""
    # 3 articles
    conn.execute(
        "INSERT INTO articles (url, title, summary, source, feed_url, fetched_at, is_relevant, title_ko, summary_ko, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("https://example.com/1", "Dinosaur fossil found", "A new discovery",
         "Nature", "https://nature.com/feed", "2026-01-01T00:00:00", 1,
         "공룡 화석 발견", "새로운 발견", "Full body text here"),
    )
    conn.execute(
        "INSERT INTO articles (url, title, summary, source, feed_url, fetched_at, is_relevant, title_ko, summary_ko) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("https://example.com/2", "Mammoth DNA study", "Genome sequenced",
         "Science", "https://science.com/feed", "2026-01-02T00:00:00", 1,
         "매머드 DNA 연구", "유전체 분석 완료"),
    )
    conn.execute(
        "INSERT INTO articles (url, title, summary, source, feed_url, fetched_at, is_relevant) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://example.com/3", "Quantum physics news", "Not paleo",
         "Science", "https://science.com/feed", "2026-01-03T00:00:00", 0),
    )

    # dispatches without user_id (old format)
    conn.execute(
        "INSERT INTO dispatches (article_id, channel, sent_at, status) VALUES (?, ?, ?, ?)",
        (1, "telegram", "2026-01-01T12:00:00", "success"),
    )
    conn.execute(
        "INSERT INTO dispatches (article_id, channel, sent_at, status) VALUES (?, ?, ?, ?)",
        (2, "telegram", "2026-01-02T12:00:00", "success"),
    )
    conn.execute(
        "INSERT INTO dispatches (article_id, channel, sent_at, status) VALUES (?, ?, ?, ?)",
        (1, "email", "2026-01-01T12:00:00", "success"),
    )

    # pipeline run
    conn.execute(
        "INSERT INTO pipeline_runs (started_at, finished_at, fetched, new_articles, relevant, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-01-01T00:00:00", "2026-01-01T00:05:00", 10, 3, 2, "success"),
    )
    conn.commit()


def _migrate_old_db() -> Database:
    """Create old schema DB with data, then migrate via Database.init_tables()."""
    conn = _create_old_schema_db()
    _insert_old_data(conn)

    # Monkey-patch: make Database use our existing connection
    db = Database.__new__(Database)
    db.db_path = ":memory:"
    db.conn = conn
    db.conn.row_factory = sqlite3.Row
    db.conn.execute("PRAGMA foreign_keys=ON")
    db.conn.execute("PRAGMA busy_timeout=5000")

    # Run migration
    db.init_tables()
    return db


def test_migration_preserves_articles():
    db = _migrate_old_db()
    rows = db.conn.execute("SELECT * FROM articles ORDER BY id").fetchall()
    assert len(rows) == 3

    a1 = dict(rows[0])
    assert a1["url"] == "https://example.com/1"
    assert a1["title"] == "Dinosaur fossil found"
    assert a1["is_relevant"] == 1
    assert a1["title_ko"] == "공룡 화석 발견"
    assert a1["summary_ko"] == "새로운 발견"
    assert a1["body"] == "Full body text here"

    a3 = dict(rows[2])
    assert a3["is_relevant"] == 0
    assert a3["title_ko"] is None
    db.close()


def test_migration_preserves_dispatches():
    db = _migrate_old_db()
    rows = db.conn.execute("SELECT * FROM dispatches ORDER BY id").fetchall()
    assert len(rows) == 3

    d1 = dict(rows[0])
    assert d1["article_id"] == 1
    assert d1["channel"] == "telegram"
    assert d1["status"] == "success"
    # user_id should be NULL after migration (not yet backfilled)
    assert d1["user_id"] is None
    db.close()


def test_migration_adds_user_id_column():
    db = _migrate_old_db()
    cols = [row[1] for row in db.conn.execute("PRAGMA table_info(dispatches)")]
    assert "user_id" in cols
    db.close()


def test_migration_creates_users_table():
    db = _migrate_old_db()
    tables = [row[0] for row in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )]
    assert "users" in tables

    # No users yet (admin not seeded)
    assert len(db.get_all_users()) == 0
    db.close()


def test_migration_preserves_pipeline_runs():
    db = _migrate_old_db()
    runs = db.get_recent_runs(10)
    assert len(runs) == 1
    assert runs[0]["fetched"] == 10
    assert runs[0]["new_articles"] == 3
    assert runs[0]["status"] == "success"
    db.close()


def test_migration_seed_admin_backfills():
    """After migration, seed_admin should backfill old telegram dispatches."""
    db = _migrate_old_db()

    admin_id = db.seed_admin("99999", username="admin")

    # Old telegram dispatches should now have admin's user_id
    tg_rows = db.conn.execute(
        "SELECT * FROM dispatches WHERE channel = 'telegram'"
    ).fetchall()
    for row in tg_rows:
        assert dict(row)["user_id"] == admin_id

    # Email dispatch should remain NULL
    email_rows = db.conn.execute(
        "SELECT * FROM dispatches WHERE channel = 'email'"
    ).fetchall()
    for row in email_rows:
        assert dict(row)["user_id"] is None
    db.close()


def test_migration_existing_data_still_queryable():
    """After migration, all existing DB methods still work correctly."""
    db = _migrate_old_db()

    # get_stats
    stats = db.get_stats()
    assert stats["total"] == 3
    assert stats["relevant"] == 2
    assert stats["summarized"] == 2
    assert stats["sent"] == 2  # article 1 and 2

    # get_unsummarized (none — both relevant articles already summarized)
    assert len(db.get_unsummarized()) == 0

    # get_unfiltered (none — all articles filtered)
    assert len(db.get_unfiltered()) == 0

    # get_source_stats
    source_stats = db.get_source_stats()
    assert len(source_stats) == 2  # Nature and Science
    db.close()


def test_migration_new_user_dispatch_after_migration():
    """After migration, new per-user dispatches work correctly."""
    db = _migrate_old_db()

    # Add user and seed admin
    admin_id = db.seed_admin("99999")
    user_id = db.add_user("12345", username="testuser")

    # Admin: article 1,2 already sent (backfilled), so unsent should be 0
    unsent_admin = db.get_unsent_for_user("telegram", admin_id)
    assert len(unsent_admin) == 0

    # New user: nothing sent yet, should see 2 summarized articles
    unsent_new = db.get_unsent_for_user("telegram", user_id)
    assert len(unsent_new) == 2
    urls = {a["url"] for a in unsent_new}
    assert urls == {"https://example.com/1", "https://example.com/2"}

    # Send one to new user
    db.record_dispatch(1, "telegram", "success", user_id=user_id)
    unsent_new = db.get_unsent_for_user("telegram", user_id)
    assert len(unsent_new) == 1
    assert unsent_new[0]["url"] == "https://example.com/2"
    db.close()


def test_migration_idempotent():
    """Calling init_tables() multiple times should not break anything."""
    db = _migrate_old_db()

    # Run init_tables again
    db.init_tables()
    db.init_tables()

    # Data should still be intact
    stats = db.get_stats()
    assert stats["total"] == 3
    assert len(db.get_all_users()) == 0

    cols = [row[1] for row in db.conn.execute("PRAGMA table_info(dispatches)")]
    assert cols.count("user_id") == 1  # not duplicated
    db.close()


# --- 레거시 chat_id 스키마 (Phase 4 이전) ------------------------------------

def _legacy_chat_id_db(path: str) -> sqlite3.Connection:
    """Phase 4 이전 스키마 — `chat_id` NOT NULL, `email`·notify_* 없음."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id      TEXT UNIQUE NOT NULL,
            username     TEXT,
            display_name TEXT,
            is_active    BOOLEAN NOT NULL DEFAULT 1,
            is_admin     BOOLEAN NOT NULL DEFAULT 0,
            keywords     TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        INSERT INTO users (chat_id, username, is_active, is_admin, keywords,
                           created_at, updated_at)
        VALUES ('123', '관리자', 1, 1, NULL, '2026-01-01', '2026-01-01');
    """)
    conn.commit()
    return conn


def test_migrate_legacy_schema_with_referencing_rows(tmp_path):
    """`users` 를 참조하는 행이 있어도 재구축이 완주해야 한다.

    회귀: `dispatches.user_id`·`memories.user_id` 가 users 를 참조하는데
    `PRAGMA foreign_keys=ON` 상태로 테이블을 갈아끼워 **FOREIGN KEY constraint failed** 로 죽었다.
    발송 이력이 있는 **실제 운영 DB 는 전부 여기 걸린다** — 앞의 테스트들은 참조 표가 없어 못 잡았다.
    """
    path = str(tmp_path / "refs.db")
    conn = _legacy_chat_id_db(path)
    conn.executescript("""
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, fetched_at TEXT NOT NULL
        );
        INSERT INTO articles (url, title, fetched_at)
        VALUES ('https://example.com/1', 'T', '2026-01-01');
        CREATE TABLE dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL REFERENCES articles(id),
            channel TEXT NOT NULL, sent_at TEXT NOT NULL, status TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id)
        );
        INSERT INTO dispatches (article_id, channel, sent_at, status, user_id)
        VALUES (1, 'telegram', '2026-01-01', 'success', 1);
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        INSERT INTO memories (user_id, content, created_at)
        VALUES (1, '메모', '2026-01-01');
    """)
    conn.commit()
    conn.close()

    db = Database(path)
    db.init_tables()

    cols = {row[1]: row for row in db.conn.execute("PRAGMA table_info(users)")}
    assert not cols["telegram_chat_id"][3]
    # 참조가 살아 있어야 한다 — user_id 가 고아가 되면 발송 이력·메모가 끊긴다.
    assert db.conn.execute("SELECT user_id FROM dispatches").fetchone()[0] == 1
    assert db.conn.execute("SELECT user_id FROM memories").fetchone()[0] == 1
    assert not db.conn.execute("PRAGMA foreign_key_check").fetchall()
    # 재구축 뒤에도 FK 강제가 다시 켜져 있어야 한다.
    assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    db.close()


def test_migrate_legacy_chat_id_schema(tmp_path):
    """레거시 DB 를 열어도 마이그레이션이 완주해야 한다.

    회귀: `email` 은 이 마이그레이션 직전에 **맨 뒤로** 추가되는데 재구축 테이블은 5번째로
    선언한다. `INSERT ... SELECT *` 였을 땐 순서가 어긋나 `keywords`(NULL)가 `is_admin`
    (NOT NULL) 자리로 들어가 죽었다 — 즉 **오래된 백업으로는 복구가 불가능했다.**
    """
    path = str(tmp_path / "legacy.db")
    _legacy_chat_id_db(path).close()

    db = Database(path)
    db.init_tables()

    cols = {row[1]: row for row in db.conn.execute("PRAGMA table_info(users)")}
    assert "telegram_chat_id" in cols and "chat_id" not in cols
    assert not cols["telegram_chat_id"][3], "telegram_chat_id 의 NOT NULL 이 안 풀렸다"
    assert {"email", "notify_telegram", "notify_email"} <= set(cols)

    row = db.conn.execute(
        "SELECT telegram_chat_id, username, is_active, is_admin, keywords FROM users"
    ).fetchone()
    assert tuple(row) == ("123", "관리자", 1, 1, None), "컬럼이 어긋나 값이 밀렸다"
    db.close()


def test_migrate_repairs_half_migrated_users_table(tmp_path):
    """rename 만 되고 재구축이 실패해 NOT NULL 이 남은 DB 도 복구된다.

    rename 은 자체 커밋이라, 예전엔 재구축이 실패하면 다음 실행에서 `chat_id` 가 이미 없어
    분기를 건너뛰고 **NOT NULL 인 채 영영 굳었다**(이메일 전용 사용자를 못 만든다).
    """
    path = str(tmp_path / "half.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            username     TEXT,
            display_name TEXT,
            is_active    BOOLEAN NOT NULL DEFAULT 1,
            is_admin     BOOLEAN NOT NULL DEFAULT 0,
            keywords     TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        , email TEXT);
        INSERT INTO users (telegram_chat_id, username, is_active, is_admin,
                           created_at, updated_at)
        VALUES ('456', '구독자', 1, 0, '2026-01-01', '2026-01-01');
    """)
    conn.commit()
    conn.close()

    db = Database(path)
    db.init_tables()

    cols = {row[1]: row for row in db.conn.execute("PRAGMA table_info(users)")}
    assert not cols["telegram_chat_id"][3], "NOT NULL 이 그대로 남았다"
    # 이메일 전용 사용자(telegram_chat_id 없음)를 만들 수 있어야 한다.
    uid = db.add_user(telegram_chat_id=None, username="이메일만", email="x@example.com")
    assert db.get_user(uid)["telegram_chat_id"] is None
    db.close()


def test_migrate_restarts_after_crashed_rebuild(tmp_path):
    """재구축이 중간에 죽어 `users_new` 가 남아 있어도 다시 열 수 있어야 한다.

    회귀: executescript 는 문장별로 적용돼(암묵 커밋) 중간 실패 시 `users_new` 가 남았고,
    다음 실행이 "table users_new already exists" 로 막혀 **DB 를 영영 못 열었다.**
    복구 시나리오에서 이건 치명적이다 — 백업이 있어도 열리지 않는다.
    """
    path = str(tmp_path / "crashed.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            username     TEXT,
            display_name TEXT,
            is_active    BOOLEAN NOT NULL DEFAULT 1,
            is_admin     BOOLEAN NOT NULL DEFAULT 0,
            keywords     TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        , email TEXT);
        INSERT INTO users (telegram_chat_id, is_active, is_admin, created_at, updated_at)
        VALUES ('789', 1, 0, '2026-01-01', '2026-01-01');
        -- 죽은 재구축이 남긴 잔재
        CREATE TABLE users_new (id INTEGER PRIMARY KEY AUTOINCREMENT);
    """)
    conn.commit()
    conn.close()

    db = Database(path)
    db.init_tables()          # 여기서 터지면 안 된다

    cols = {row[1]: row for row in db.conn.execute("PRAGMA table_info(users)")}
    assert not cols["telegram_chat_id"][3]
    assert db.conn.execute("SELECT telegram_chat_id FROM users").fetchone()[0] == "789"
    leftovers = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'users_new'").fetchall()
    assert not leftovers, "재구축 잔재가 남았다"
    db.close()

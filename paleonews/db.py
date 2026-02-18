import json
import sqlite3
from datetime import datetime, timezone


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
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

            CREATE TABLE IF NOT EXISTS dispatches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id  INTEGER NOT NULL REFERENCES articles(id),
                channel     TEXT NOT NULL,
                sent_at     TEXT NOT NULL,
                status      TEXT NOT NULL,
                user_id     INTEGER REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
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

            CREATE TABLE IF NOT EXISTS users (
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
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Run schema migrations for existing DBs."""
        # Migrate: add body column if missing
        article_cols = [row[1] for row in self.conn.execute("PRAGMA table_info(articles)")]
        if "body" not in article_cols:
            self.conn.execute("ALTER TABLE articles ADD COLUMN body TEXT")
            self.conn.commit()

        # Migrate: add user_id column to dispatches if missing
        dispatch_cols = [row[1] for row in self.conn.execute("PRAGMA table_info(dispatches)")]
        if "user_id" not in dispatch_cols:
            self.conn.execute("ALTER TABLE dispatches ADD COLUMN user_id INTEGER REFERENCES users(id)")
            self.conn.commit()

    def seed_admin(self, chat_id: str, username: str | None = None):
        """Seed admin user from TELEGRAM_CHAT_ID. Backfills existing telegram dispatches."""
        existing = self.get_user_by_chat_id(chat_id)
        if existing:
            if not existing["is_admin"]:
                self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (existing["id"],))
                self.conn.commit()
            return existing["id"]

        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """INSERT INTO users (chat_id, username, display_name, is_active, is_admin, keywords, created_at, updated_at)
               VALUES (?, ?, ?, 1, 1, NULL, ?, ?)""",
            (chat_id, username, username, now, now),
        )
        self.conn.commit()
        admin_id = cursor.lastrowid

        # Backfill existing telegram dispatches with admin user_id
        self.conn.execute(
            "UPDATE dispatches SET user_id = ? WHERE channel = 'telegram' AND user_id IS NULL",
            (admin_id,),
        )
        self.conn.commit()
        return admin_id

    # --- User CRUD ---

    def add_user(self, chat_id: str, username: str | None = None,
                 display_name: str | None = None, is_admin: bool = False) -> int:
        """Add a new user. Returns user id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """INSERT INTO users (chat_id, username, display_name, is_active, is_admin, keywords, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, NULL, ?, ?)""",
            (chat_id, username, display_name or username, is_admin, now, now),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_user_by_chat_id(self, chat_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_active_users(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM users WHERE is_active = 1").fetchall()
        return [dict(r) for r in rows]

    def get_all_users(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def update_user_active(self, user_id: int, is_active: bool):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
            (is_active, now, user_id),
        )
        self.conn.commit()

    def update_user_keywords(self, user_id: int, keywords: list[str] | None):
        """Set user keywords. None means receive all articles."""
        now = datetime.now(timezone.utc).isoformat()
        kw_json = json.dumps(keywords, ensure_ascii=False) if keywords is not None else None
        self.conn.execute(
            "UPDATE users SET keywords = ?, updated_at = ? WHERE id = ?",
            (kw_json, now, user_id),
        )
        self.conn.commit()

    def get_user_keywords(self, user_id: int) -> list[str] | None:
        """Get user keywords. Returns None if user receives all articles."""
        row = self.conn.execute("SELECT keywords FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or row["keywords"] is None:
            return None
        return json.loads(row["keywords"])

    def remove_user(self, user_id: int):
        self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()

    # --- Article methods ---

    def save_articles(self, articles) -> int:
        """Save articles to DB. Returns count of newly inserted rows."""
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for a in articles:
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO articles
                       (url, title, summary, source, feed_url, published, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (a.url, a.title, a.summary, a.source, a.feed_url,
                     a.published.isoformat() if a.published else None, now),
                )
                if self.conn.execute("SELECT changes()").fetchone()[0] > 0:
                    inserted += 1
            except sqlite3.Error:
                continue
        self.conn.commit()
        return inserted

    def get_unfiltered(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM articles WHERE is_relevant IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_relevant(self, article_id: int, is_relevant: bool):
        self.conn.execute(
            "UPDATE articles SET is_relevant = ? WHERE id = ?",
            (is_relevant, article_id),
        )
        self.conn.commit()

    def get_unsummarized(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM articles WHERE is_relevant = 1 AND summary_ko IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def save_summary(self, article_id: int, title_ko: str, summary_ko: str):
        self.conn.execute(
            "UPDATE articles SET title_ko = ?, summary_ko = ? WHERE id = ?",
            (title_ko, summary_ko, article_id),
        )
        self.conn.commit()

    def get_unsent(self, channel: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT a.* FROM articles a
               WHERE a.is_relevant = 1
                 AND a.summary_ko IS NOT NULL
                 AND a.id NOT IN (
                     SELECT article_id FROM dispatches
                     WHERE channel = ? AND status = 'success'
                       AND user_id IS NULL
                 )""",
            (channel,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_unsent_for_user(self, channel: str, user_id: int) -> list[dict]:
        """Get articles not yet sent to a specific user on a channel."""
        rows = self.conn.execute(
            """SELECT a.* FROM articles a
               WHERE a.is_relevant = 1
                 AND a.summary_ko IS NOT NULL
                 AND a.id NOT IN (
                     SELECT article_id FROM dispatches
                     WHERE channel = ? AND user_id = ? AND status = 'success'
                 )""",
            (channel, user_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_dispatch(self, article_id: int, channel: str, status: str,
                        user_id: int | None = None):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO dispatches (article_id, channel, sent_at, status, user_id)
               VALUES (?, ?, ?, ?, ?)""",
            (article_id, channel, now, status, user_id),
        )
        self.conn.commit()

    def get_uncrawled(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM articles WHERE is_relevant = 1 AND body IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def save_body(self, article_id: int, body: str):
        self.conn.execute(
            "UPDATE articles SET body = ? WHERE id = ?",
            (body, article_id),
        )
        self.conn.commit()

    # --- Pipeline run methods ---

    def start_run(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "INSERT INTO pipeline_runs (started_at, status) VALUES (?, 'running')",
            (now,),
        )
        self.conn.commit()
        return cursor.lastrowid

    def finish_run(self, run_id: int, **kwargs):
        now = datetime.now(timezone.utc).isoformat()
        errors = kwargs.pop("errors", None)
        sets = ["finished_at = ?", "status = ?"]
        vals = [now, "error" if errors else "success"]
        if errors:
            sets.append("errors = ?")
            vals.append("\n".join(errors))
        for key in ("fetched", "new_articles", "relevant", "crawled", "summarized", "sent"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(kwargs[key])
        vals.append(run_id)
        self.conn.execute(
            f"UPDATE pipeline_runs SET {', '.join(sets)} WHERE id = ?", vals,
        )
        self.conn.commit()

    def get_recent_runs(self, limit: int = 5) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_source_stats(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT source,
                      COUNT(*) as total,
                      SUM(CASE WHEN is_relevant = 1 THEN 1 ELSE 0 END) as relevant,
                      SUM(CASE WHEN summary_ko IS NOT NULL THEN 1 ELSE 0 END) as summarized
               FROM articles
               GROUP BY source
               ORDER BY total DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        relevant = self.conn.execute(
            "SELECT COUNT(*) FROM articles WHERE is_relevant = 1"
        ).fetchone()[0]
        summarized = self.conn.execute(
            "SELECT COUNT(*) FROM articles WHERE summary_ko IS NOT NULL"
        ).fetchone()[0]
        sent = self.conn.execute(
            "SELECT COUNT(DISTINCT article_id) FROM dispatches WHERE status = 'success'"
        ).fetchone()[0]
        return {
            "total": total,
            "relevant": relevant,
            "summarized": summarized,
            "sent": sent,
        }

    def close(self):
        self.conn.close()

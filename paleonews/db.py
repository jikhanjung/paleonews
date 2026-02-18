import sqlite3
from datetime import datetime, timezone


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

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
                status      TEXT NOT NULL
            );
        """)
        self.conn.commit()
        # Migrate: add body column if missing (for existing DBs)
        columns = [row[1] for row in self.conn.execute("PRAGMA table_info(articles)")]
        if "body" not in columns:
            self.conn.execute("ALTER TABLE articles ADD COLUMN body TEXT")
            self.conn.commit()

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
                 )""",
            (channel,),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_dispatch(self, article_id: int, channel: str, status: str):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO dispatches (article_id, channel, sent_at, status)
               VALUES (?, ?, ?, ?)""",
            (article_id, channel, now, status),
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

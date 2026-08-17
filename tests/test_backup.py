"""백업 안전망 — 무결성 게이트와 반출 위생.

`scripts/backup_db.py` 는 패키지가 아니라 cron 이 직접 실행하는 스크립트라 경로로 로드한다.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_backup_module(root: Path):
    """`PALEONEWS_ROOT` 를 임시 경로로 고정한 채 스크립트를 로드한다(경로가 import 시점에 굳는다)."""
    import os
    os.environ["PALEONEWS_ROOT"] = str(root)
    spec = importlib.util.spec_from_file_location(
        "backup_db_under_test", REPO_ROOT / "scripts" / "backup_db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_db(path: Path, *, sessions: int = 0, articles: int = 1) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, url TEXT UNIQUE, title TEXT)")
    conn.executemany(
        "INSERT INTO articles (url, title) VALUES (?, ?)",
        [(f"https://example.com/{i}", f"제목 {i} " + "x" * 80) for i in range(articles)])
    if sessions:
        conn.executescript("""
            CREATE TABLE django_session (
                session_key varchar(40) NOT NULL PRIMARY KEY,
                session_data text NOT NULL, expire_date datetime NOT NULL);
            CREATE TABLE auth_user (
                id INTEGER PRIMARY KEY, username TEXT, password TEXT);
            INSERT INTO auth_user VALUES (1, 'admin', 'pbkdf2_sha256$strong-hash');
        """)
        conn.executemany(
            "INSERT INTO django_session VALUES (?, 'payload', '2026-12-01')",
            [(f"tok{i}-bearer-secret",) for i in range(sessions)])
    conn.commit()
    conn.close()


@pytest.fixture
def root(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "backup").mkdir()
    return tmp_path


def snapshot_of(root: Path) -> Path:
    snaps = list((root / "backup").glob("paleonews_*.sqlite3"))
    assert len(snaps) == 1, f"스냅샷이 1개가 아니다: {snaps}"
    return snaps[0]


def test_backup_purges_sessions_but_keeps_everything_else(root):
    """세션은 bearer 토큰이라 사본에서 지운다. 비밀번호 해시와 운영 데이터는 남긴다."""
    src = root / "data" / "paleonews.db"
    make_db(src, sessions=3)
    mod = load_backup_module(root)

    assert mod.backup_one("paleonews", src) is not None

    snap = sqlite3.connect(snapshot_of(root))
    assert snap.execute("SELECT COUNT(*) FROM django_session").fetchone()[0] == 0
    assert snap.execute("SELECT password FROM auth_user").fetchone()[0].startswith("pbkdf2")
    assert snap.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
    snap.close()

    # VACUUM 까지 하므로 토큰 문자열이 free page 에도 남지 않는다.
    assert b"bearer-secret" not in snapshot_of(root).read_bytes()


def test_live_db_is_never_touched(root):
    """★ 위생 대상은 **사본뿐**이다 — 로그인한 사용자가 튕기면 안 된다."""
    src = root / "data" / "paleonews.db"
    make_db(src, sessions=3)
    mod = load_backup_module(root)

    mod.backup_one("paleonews", src)

    live = sqlite3.connect(src)
    assert live.execute("SELECT COUNT(*) FROM django_session").fetchone()[0] == 3
    live.close()


def test_backup_without_session_table_is_fine(root):
    """세션 테이블이 없는 DB(Django admin 도입 전)도 그냥 백업된다."""
    src = root / "data" / "paleonews.db"
    make_db(src)
    mod = load_backup_module(root)

    assert mod.backup_one("paleonews", src) is not None
    snap = sqlite3.connect(snapshot_of(root))
    assert snap.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
    snap.close()


def test_corrupt_source_is_not_adopted_and_pruning_stops(root):
    """손상 시 ① 미채택 ② 과거 스냅샷 보존 ③ 증거 1개 ④ 센티넬."""
    src = root / "data" / "paleonews.db"
    # 손상이 **실제로 페이지를 깨뜨리도록** 충분히 크게 만든다. 몇 KB 짜리 DB 는 임의 오프셋을
    # 덮어도 빈 공간에 떨어져 integrity_check 를 통과해버린다(이 테스트가 처음에 그렇게 헛돌았다).
    make_db(src, articles=3000)
    mod = load_backup_module(root)

    # 과거 스냅샷 2개를 미리 놓아 둔다.
    for stamp in ("20260101_01", "20260101_02"):
        (root / "backup" / f"paleonews_{stamp}.sqlite3").write_bytes(src.read_bytes())

    with open(src, "r+b") as f:      # 페이지 중간을 깨뜨린다
        f.seek(20000)
        f.write(b"\xde\xad\xbe\xef" * 512)

    assert mod.backup_one("paleonews", src) is None
    assert (root / "backup" / "paleonews_INTEGRITY_FAIL.corrupt").exists()
    assert (root / "data" / "INTEGRITY_FAIL").exists()
    survivors = sorted(p.name for p in (root / "backup").glob("paleonews_2026*.sqlite3"))
    assert survivors == ["paleonews_20260101_01.sqlite3", "paleonews_20260101_02.sqlite3"]


def test_snapshot_is_static_and_leaves_no_sidecars(root):
    """스냅샷은 journal_mode=DELETE 여야 한다 — WAL 이면 읽기 전용 검사가 고아 `-shm` 을 남긴다."""
    src = root / "data" / "paleonews.db"
    make_db(src)
    sqlite3.connect(src).execute("PRAGMA journal_mode=WAL").close()
    mod = load_backup_module(root)

    mod.backup_one("paleonews", src)

    snap = snapshot_of(root)
    assert sqlite3.connect(snap).execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert not list((root / "backup").glob("*.tmp*"))
    assert not list((root / "backup").glob("*-wal"))
    assert not list((root / "backup").glob("*-shm"))

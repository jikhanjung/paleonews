"""`/healthz` — 배포 계약 헬스체크 + 무결성 센티넬 소비.

센티넬은 `scripts/backup_db.py` 가 PRAGMA integrity_check 실패 시 DB 옆에 남긴다.
**아무도 읽지 않는 센티넬은 "검사가 있다는 착각"만 만든다** — healthz 가 읽고 smoke 가
실패시키는 것까지가 한 세트다. 그 고리를 여기서 고정한다.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paleonews import web


@pytest.fixture
def db_dir(tmp_path, monkeypatch):
    """web.get_db() 가 임시 경로에 DB 를 만들게 한다.

    Database 를 여기서 만들어 주입하면 안 된다 — sqlite3 커넥션은 만든 스레드에서만 쓸 수 있는데
    TestClient 는 앱을 다른 스레드에서 돌린다. `_db` 를 비워 두고 **요청 스레드가 직접** 열게 한다.
    """
    monkeypatch.setattr(web, "_db", None)
    monkeypatch.setattr(web, "get_config_yaml_only",
                        lambda: {"db_path": str(tmp_path / "paleonews.db")})
    yield tmp_path
    # 닫지 않는다 — 커넥션은 앱 스레드가 열었으므로 여기서 close() 하면 같은 스레드 제약에 걸린다.
    # monkeypatch 가 `_db` 를 원복하고 tmp_path 는 지워지므로 새는 건 없다.


@pytest.fixture
def client(db_dir):
    with TestClient(web.app) as c:
        yield c


@pytest.fixture
def sentinel(db_dir) -> Path:
    return db_dir / web.INTEGRITY_SENTINEL


def test_healthz_ok(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert set(body["counts"]) == {"articles", "feeds", "users"}
    assert "integrity" not in body


def test_healthz_degraded_when_sentinel_present(client, sentinel):
    sentinel.write_text(
        "2026-08-17 00:00:00 backup_db.py: PRAGMA integrity_check 실패.\n상세 줄\n")

    resp = client.get("/healthz")
    body = resp.json()
    # HTTP 는 200 을 유지한다 — 서비스는 살아 있고 배포도 성공한 것이다.
    # deploy.sh 의 healthz 대기가 여기서 막히면 안 된다. 잡는 건 smoke 의 몫.
    assert resp.status_code == 200
    assert body["status"] == "degraded"
    assert body["integrity"].startswith("2026-08-17")
    assert body["db"] is True


def test_healthz_recovers_when_sentinel_removed(client, sentinel):
    sentinel.write_text("손상\n")
    assert client.get("/healthz").json()["status"] == "degraded"

    sentinel.unlink()
    assert client.get("/healthz").json()["status"] == "ok"

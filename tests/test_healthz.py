"""`/healthz` — 배포 계약 헬스체크 + 무결성 센티넬 소비.

센티넬은 `scripts/backup_db.py` 가 PRAGMA integrity_check 실패 시 DB 옆에 남긴다.
**아무도 읽지 않는 센티넬은 "검사가 있다는 착각"만 만든다** — healthz 가 읽고 smoke 가
실패시키는 것까지가 한 세트다. 그 고리를 여기서 고정한다.
"""


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

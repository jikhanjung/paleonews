"""파이프라인 오케스트레이션 특성화 — `_run_pipeline` 의 계약.

P08 §P2 에서 이 함수는 `manage.py run_pipeline` 관리 명령으로 옮겨간다. 옮기다 깨지기 쉬운 건
단계별 로직이 아니라 **단계들을 엮는 규약**이라, 그걸 여기서 못박는다:

- 순서: fetch → filter → crawl → summarize → send
- **한 단계가 실패해도 나머지는 계속 진행한다**(CLAUDE.md 규약). 실패는 모아서 기록·통지.
- `pipeline_runs` 에 회차 수치를 남긴다. `sent` 는 **회차 증분**이지 누적 총계가 아니다(0.3.4).
- 실패가 있으면 관리자에게 통지한다.

각 단계 자체는 여기서 돌리지 않는다 — 네트워크·LLM 과금이 걸린다. 전부 대역으로 바꾼다.
"""
from __future__ import annotations

import pytest

import paleonews.__main__ as main_mod
from paleonews.db import Database


@pytest.fixture
def db(tmp_path):
    conn = Database(str(tmp_path / "paleonews.db"))
    conn.init_tables()
    yield conn
    conn.close()


@pytest.fixture
def stages(monkeypatch):
    """5단계를 전부 대역으로 교체하고 호출 순서를 기록한다."""
    calls: list[str] = []

    def stub(name, retval=0):
        def _fn(db, config):
            calls.append(name)
            return retval
        return _fn

    monkeypatch.setattr(main_mod, "cmd_fetch", lambda db, config: (calls.append("fetch"), (7, 3))[1])
    monkeypatch.setattr(main_mod, "cmd_filter", stub("filter", 3))
    monkeypatch.setattr(main_mod, "cmd_crawl", stub("crawl", 2))
    monkeypatch.setattr(main_mod, "cmd_summarize", stub("summarize", 2))
    monkeypatch.setattr(main_mod, "cmd_send", stub("send"))
    monkeypatch.setattr(main_mod, "_notify_admin", lambda config, errors: calls.append("notify"))
    return calls


def last_run(db) -> dict:
    return db.get_recent_runs(1)[0]


def test_stage_order_and_recorded_counts(db, stages):
    main_mod._run_pipeline(db, {})

    assert stages == ["fetch", "filter", "crawl", "summarize", "send"]

    run = last_run(db)
    assert run["status"] == "success"
    assert (run["fetched"], run["new_articles"]) == (7, 3)
    assert (run["relevant"], run["crawled"], run["summarized"]) == (3, 2, 2)
    assert not run["errors"]


def test_failing_stage_does_not_stop_the_rest(db, stages, monkeypatch):
    """크롤이 터져도 요약·전송은 돈다 — 단계별 독립 실행 규약."""
    def boom(db, config):
        stages.append("crawl")
        raise RuntimeError("크롤 폭발")

    monkeypatch.setattr(main_mod, "cmd_crawl", boom)
    main_mod._run_pipeline(db, {})

    assert stages == ["fetch", "filter", "crawl", "summarize", "send", "notify"]
    run = last_run(db)
    assert "크롤 폭발" in run["errors"]
    assert run["summarized"] == 2, "뒤 단계가 실행되지 않았다"
    assert run["crawled"] == 0, "실패한 단계는 0 으로 기록돼야 한다"


def test_every_stage_failing_still_completes_the_run(db, stages, monkeypatch):
    for name in ("cmd_fetch", "cmd_filter", "cmd_crawl", "cmd_summarize", "cmd_send"):
        monkeypatch.setattr(main_mod, name,
                            lambda db, config: (_ for _ in ()).throw(RuntimeError("실패")))
    main_mod._run_pipeline(db, {})

    run = last_run(db)
    assert run["finished_at"], "run 이 마무리되지 않았다"
    # 단계마다 한 줄씩 — 5단계 전부가 독립적으로 시도되고 각자 기록됐다는 뜻.
    assert run["errors"].splitlines() == [
        "수집 실패: 실패", "필터링 실패: 실패", "크롤링 실패: 실패",
        "요약 실패: 실패", "전송 실패: 실패",
    ]
    assert stages == ["notify"]


def test_sent_is_this_run_not_all_time_total(db, stages, monkeypatch):
    """`sent` 는 회차 증분이다.

    0.3.4 이전엔 `db.get_stats()["sent"]`(전체 누적 dispatch 수)를 그대로 넣어, 마지막 회차 값이
    dispatches 테이블 전체 개수였다. 과거 발송이 쌓여 있는 상태에서 이번 회차 값이 나와야 한다.
    """
    from paleonews.fetcher import Article

    # 과거 발송 2건을 미리 쌓아 둔다.
    db.save_articles([
        Article(url="https://example.com/old1", title="old1", summary="", source="s",
                feed_url="f", published=None),
        Article(url="https://example.com/old2", title="old2", summary="", source="s",
                feed_url="f", published=None),
    ])
    old_ids = [a["id"] for a in db.get_unfiltered()]
    for aid in old_ids:
        db.record_dispatch(aid, "telegram", "success")

    # 이번 회차엔 1건만 발송한다.
    db.save_articles([Article(url="https://example.com/new", title="new", summary="", source="s",
                              feed_url="f", published=None)])
    new_id = [a["id"] for a in db.get_unfiltered() if a["id"] not in old_ids][0]

    def send(db_, config):
        stages.append("send")
        db_.record_dispatch(new_id, "telegram", "success")

    monkeypatch.setattr(main_mod, "cmd_send", send)
    main_mod._run_pipeline(db, {})

    assert last_run(db)["sent"] == 1, "누적 총계가 들어갔다"


def test_send_failure_records_zero_sent(db, stages, monkeypatch):
    monkeypatch.setattr(main_mod, "cmd_send",
                        lambda db, config: (_ for _ in ()).throw(RuntimeError("전송 실패")))
    main_mod._run_pipeline(db, {})

    run = last_run(db)
    assert run["sent"] == 0
    assert "전송 실패" in run["errors"]

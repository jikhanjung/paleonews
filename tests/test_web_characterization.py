"""웹 계층 특성화 테스트 — Django 전환(P08 §P2) 전에 현행 동작을 못박는다.

"이 동작이 옳다"를 주장하지 않는다. **"지금 이렇게 동작한다"를 고정한다.**
포팅 중 값이 조용히 바뀌면 여기서 걸린다.

무엇을 어떻게 덮는지:
- **상태를 바꾸는 POST 12개**: 요청 전후 DB 상태가 계약이다. 여기가 진짜 위험 구간.
- **HTML 5화면**: 전체 바이트 골든은 뜨지 않는다(템플릿을 손대면 매번 깨져 쓸모없어진다).
  200 + **화면에 실제 데이터가 실렸는지**만 본다 — 빈 표를 200 으로 돌려주는 회귀를 잡는 선.
  (0.3.3 의 교훈: `/healthz` 200 은 페이지가 살아 있다는 증거가 아니다.)
"""
from __future__ import annotations

import json

import pytest

from paleonews.fetcher import Article


# --- 시드 -----------------------------------------------------------------

@pytest.fixture
def seeded(client, db):
    """결정적 시드. 이 픽스처를 쓰는 테스트는 모두 같은 출발 상태를 본다."""
    uid = db.add_user(telegram_chat_id="100", username="관리자", is_admin=True,
                      email="admin@example.com")
    other = db.add_user(telegram_chat_id="200", username="구독자")
    db.update_user_keywords(other, ["공룡", "화석"])
    db.add_feed("https://example.com/feed1.xml")
    db.add_feed("https://example.com/feed2.xml")
    db.save_articles([Article(
        url="https://example.com/a1", title="Dinosaur fossil found",
        summary="A discovery", source="Nature", feed_url="https://example.com/feed1.xml",
        published=None)])
    db.set_setting("llm.provider", "claude_code")
    return {"admin_id": uid, "sub_id": other}


def post(client, path, **form):
    """폼 POST. 리다이렉트는 따라가지 않는다 — 어디로 보내는지도 계약이다."""
    return client.post(path, data=form, follow_redirects=False)


# --- 화면 -----------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/articles", "/users", "/settings"])
def test_pages_render(client, seeded, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert len(resp.text) > 500, "템플릿이 렌더되지 않고 빈 껍데기가 나왔다"


def test_dashboard_shows_real_counts(client, seeded):
    """대시보드가 DB 를 실제로 조회했는지 — 0 만 그리는 회귀를 잡는다."""
    assert "Dinosaur fossil found" in client.get("/articles").text


def test_users_page_lists_users_and_keywords(client, seeded):
    text = client.get("/users").text
    assert "관리자" in text and "구독자" in text
    assert "공룡" in text, "사용자별 키워드가 화면에 안 실렸다"


def test_user_detail_renders(client, seeded):
    resp = client.get(f"/users/{seeded['sub_id']}")
    assert resp.status_code == 200
    assert "구독자" in resp.text


def test_user_detail_unknown_redirects(client, seeded):
    resp = client.get("/users/99999", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/users"


def test_settings_page_shows_feeds(client, seeded):
    text = client.get("/settings").text
    assert "https://example.com/feed1.xml" in text


# --- 사용자 CRUD ----------------------------------------------------------

def test_add_user(client, seeded, db):
    before = len(db.get_all_users())
    resp = post(client, "/users/add", telegram_chat_id="300", name="새사람",
                email="new@example.com")
    assert resp.status_code == 303 and resp.headers["location"] == "/users"

    users = db.get_all_users()
    assert len(users) == before + 1
    added = next(u for u in users if u["telegram_chat_id"] == "300")
    assert (added["username"], added["email"], bool(added["is_admin"])) == \
           ("새사람", "new@example.com", False)


def test_add_user_with_duplicate_telegram_id_is_ignored(client, seeded, db):
    """중복 chat_id 는 **에러가 아니라 무시**하고 목록으로 돌아간다 — 현행 동작."""
    before = len(db.get_all_users())
    resp = post(client, "/users/add", telegram_chat_id="100", name="중복")
    assert resp.status_code == 303
    assert len(db.get_all_users()) == before


def test_add_user_without_telegram_id_stores_null(client, seeded, db):
    """이메일 전용 사용자 — telegram_chat_id 는 빈 문자열이 아니라 NULL 이어야 한다."""
    post(client, "/users/add", telegram_chat_id="", name="이메일만", email="only@example.com")
    added = next(u for u in db.get_all_users() if u["username"] == "이메일만")
    assert added["telegram_chat_id"] is None


def test_toggle_active_and_admin(client, seeded, db):
    uid = seeded["sub_id"]
    before = bool(db.get_user(uid)["is_active"])
    post(client, f"/users/{uid}/toggle")
    assert bool(db.get_user(uid)["is_active"]) is not before

    before_admin = bool(db.get_user(uid)["is_admin"])
    post(client, f"/users/{uid}/admin")
    assert bool(db.get_user(uid)["is_admin"]) is not before_admin


def test_delete_user(client, seeded, db):
    uid = seeded["sub_id"]
    post(client, f"/users/{uid}/delete")
    assert db.get_user(uid) is None


def test_update_email_empty_becomes_null(client, seeded, db):
    uid = seeded["admin_id"]
    post(client, f"/users/{uid}/email", email="  ")
    assert db.get_user(uid)["email"] is None

    post(client, f"/users/{uid}/email", email=" new@example.com ")
    assert db.get_user(uid)["email"] == "new@example.com"


# --- 키워드 (전송 대상을 가르는 값이라 특히 중요) ---------------------------

@pytest.mark.parametrize("raw,expected", [
    ("공룡 화석", ["공룡", "화석"]),
    ("  공룡   화석  ", ["공룡", "화석"]),
    ("*", None),        # * = 전체 수신
    ("", None),         # 빈 값도 전체 수신
    ("   ", None),
])
def test_keywords_parsing(client, seeded, db, raw, expected):
    """공백으로 쪼개고, `*`·빈 값은 NULL(=전체 수신). 이 규칙이 어긋나면 발송 대상이 바뀐다."""
    uid = seeded["sub_id"]
    post(client, f"/users/{uid}/keywords", keywords=raw)
    stored = db.get_user(uid)["keywords"]
    assert (json.loads(stored) if stored else None) == expected


def test_user_edit_updates_fields_and_keywords(client, seeded, db):
    uid = seeded["sub_id"]
    resp = post(client, f"/users/{uid}/edit",
                telegram_chat_id=" 999 ", username=" 바뀐이름 ", display_name="표시",
                email=" x@example.com ", keywords="암모나이트",
                is_active="true", is_admin="", notify_telegram="true", notify_email="")
    assert resp.status_code == 303 and resp.headers["location"] == f"/users/{uid}"

    u = db.get_user(uid)
    assert u["telegram_chat_id"] == "999"      # 앞뒤 공백 제거
    assert u["username"] == "바뀐이름"
    assert u["email"] == "x@example.com"
    assert json.loads(u["keywords"]) == ["암모나이트"]
    # 체크박스는 **꺼져 있으면 폼에 아예 안 실린다** → False 로 저장돼야 한다.
    assert bool(u["notify_email"]) is False
    assert bool(u["is_admin"]) is False
    assert bool(u["notify_telegram"]) is True


# --- 설정: 모델·provider (LLM 과금과 직결) ---------------------------------

def test_settings_models_update_writes_overlay(client, seeded, db):
    """`app_settings` overlay 는 provider·모델을 정한다 — provider 가 틀리면 과금 경로가 바뀐다."""
    resp = post(client, "/settings/models/update",
                llm_provider=" claude_code ", filter_model=" haiku-x ",
                summarizer_model="sonnet-y", chat_model="sonnet-z")
    assert resp.status_code == 303 and resp.headers["location"] == "/settings"

    s = db.get_all_settings()
    assert s["llm.provider"] == "claude_code"          # 공백 제거
    assert s["filter.llm_filter.model"] == "haiku-x"
    assert s["summarizer.model"] == "sonnet-y"
    assert s["chat.model"] == "sonnet-z"


# --- 설정: 피드 소스 -------------------------------------------------------

def test_add_feed(client, seeded, db):
    before = len(db.get_all_feeds())
    post(client, "/settings/sources/add", url="  https://example.com/new.xml  ")
    urls = [f["url"] for f in db.get_all_feeds()]
    assert len(urls) == before + 1
    assert "https://example.com/new.xml" in urls


def test_add_duplicate_feed_is_silently_ignored(client, seeded, db):
    """UNIQUE 위반을 삼킨다 — 에러 화면 대신 조용히 넘어가는 게 현행 동작."""
    before = len(db.get_all_feeds())
    resp = post(client, "/settings/sources/add", url="https://example.com/feed1.xml")
    assert resp.status_code == 303
    assert len(db.get_all_feeds()) == before


def test_add_empty_feed_is_noop(client, seeded, db):
    before = len(db.get_all_feeds())
    post(client, "/settings/sources/add", url="   ")
    assert len(db.get_all_feeds()) == before


def test_toggle_and_remove_feed(client, seeded, db):
    feed = db.get_all_feeds()[0]
    post(client, "/settings/sources/toggle", feed_id=feed["id"], is_active=0)
    assert not next(f for f in db.get_all_feeds() if f["id"] == feed["id"])["is_active"]

    post(client, "/settings/sources/remove", feed_id=feed["id"])
    assert feed["id"] not in [f["id"] for f in db.get_all_feeds()]


# --- 파이프라인 트리거 -----------------------------------------------------

def test_pipeline_status_shape(client, seeded):
    body = client.get("/pipeline/status").json()
    assert set(body) == {"running", "last_result"}


def test_pipeline_run_spawns_and_reports(client, seeded, monkeypatch):
    """실제 파이프라인은 돌리지 않는다(네트워크·LLM 과금). 스레드가 뜨고 상태가 갱신되는지만 본다."""
    import paleonews.__main__ as main_mod
    calls = []
    monkeypatch.setattr(main_mod, "_run_pipeline", lambda db, config: calls.append(True))

    resp = post(client, "/pipeline/run")
    assert resp.status_code == 303 and resp.headers["location"] == "/"

    import time
    for _ in range(50):
        if not client.get("/pipeline/status").json()["running"]:
            break
        time.sleep(0.05)
    status = client.get("/pipeline/status").json()
    assert calls == [True]
    assert status == {"running": False, "last_result": "success"}


def test_pipeline_run_rejects_concurrent(client, seeded, monkeypatch):
    """이미 돌고 있으면 409 — 두 번 눌러 파이프라인이 겹치면 LLM 비용이 두 배가 된다."""
    monkeypatch.setitem(__import__("paleonews.web", fromlist=["_pipeline_status"])._pipeline_status,
                        "running", True)
    resp = post(client, "/pipeline/run")
    assert resp.status_code == 409
    assert resp.json() == {"status": "already_running"}

"""웹 계층 테스트 공용 픽스처.

P08 §P2(Django 전환) 대비. Django 로 옮긴 뒤에도 **같은 테스트가 그대로 돌아야** 하므로
여기서 백엔드 의존을 격리한다(naverland 가 `params=["flask","django"]` 로 한 것과 같은 자리).
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paleonews import web
from paleonews.config import load_config
from paleonews.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db_dir(tmp_path, monkeypatch):
    """web.get_db() 가 임시 경로에 DB 를 만들게 한다.

    Database 를 여기서 만들어 주입하면 안 된다 — sqlite3 커넥션은 만든 스레드에서만 쓸 수 있는데
    TestClient 는 앱을 다른 스레드에서 돌린다. `_db` 를 비워 두고 **요청 스레드가 직접** 열게 한다.
    """
    monkeypatch.setattr(web, "_db", None)
    # **실제 config.yaml 을 읽는다** — 스텁으로 dict 를 지어내면 템플릿이 참조하는 키
    # (filter.llm_filter.model 등)가 빠져 화면이 죽고, 정작 그걸 테스트가 못 잡는다.
    # 여기서 바꾸는 건 DB 경로뿐이고 overlay 로직은 운영과 같은 것이 돈다.
    base_config = dict(load_config(str(REPO_ROOT / "config.yaml")))
    base_config["db_path"] = str(tmp_path / "paleonews.db")
    monkeypatch.setattr(web, "get_config_yaml_only", lambda: base_config)
    # 모델 카탈로그는 Anthropic API 를 친다 — 테스트가 네트워크·자격증명에 기대면 안 된다.
    # 운영에서도 실패 시 빈 목록으로 폴백하므로(자유 입력 UI) 그 경로를 고정한다.
    monkeypatch.setattr(web, "get_available_models", lambda: [])
    yield tmp_path
    # 닫지 않는다 — 커넥션은 앱 스레드가 열었으므로 여기서 close() 하면 같은 스레드 제약에 걸린다.
    # monkeypatch 가 `_db` 를 원복하고 tmp_path 는 지워지므로 새는 건 없다.


@pytest.fixture
def client(db_dir):
    with TestClient(web.app) as c:
        yield c


@pytest.fixture
def db(db_dir):
    """시드·검증용 **별도** DB 커넥션.

    ⚠️ 앱이 연 `web._db` 를 빌려 쓰면 안 된다 — TestClient 는 앱을 다른 스레드에서 돌리고
    sqlite3 커넥션은 만든 스레드에서만 쓸 수 있다. 같은 파일에 별도 커넥션을 연다.
    WAL 이라 이쪽에서 커밋한 것이 앱 쪽에도 곧바로 보인다.
    """
    conn = Database(str(db_dir / "paleonews.db"))
    conn.init_tables()
    yield conn
    conn.close()


@pytest.fixture
def sentinel(db_dir) -> Path:
    return db_dir / web.INTEGRITY_SENTINEL

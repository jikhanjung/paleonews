"""웹 계층 테스트 공용 픽스처.

`client` 는 **FastAPI 와 Django 양쪽**에 파라미터화돼 있다 — 같은 특성화 테스트가 두 구현에
그대로 적용되는 것이 P08 §P2 포팅의 패리티 증명이다(naverland §P1 과 같은 방식).
FastAPI 를 걷어낼 땐 `params` 에서 "fastapi" 를 빼면 된다.
"""
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paleonews import web
from paleonews.config import load_config
from paleonews.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def template_db(tmp_path_factory, django_ready):
    """모든 테이블(paleonews + Django auth/session)이 들어 있는 원본 DB. 세션당 1회.

    Django admin 로그인은 `auth_user`·`django_session` 을 요구하는데, `db.py:init_tables()` 는
    paleonews 표만 만든다. 테스트마다 migrate 를 돌리면 느리므로 **한 번 만들어 복사**한다.
    """
    from django.conf import settings as dj_settings
    from django.core.management import call_command
    from django.db import connections

    path = tmp_path_factory.mktemp("template") / "paleonews.db"
    base = Database(str(path))
    base.init_tables()
    base.close()

    conn = connections["default"]
    conn.close()
    saved = conn.settings_dict["NAME"]
    dj_settings.DATABASES["default"]["NAME"] = str(path)
    conn.settings_dict["NAME"] = str(path)
    try:
        call_command("migrate", "--fake-initial", verbosity=0, interactive=False)
    finally:
        conn.close()
        conn.settings_dict["NAME"] = saved
        dj_settings.DATABASES["default"]["NAME"] = saved
    return path


@pytest.fixture
def db_dir(tmp_path, monkeypatch, template_db):
    """앱이 임시 경로의 DB 를 쓰게 한다.

    Database 를 여기서 만들어 주입하면 안 된다 — sqlite3 커넥션은 만든 스레드에서만 쓸 수 있는데
    TestClient 는 앱을 다른 스레드에서 돌린다. `_db` 를 비워 두고 요청 스레드가 직접 열게 한다.
    """
    monkeypatch.setattr(web, "_db", None)
    # **실제 config.yaml 을 읽는다** — 스텁 dict 를 지어내면 템플릿이 참조하는 키가 빠져
    # 화면이 죽고, 정작 그걸 테스트가 못 잡는다. 바꾸는 건 DB 경로뿐이다.
    base_config = dict(load_config(str(REPO_ROOT / "config.yaml")))
    base_config["db_path"] = str(tmp_path / "paleonews.db")
    monkeypatch.setattr(web, "get_config_yaml_only", lambda: base_config)
    # 모델 카탈로그는 Anthropic API 를 친다 — 테스트가 네트워크·자격증명에 기대면 안 된다.
    monkeypatch.setattr(web, "get_available_models", lambda: [])
    shutil.copy(template_db, tmp_path / "paleonews.db")
    return tmp_path


@pytest.fixture
def db(db_dir):
    """시드·검증용 **별도** DB 커넥션(앱 스레드의 것을 빌려 쓸 수 없다)."""
    conn = Database(str(db_dir / "paleonews.db"))
    conn.init_tables()
    yield conn
    conn.close()


class Response:
    """FastAPI/Django 응답을 같은 모양으로 감싼다."""

    def __init__(self, status_code, text, headers, payload):
        self.status_code = status_code
        self.text = text
        self.headers = headers
        self._payload = payload

    def json(self):
        return self._payload


class Backend:
    def __init__(self, name, raw):
        self.name = name
        self.raw = raw

    def _wrap(self, resp):
        if self.name == "fastapi":
            text, headers = resp.text, {k.lower(): v for k, v in resp.headers.items()}
        else:
            text = resp.content.decode("utf-8", "replace") if resp.content else ""
            headers = {k.lower(): v for k, v in resp.items()}
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            payload = None
        return Response(resp.status_code, text, headers, payload)

    def get(self, path, follow_redirects=True):
        if self.name == "fastapi":
            return self._wrap(self.raw.get(path, follow_redirects=follow_redirects))
        return self._wrap(self.raw.get(path, follow=follow_redirects))

    def post(self, path, data=None, follow_redirects=True):
        data = data or {}
        if self.name == "fastapi":
            return self._wrap(self.raw.post(path, data=data, follow_redirects=follow_redirects))
        return self._wrap(self.raw.post(path, data=data, follow=follow_redirects))


@pytest.fixture(scope="session")
def django_ready():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()


@pytest.fixture(params=["fastapi", "django"])
def client(request, db_dir, django_ready):
    if request.param == "fastapi":
        with TestClient(web.app) as c:
            yield Backend("fastapi", c)
        return

    from django.conf import settings as dj_settings
    from django.db import connections
    from django.test import Client as DjangoClient

    conn = connections["default"]
    conn.close()
    saved = conn.settings_dict["NAME"]
    path = str(db_dir / "paleonews.db")
    dj_settings.DATABASES["default"]["NAME"] = path
    conn.settings_dict["NAME"] = path
    try:
        # 5화면은 FastAPI 시절과 같이 **열려 있다**(잠그는 건 별개 결정 — views.py docstring).
        # `/admin/` 만 로그인을 요구하고, 그건 test_admin.py 가 따로 본다.
        # `enforce_csrf_checks=True`: 기본값(False)이면 컨테이너에서만 403 이 나고 테스트는
        # 통과한다 — 실제로 그렇게 놓쳤다. 레거시 폼은 토큰 없이 통과해야 한다(csrf_exempt).
        yield Backend("django", DjangoClient(enforce_csrf_checks=True))
    finally:
        conn.close()
        conn.settings_dict["NAME"] = saved
        dj_settings.DATABASES["default"]["NAME"] = saved


@pytest.fixture
def pipeline_state(client):
    """백엔드가 실제로 쓰는 파이프라인 상태 dict — 두 구현이 각자 갖고 있다."""
    if client.name == "fastapi":
        return web._pipeline_status
    from news import views
    return views._pipeline_status


@pytest.fixture
def sentinel(db_dir) -> Path:
    return db_dir / web.INTEGRITY_SENTINEL

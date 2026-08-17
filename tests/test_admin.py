"""Django admin — 도입으로 생긴 것과 생기지 않은 것.

admin 은 P08 §4 결정으로 도입했다(운영자 UI + SaaS 문). 그 대가로 `auth_user`·`django_session`
이 생기고, `django_session` 은 bearer 토큰이라 **DB 사본이 호스트를 떠날 때 지워야 한다**
(계약 MUST) — 그 위생은 `tests/test_backup.py` 가 지킨다.

여기서 못박는 것: admin 은 로그인을 요구하고, **기존 5화면은 여전히 열려 있다**(인증 태세를
바꾸는 건 별개 결정 — `news/views.py` docstring).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("django_ready")


@pytest.fixture
def django_only(db_dir):
    """Django 백엔드 전용 클라이언트(파라미터화된 `client` 와 달리 한쪽만 본다)."""
    from django.conf import settings as dj_settings
    from django.db import connections
    from django.test import Client

    conn = connections["default"]
    conn.close()
    saved = conn.settings_dict["NAME"]
    path = str(db_dir / "paleonews.db")
    dj_settings.DATABASES["default"]["NAME"] = path
    conn.settings_dict["NAME"] = path
    try:
        yield Client()
    finally:
        conn.close()
        conn.settings_dict["NAME"] = saved
        dj_settings.DATABASES["default"]["NAME"] = saved


def test_admin_requires_login(django_only):
    resp = django_only.get("/admin/")
    assert resp.status_code == 302
    assert "/admin/login/" in resp["Location"]


def test_admin_login_page_renders(django_only):
    assert django_only.get("/admin/login/").status_code == 200


def test_legacy_screens_are_not_gated(django_only):
    """기존 5화면은 **열려 있어야 한다** — 포팅이 인증 태세를 바꾸면 안 된다.

    잠그는 순간 슈퍼유저를 만들기 전까지 운영자가 UI 에서 잠긴다. 그건 배포 절차가 바뀌는
    별개 결정이라 이 포팅에 끼워 넣지 않는다.
    """
    for path in ("/", "/articles", "/users", "/settings", "/healthz"):
        assert django_only.get(path).status_code == 200, f"{path} 가 잠겼다"


def test_admin_lists_registered_models(django_only):
    """운영자가 로그인하면 밑바닥 조회가 생긴다 — 전용 화면에 없던 부분."""
    from django.contrib.auth.models import User

    operator = User.objects.create_superuser("operator", password="x" * 20)
    django_only.force_login(operator)

    body = django_only.get("/admin/").content.decode()
    for label in ("Article", "Subscriber", "Dispatch", "Feed", "Pipeline run", "App setting"):
        assert label in body, f"admin 에 {label} 이 안 보인다"

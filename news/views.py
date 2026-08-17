"""관리 UI 뷰 — FastAPI `paleonews/web.py` 에서 포팅 (P08 §P2).

포팅 원칙: **응답과 DB 상태가 달라지면 안 된다**(`tests/test_web_characterization.py` 가 게이트).
템플릿은 Jinja2 그대로 재사용하고(설정의 Jinja2 백엔드), 컨텍스트 키도 그대로 넘긴다.

Django admin 은 모델 CRUD 를 덮지만 **이 화면들은 덮지 못한다**(P06 보류 사유 ③):
파이프라인 실행 버튼·상태 폴링, provider·모델 드롭다운(`app_settings` overlay),
사용자별 키워드 편집. 그래서 전용 뷰로 남는다.

## 인증: 이 화면들은 **잠그지 않는다**

`/admin/` 은 Django 로그인을 요구하지만 아래 5화면은 FastAPI 시절과 똑같이 열려 있다.
nginx 뒤 사설망이고, **인증 태세를 바꾸는 건 "admin 도입"과 다른 결정**이라 포팅에 끼워 넣지
않는다(끼워 넣으면 슈퍼유저를 만들기 전까지 운영자가 UI 에서 잠긴다).
잠그려면 각 뷰에 `@login_required` 한 줄이면 된다 — 그때는 슈퍼유저 생성이 배포 절차에 들어간다.

## CSRF: 레거시 폼은 면제한다

FastAPI 시절엔 CSRF 보호가 없었고 템플릿에도 토큰 필드가 없다. `CsrfViewMiddleware` 는
**admin 이 요구해서** 싣지만, 그대로 두면 기존 폼 POST 가 전부 403 이 된다(실측).
그래서 레거시 POST 뷰만 `@csrf_exempt` 로 면제한다 — admin 은 보호를 그대로 받는다.
토큰을 붙이려면 템플릿 5개를 손봐야 하는데, 그건 인증 태세 변경과 함께 갈 별개 작업이다.
"""
from __future__ import annotations

import json
import logging
import threading

from django.conf import settings as dj_settings
from django.db import connection
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from paleonews.config import apply_settings_overlay, load_config

from .models import AppSetting, Article, Dispatch, Feed, PipelineRun, Subscriber

logger = logging.getLogger(__name__)


class SeeOther(HttpResponseRedirect):
    """303 See Other.

    Django 의 `redirect()` 는 **302** 를 내지만 FastAPI 쪽은 전부 303 이었다. 폼 POST 뒤
    302 는 메서드 유지가 구현에 따라 갈리고 303 은 GET 을 강제한다 — 브라우저 동작이 달라지므로
    그대로 맞춘다.
    """
    status_code = 303

# 파이프라인 실행 상태 — 프로세스 로컬. gunicorn worker 1개 전제(entrypoint 참조).
_pipeline_status = {"running": False, "last_result": None}


def now_iso() -> str:
    """DB 의 시각은 전부 UTC ISO 문자열이다 — CLI(`db.py`)와 같은 형식으로 쓴다."""
    from datetime import datetime, timezone as tz
    return datetime.now(tz.utc).isoformat()


def get_config() -> dict:
    """yaml 설정 위에 DB overlay 를 얹는다. **매 요청 재구성** — UI 변경이 즉시 반영돼야 한다."""
    yaml_cfg = load_config(str(dj_settings.BASE_DIR / "config.yaml"))
    overrides = {s.key: s.value for s in AppSetting.objects.all()}
    return apply_settings_overlay(yaml_cfg, overrides)


def get_available_models() -> list[dict]:
    """Anthropic 모델 카탈로그(1시간 캐시). 실패하면 빈 목록 — UI 가 자유 입력으로 폴백한다."""
    global _models_cache
    import time
    if _models_cache and time.time() - _models_cache[0] < 3600:
        return _models_cache[1]
    try:
        from anthropic import Anthropic
        result = Anthropic().models.list(limit=50)
        models = [{"id": m.id, "display_name": m.display_name} for m in result.data]
        _models_cache = (time.time(), models)
        return models
    except Exception as e:
        logger.warning("Failed to fetch model catalogue: %s", e)
        return []


_models_cache: tuple[float, list[dict]] | None = None


# --- 대시보드 -------------------------------------------------------------

def dashboard(request):
    users = _users_with_extras()
    return render(request, "dashboard.html", {
        "stats": _stats(),
        "users": users,
        "runs": _recent_runs(5),
        "active_users": sum(1 for u in users if u["is_active"]),
        "source_stats": _source_stats(),
        "pipeline_status": _pipeline_status,
    })


def _stats() -> dict:
    return {
        "total": Article.objects.count(),
        "relevant": Article.objects.filter(is_relevant=True).count(),
        "summarized": Article.objects.exclude(summary_ko=None).count(),
        "sent": Dispatch.objects.filter(status="success").values("article_id").distinct().count(),
    }


def _source_stats() -> list[dict]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT source, COUNT(*) AS total, "
            "       SUM(CASE WHEN is_relevant = 1 THEN 1 ELSE 0 END) AS relevant "
            "  FROM articles WHERE source IS NOT NULL GROUP BY source ORDER BY total DESC")
        return [{"source": r[0], "total": r[1], "relevant": r[2]} for r in cur.fetchall()]


def _recent_runs(limit: int) -> list[dict]:
    return list(PipelineRun.objects.order_by("-id").values()[:limit])


# --- 기사 -----------------------------------------------------------------

def articles_list(request):
    q = request.GET.get("q", "")
    status = request.GET.get("status", "all")
    page = max(1, _int(request.GET.get("page"), 1))
    per_page = min(100, max(10, _int(request.GET.get("per_page"), 30)))

    qs = Article.objects.all()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(title__contains=q) | Q(title_ko__contains=q) | Q(source__contains=q))
    if status == "relevant":
        qs = qs.filter(is_relevant=True)
    elif status == "summarized":
        qs = qs.exclude(summary_ko=None)
    elif status == "sent":
        qs = qs.filter(id__in=Dispatch.objects.filter(status="success").values("article_id"))

    total = qs.count()
    offset = (page - 1) * per_page
    articles = list(qs.order_by("-id").values()[offset:offset + per_page])
    return render(request, "articles.html", {
        "articles": articles, "q": q, "page": page, "per_page": per_page,
        "total": total, "total_pages": max(1, (total + per_page - 1) // per_page),
        "status_filter": status,
    })


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --- 사용자 ---------------------------------------------------------------

def _users_with_extras() -> list[dict]:
    users = list(Subscriber.objects.order_by("id").values())
    for u in users:
        u["keywords_list"] = json.loads(u["keywords"]) if u["keywords"] else None
        u["memories"] = list(
            Subscriber.objects.get(pk=u["id"]).memory_set.order_by("-id").values())
    return users


def users_list(request):
    return render(request, "users.html", {"users": _users_with_extras()})


def user_detail(request, user_id: int):
    user = Subscriber.objects.filter(pk=user_id).values().first()
    if not user:
        return SeeOther("/users")
    user["keywords_list"] = json.loads(user["keywords"]) if user["keywords"] else None
    user["memories"] = list(
        Subscriber.objects.get(pk=user_id).memory_set.order_by("-id").values())
    dispatches = list(
        Dispatch.objects.filter(user_id=user_id).order_by("-sent_at").values()[:20])
    return render(request, "user_detail.html", {"user": user, "dispatches": dispatches})


@csrf_exempt
@require_POST
def users_add(request):
    tg_id = request.POST.get("telegram_chat_id", "").strip() or None
    name = request.POST.get("name", "")
    email = request.POST.get("email", "")
    if tg_id and Subscriber.objects.filter(telegram_chat_id=tg_id).exists():
        # 중복은 **에러가 아니라 무시**하고 목록으로 — FastAPI 시절과 같다.
        return SeeOther("/users")
    now = now_iso()
    Subscriber.objects.create(
        telegram_chat_id=tg_id, username=name or None, display_name=name or None,
        email=email or None, is_admin=_checkbox(request, "is_admin"),
        created_at=now, updated_at=now)
    return SeeOther("/users")


@csrf_exempt
@require_POST
def user_edit(request, user_id: int):
    user = Subscriber.objects.filter(pk=user_id).first()
    if not user:
        return SeeOther("/users")
    user.telegram_chat_id = request.POST.get("telegram_chat_id", "").strip() or None
    user.username = request.POST.get("username", "").strip() or None
    user.display_name = request.POST.get("display_name", "").strip() or None
    user.email = request.POST.get("email", "").strip() or None
    user.is_active = _checkbox(request, "is_active")
    user.is_admin = _checkbox(request, "is_admin")
    user.notify_telegram = _checkbox(request, "notify_telegram")
    user.notify_email = _checkbox(request, "notify_email")
    user.keywords = _parse_keywords(request.POST.get("keywords", ""))
    user.updated_at = now_iso()
    user.save()
    return SeeOther(f"/users/{user_id}")


@csrf_exempt
@require_POST
def users_toggle(request, user_id: int):
    user = Subscriber.objects.filter(pk=user_id).first()
    if user:
        user.is_active = not user.is_active
        user.updated_at = now_iso()
        user.save(update_fields=["is_active", "updated_at"])
    return SeeOther("/users")


@csrf_exempt
@require_POST
def users_keywords(request, user_id: int):
    Subscriber.objects.filter(pk=user_id).update(
        keywords=_parse_keywords(request.POST.get("keywords", "")), updated_at=now_iso())
    return SeeOther("/users")


@csrf_exempt
@require_POST
def users_email(request, user_id: int):
    Subscriber.objects.filter(pk=user_id).update(
        email=request.POST.get("email", "").strip() or None, updated_at=now_iso())
    return SeeOther("/users")


@csrf_exempt
@require_POST
def users_delete(request, user_id: int):
    # `Dispatch.user` 가 SET_NULL 이라 발송 이력은 남고 링크만 끊긴다 — FastAPI 시절엔
    # 이력이 있는 사용자를 지우면 FK 제약에 걸려 **실패했다**(의도한 동작 변경).
    Subscriber.objects.filter(pk=user_id).delete()
    return SeeOther("/users")


@csrf_exempt
@require_POST
def users_toggle_admin(request, user_id: int):
    user = Subscriber.objects.filter(pk=user_id).first()
    if user:
        user.is_admin = not user.is_admin
        user.save(update_fields=["is_admin"])
    return SeeOther("/users")


def _checkbox(request, name: str) -> bool:
    """체크박스는 **꺼져 있으면 폼에 아예 안 실린다** → 부재 = False."""
    return request.POST.get(name, "") not in ("", "false", "False", "0")


def _parse_keywords(raw: str) -> str | None:
    """공백으로 쪼갠 JSON 배열. `*`·빈 값은 **NULL = 전체 수신**.

    이 규칙이 어긋나면 발송 대상이 통째로 바뀐다.
    """
    kw = raw.strip()
    if not kw or kw == "*":
        return None
    return json.dumps([k.strip() for k in kw.split() if k.strip()], ensure_ascii=False)


# --- 설정 -----------------------------------------------------------------

def settings_page(request):
    return render(request, "settings.html", {
        "config": get_config(),
        "feeds": list(Feed.objects.order_by("id").values()),
        "available_models": get_available_models(),
    })


@csrf_exempt
@require_POST
def settings_models_update(request):
    """provider·모델 overlay. ⚠️ `llm.provider` 값이 구독 과금 경로를 정한다."""
    for key, field in (("llm.provider", "llm_provider"),
                       ("filter.llm_filter.model", "filter_model"),
                       ("summarizer.model", "summarizer_model"),
                       ("chat.model", "chat_model")):
        AppSetting.objects.update_or_create(
            key=key,
            defaults={"value": request.POST.get(field, "").strip(), "updated_at": now_iso()})
    return SeeOther("/settings")


@csrf_exempt
@require_POST
def sources_add(request):
    url = request.POST.get("url", "").strip()
    if url:
        now = now_iso()
        # 중복 URL 은 조용히 무시 — FastAPI 시절 IntegrityError 를 삼키던 동작과 같다.
        Feed.objects.get_or_create(
            url=url, defaults={"is_active": True, "created_at": now, "updated_at": now})
    return SeeOther("/settings")


@csrf_exempt
@require_POST
def sources_remove(request):
    Feed.objects.filter(pk=_int(request.POST.get("feed_id"), 0)).delete()
    return SeeOther("/settings")


@csrf_exempt
@require_POST
def sources_toggle(request):
    Feed.objects.filter(pk=_int(request.POST.get("feed_id"), 0)).update(
        is_active=bool(_int(request.POST.get("is_active"), 0)), updated_at=now_iso())
    return SeeOther("/settings")


# --- 파이프라인 -----------------------------------------------------------

@csrf_exempt
@require_POST
def pipeline_run(request):
    if _pipeline_status["running"]:
        # 두 번 눌러 파이프라인이 겹치면 LLM 비용이 두 배가 된다.
        return JsonResponse({"status": "already_running"}, status=409)

    _pipeline_status["running"] = True
    _pipeline_status["last_result"] = None

    def run():
        try:
            from paleonews.__main__ import _run_pipeline
            from paleonews.db import Database
            config = get_config()
            db = Database(config.get("db_path", "paleonews.db"))
            db.init_tables()
            try:
                _run_pipeline(db, config)
                _pipeline_status["last_result"] = "success"
            finally:
                db.close()
        except Exception as e:
            logger.exception("Pipeline execution failed")
            _pipeline_status["last_result"] = f"error: {e}"
        finally:
            _pipeline_status["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return SeeOther("/")


def pipeline_status(request):
    return JsonResponse(_pipeline_status)


# --- 헬스체크 (인증 없음 — smoke 가 소비한다) -----------------------------

INTEGRITY_SENTINEL = "INTEGRITY_FAIL"


def _integrity_sentinel() -> str | None:
    """backup_db.py 가 DB 옆에 남긴 손상 플래그의 첫 줄. 아무도 안 읽으면 무의미하다."""
    import os
    db_path = dj_settings.DATABASES["default"]["NAME"]
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(db_path)), INTEGRITY_SENTINEL),
                  encoding="utf-8") as f:
            return f.readline().strip() or None
    except OSError:
        return None


def healthz(request):
    from paleonews.web import _app_version
    payload = {"status": "ok", "version": _app_version(), "db": False, "counts": {}}
    try:
        payload["counts"] = {
            "articles": Article.objects.count(),
            "feeds": Feed.objects.count(),
            "users": Subscriber.objects.count(),
        }
        payload["db"] = True
    except Exception as e:
        logger.exception("healthz DB check failed")
        payload["status"] = "error"
        payload["error"] = str(e)
        return JsonResponse(payload, status=503)

    if sentinel := _integrity_sentinel():
        payload["status"] = "degraded"
        payload["integrity"] = sentinel
    return JsonResponse(payload)

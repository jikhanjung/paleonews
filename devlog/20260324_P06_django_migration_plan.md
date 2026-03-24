# Phase 6: Django 전환 계획

**날짜**: 2026-03-24
**선행**: Phase 5 완료 (챗봇, 웹 Admin UI, Docker 배포)

## 목표

현재 FastAPI + 직접 SQL 기반 시스템을 Django로 전환하여:
- ORM + 자동 마이그레이션으로 DB 관리 단순화
- Django Admin으로 웹 UI 코드 대폭 축소
- 인증/권한 시스템 내장
- management commands로 CLI 체계화

## 현재 코드 규모

| 모듈 | 줄 수 | Django 전환 후 |
|------|-------|---------------|
| `db.py` (수동 SQL) | 432 | **삭제** → models.py ~100줄 |
| `web.py` (FastAPI) | 261 | **삭제** → admin.py ~60줄 |
| `templates/` (5개 파일) | 502 | **삭제** → Django Admin 기본 제공 |
| `__main__.py` (CLI+파이프라인) | 603 | **분리** → management commands ~300줄 |
| `config.py` | 16 | **삭제** → Django settings.py |
| `fetcher.py` | 85 | 그대로 유지 |
| `filter.py` | 96 | 그대로 유지 |
| `crawler.py` | 69 | 그대로 유지 |
| `summarizer.py` | 97 | 그대로 유지 |
| `llm.py` | 59 | 그대로 유지 |
| `bot.py` | 270 | 약간 수정 (DB 접근을 ORM으로) |
| `dispatcher/*` | 235 | 약간 수정 (DB 접근을 ORM으로) |

**삭제되는 코드**: ~1,211줄 (db.py + web.py + templates + config.py)
**새로 작성하는 코드**: ~500줄 (models.py + admin.py + settings.py + management commands)
**순 감소**: ~700줄

---

## 디렉토리 구조

```
paleonews/                          # Django 프로젝트 루트
├── manage.py
├── config.yaml                     # 파이프라인 설정 (Django 설정과 분리)
├── sources.txt
├── .env
│
├── paleonews/                      # Django 프로젝트 설정
│   ├── __init__.py
│   ├── settings.py                 # DB, 로깅, 인증, installed_apps
│   ├── urls.py                     # admin + API URL 라우팅
│   └── wsgi.py
│
├── articles/                       # 기사 앱
│   ├── __init__.py
│   ├── models.py                   # Article, PipelineRun
│   ├── admin.py                    # 기사 목록, 검색, 필터
│   └── management/
│       └── commands/
│           ├── fetch.py            # RSS 수집
│           ├── filter_articles.py  # 필터링
│           ├── crawl.py            # 본문 크롤링
│           ├── summarize.py        # 한국어 요약
│           ├── send.py             # 다중 채널 전송
│           ├── run_pipeline.py     # 전체 파이프라인
│           └── status.py           # DB 통계
│
├── users/                          # 사용자 앱
│   ├── __init__.py
│   ├── models.py                   # Subscriber, Memory, Dispatch
│   └── admin.py                    # 사용자 관리, 키워드, 메모리
│
├── bot/                            # Telegram 봇 앱
│   ├── __init__.py
│   ├── bot.py                      # 봇 로직 (기존과 거의 동일)
│   └── management/
│       └── commands/
│           └── run_bot.py          # 봇 데몬
│
├── pipeline/                       # 파이프라인 공통 모듈 (앱 아님)
│   ├── __init__.py
│   ├── fetcher.py                  # 기존과 동일
│   ├── filter.py                   # 기존과 동일
│   ├── crawler.py                  # 기존과 동일
│   ├── summarizer.py               # 기존과 동일
│   └── llm.py                      # 기존과 동일
│
├── dispatcher/                     # 전송 모듈 (앱 아님)
│   ├── __init__.py
│   ├── base.py
│   ├── telegram.py
│   ├── email.py
│   └── webhook.py
│
├── deploy/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── entrypoint.sh
│
└── tests/
    ├── test_models.py
    ├── test_filter.py
    └── test_fetcher.py
```

---

## Step 1: Django 프로젝트 초기 셋업

### 1.1 의존성 변경

**pyproject.toml 수정:**

```toml
dependencies = [
    # 기존 유지
    "feedparser",
    "httpx",
    "anthropic",
    "openai",
    "python-telegram-bot",
    "pyyaml",
    "python-dotenv",
    "readability-lxml",
    # FastAPI 관련 제거 → Django 추가
    "django>=5.1",
    "gunicorn",           # 프로덕션 WSGI 서버
]
```

**제거하는 의존성**: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`
**추가하는 의존성**: `django`, `gunicorn`

### 1.2 settings.py

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "articles",
    "users",
    "bot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "paleonews.urls"
WSGI_APPLICATION = "paleonews.wsgi.application"

# SQLite (기존 DB 경로 유지)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DB_PATH", BASE_DIR / "paleonews.db"),
        "OPTIONS": {
            "timeout": 5,           # busy_timeout=5000ms 대응
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;",
        },
    }
}

# config.yaml 로딩 (파이프라인 설정)
import yaml
_config_path = os.environ.get("CONFIG_PATH", BASE_DIR / "config.yaml")
with open(_config_path) as f:
    PIPELINE_CONFIG = yaml.safe_load(f)

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 로깅 (기존 config.yaml 설정 반영)
_log_cfg = PIPELINE_CONFIG.get("logging", {})
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": _log_cfg.get("file", "logs/paleonews.log"),
            "maxBytes": _log_cfg.get("max_bytes", 5242880),
            "backupCount": _log_cfg.get("backup_count", 3),
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": _log_cfg.get("level", "INFO"),
    },
}
```

### 1.3 urls.py

```python
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]

admin.site.site_header = "PaleoNews 관리"
admin.site.site_title = "PaleoNews"
admin.site.index_title = "대시보드"
```

---

## Step 2: 모델 정의

### 2.1 articles/models.py

```python
from django.db import models


class Article(models.Model):
    url = models.URLField(unique=True)
    title = models.TextField()
    summary = models.TextField(blank=True, null=True)
    source = models.CharField(max_length=200, blank=True, null=True)
    feed_url = models.URLField(blank=True, null=True)
    published = models.DateTimeField(blank=True, null=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    is_relevant = models.BooleanField(null=True, default=None)
    body = models.TextField(blank=True, null=True)
    title_ko = models.TextField(blank=True, null=True)
    summary_ko = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.title_ko or self.title

    @property
    def is_summarized(self):
        return self.summary_ko is not None


class PipelineRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "실행 중"
        SUCCESS = "success", "성공"
        ERROR = "error", "오류"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    fetched = models.IntegerField(default=0)
    new_articles = models.IntegerField(default=0)
    relevant = models.IntegerField(default=0)
    crawled = models.IntegerField(default=0)
    summarized = models.IntegerField(default=0)
    sent = models.IntegerField(default=0)
    errors = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"Run #{self.id} ({self.status}) - {self.started_at:%Y-%m-%d %H:%M}"
```

### 2.2 users/models.py

```python
from django.db import models


class Subscriber(models.Model):
    """Telegram/Email 구독자. Django auth User와 분리 — 봇 사용자는 Django 로그인 불필요."""
    chat_id = models.CharField(max_length=64, unique=True)
    username = models.CharField(max_length=100, blank=True, null=True)
    display_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)
    keywords = models.JSONField(blank=True, null=True, help_text="키워드 목록. null=전체 수신")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.display_name or self.chat_id}"

    @property
    def keywords_display(self):
        if self.keywords is None:
            return "전체 수신"
        return ", ".join(self.keywords)


class Dispatch(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "성공"
        FAILED = "failed", "실패"
        FILTERED = "filtered", "필터됨"

    article = models.ForeignKey("articles.Article", on_delete=models.CASCADE, related_name="dispatches")
    subscriber = models.ForeignKey(Subscriber, on_delete=models.SET_NULL, null=True, blank=True, related_name="dispatches")
    channel = models.CharField(max_length=20)  # telegram, email, slack, discord
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.channel} → {self.subscriber} ({self.status})"


class Memory(models.Model):
    subscriber = models.ForeignKey(Subscriber, on_delete=models.CASCADE, related_name="memories")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "memories"

    def __str__(self):
        return self.content[:50]
```

---

## Step 3: Django Admin 설정

### 3.1 articles/admin.py

```python
from django.contrib import admin
from .models import Article, PipelineRun


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["id", "title_short", "source", "is_relevant", "is_summarized_icon", "fetched_at"]
    list_filter = ["is_relevant", "source"]
    search_fields = ["title", "title_ko", "source", "url"]
    readonly_fields = ["url", "fetched_at"]
    list_per_page = 30

    @admin.display(description="제목")
    def title_short(self, obj):
        title = obj.title_ko or obj.title
        return title[:60] + "..." if len(title) > 60 else title

    @admin.display(boolean=True, description="요약")
    def is_summarized_icon(self, obj):
        return obj.summary_ko is not None


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ["id", "started_at", "status", "fetched", "new_articles",
                     "relevant", "crawled", "summarized", "sent"]
    list_filter = ["status"]
    readonly_fields = ["started_at", "finished_at", "errors"]
```

### 3.2 users/admin.py

```python
from django.contrib import admin
from .models import Subscriber, Dispatch, Memory


class MemoryInline(admin.TabularInline):
    model = Memory
    extra = 0
    readonly_fields = ["content", "created_at"]


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ["id", "chat_id", "display_name", "email", "is_active",
                     "is_admin", "keywords_display", "created_at"]
    list_filter = ["is_active", "is_admin"]
    search_fields = ["chat_id", "display_name", "email"]
    list_editable = ["is_active", "is_admin"]
    inlines = [MemoryInline]


@admin.register(Dispatch)
class DispatchAdmin(admin.ModelAdmin):
    list_display = ["id", "article", "subscriber", "channel", "status", "sent_at"]
    list_filter = ["channel", "status"]
    raw_id_fields = ["article", "subscriber"]
```

**현재 web.py + 5개 템플릿 (763줄)이 위 admin.py 2개 (약 60줄)로 대체됨.**

Django Admin이 기본 제공하는 것:
- 기사 목록 + 검색 + 필터링 + 페이지네이션
- 사용자 CRUD + 인라인 메모리 관리
- 파이프라인 실행 이력 조회
- 전송 내역 조회
- 로그인 인증 (현재 시스템에는 없던 기능)

---

## Step 4: Management Commands

기존 `__main__.py`의 커맨드를 Django management commands로 전환.

### 4.1 공통 헬퍼

`articles/management/commands/_base.py` (선택적):
```python
# config.yaml 로딩은 django.conf.settings.PIPELINE_CONFIG 으로 접근
```

### 4.2 커맨드 매핑

| 기존 명령어 | Django 명령어 | 비고 |
|------------|--------------|------|
| `paleonews run` | `manage.py run_pipeline` | 전체 파이프라인 |
| `paleonews fetch` | `manage.py fetch` | RSS 수집 |
| `paleonews filter` | `manage.py filter_articles` | `filter`는 예약어라 이름 변경 |
| `paleonews crawl` | `manage.py crawl` | 본문 크롤링 |
| `paleonews summarize` | `manage.py summarize` | 요약 |
| `paleonews send` | `manage.py send` | 전송 |
| `paleonews status` | `manage.py status` | 통계 (또는 Admin에서 확인) |
| `paleonews bot` | `manage.py run_bot` | Telegram 봇 데몬 |
| `paleonews users *` | Django Admin UI | CLI 불필요 |
| `paleonews sources *` | Django Admin 또는 management command | |
| `paleonews web` | `manage.py runserver` (개발) / `gunicorn` (프로덕션) | |

### 4.3 fetch 커맨드 예시

```python
# articles/management/commands/fetch.py
from django.core.management.base import BaseCommand
from django.conf import settings

from articles.models import Article
from pipeline.fetcher import fetch_all, load_sources


class Command(BaseCommand):
    help = "RSS 피드에서 기사 수집"

    def handle(self, *args, **options):
        config = settings.PIPELINE_CONFIG
        sources = load_sources(config["sources_file"])
        fetched_articles = fetch_all(sources)

        inserted = 0
        for a in fetched_articles:
            _, created = Article.objects.get_or_create(
                url=a.url,
                defaults={
                    "title": a.title,
                    "summary": a.summary,
                    "source": a.source,
                    "feed_url": a.feed_url,
                    "published": a.published,
                },
            )
            if created:
                inserted += 1

        self.stdout.write(f"수집: {len(fetched_articles)}건, 신규: {inserted}건")
```

### 4.4 run_pipeline 커맨드

```python
# articles/management/commands/run_pipeline.py
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from articles.models import PipelineRun


class Command(BaseCommand):
    help = "전체 파이프라인 실행 (fetch → filter → crawl → summarize → send)"

    def handle(self, *args, **options):
        run = PipelineRun.objects.create()
        errors = []

        steps = [
            ("1/5 RSS 피드 수집", "fetch"),
            ("2/5 필터링", "filter_articles"),
            ("3/5 본문 크롤링", "crawl"),
            ("4/5 한국어 요약", "summarize"),
            ("5/5 전송", "send"),
        ]

        for label, cmd in steps:
            self.stdout.write(f"\n=== {label} ===")
            try:
                call_command(cmd)
            except Exception as e:
                errors.append(f"{label} 실패: {e}")

        run.finished_at = timezone.now()
        run.status = "error" if errors else "success"
        if errors:
            run.errors = "\n".join(errors)
        run.save()

        if errors:
            self.stderr.write(f"\n⚠️ {len(errors)}건의 오류 발생")
```

### 4.5 run_bot 커맨드

```python
# bot/management/commands/run_bot.py
from django.core.management.base import BaseCommand
from bot.bot import run_bot


class Command(BaseCommand):
    help = "Telegram 봇 데몬 실행"

    def handle(self, *args, **options):
        run_bot()
```

---

## Step 5: 파이프라인 로직 이식

### 5.1 변경 없는 모듈 (pipeline/ 디렉토리로 이동)

다음 모듈은 DB에 직접 접근하지 않으므로 **코드 변경 없이** 이동만:

| 모듈 | 변경 사항 |
|------|----------|
| `fetcher.py` | 없음. Article dataclass + feedparser 로직 그대로 |
| `crawler.py` | 없음. httpx + readability 로직 그대로 |
| `summarizer.py` | 없음. Claude API 호출 + 파싱 그대로 |
| `llm.py` | 없음. LLM 클라이언트 추상화 그대로 |

### 5.2 수정이 필요한 모듈

**filter.py**: `db` 파라미터 대신 ORM 쿼리셋 사용

```python
# 기존: filter_articles(db, config, llm_client=None)
# 변경: filter_articles(config, llm_client=None)
#   내부에서 Article.objects.filter(is_relevant=None) 사용
```

**dispatcher/telegram.py, email.py, webhook.py**: 변경 없음 (DB 접근 안 함)

**bot.py**: `Database` 클래스 대신 Django ORM 사용
- `db.get_user_by_chat_id(chat_id)` → `Subscriber.objects.filter(chat_id=chat_id).first()`
- `db.save_memory(user_id, content)` → `Memory.objects.create(subscriber=subscriber, content=content)`
- 기타 CRUD도 동일 패턴

### 5.3 변환 패턴 요약

| 기존 (db.py 직접 SQL) | Django ORM |
|----------------------|------------|
| `db.save_articles(articles)` | `Article.objects.get_or_create(url=...)` |
| `db.get_unfiltered()` | `Article.objects.filter(is_relevant=None)` |
| `db.mark_relevant(id, True)` | `article.is_relevant = True; article.save()` |
| `db.get_unsummarized()` | `Article.objects.filter(is_relevant=True, summary_ko=None)` |
| `db.save_summary(id, t, s)` | `article.title_ko = t; article.summary_ko = s; article.save()` |
| `db.get_uncrawled()` | `Article.objects.filter(is_relevant=True, body=None)` |
| `db.get_unsent_for_user(ch, uid)` | `Article.objects.filter(...).exclude(dispatches__channel=ch, dispatches__subscriber_id=uid, dispatches__status="success")` |
| `db.record_dispatch(...)` | `Dispatch.objects.create(...)` |
| `db.get_stats()` | `Article.objects.aggregate(...)` |

---

## Step 6: 기존 DB 데이터 마이그레이션

기존 SQLite DB의 데이터를 Django 스키마로 옮기는 작업.

### 6.1 전략: 커스텀 마이그레이션

Django의 `RunPython` 마이그레이션으로 기존 테이블 데이터를 새 테이블로 복사.

```python
# articles/migrations/0002_import_legacy_data.py
import sqlite3
from django.db import migrations

def import_legacy(apps, schema_editor):
    """기존 paleonews.db에서 데이터 임포트."""
    import os
    legacy_path = os.environ.get("LEGACY_DB_PATH")
    if not legacy_path or not os.path.exists(legacy_path):
        return

    Article = apps.get_model("articles", "Article")
    PipelineRun = apps.get_model("articles", "PipelineRun")
    Subscriber = apps.get_model("users", "Subscriber")
    Dispatch = apps.get_model("users", "Dispatch")
    Memory = apps.get_model("users", "Memory")

    conn = sqlite3.connect(legacy_path)
    conn.row_factory = sqlite3.Row

    # Articles
    for row in conn.execute("SELECT * FROM articles"):
        Article.objects.get_or_create(url=row["url"], defaults={...})

    # Users → Subscribers
    for row in conn.execute("SELECT * FROM users"):
        Subscriber.objects.get_or_create(chat_id=row["chat_id"], defaults={...})

    # Dispatches, Memories, PipelineRuns 도 동일 패턴
    conn.close()

class Migration(migrations.Migration):
    dependencies = [("articles", "0001_initial"), ("users", "0001_initial")]
    operations = [migrations.RunPython(import_legacy, migrations.RunPython.noop)]
```

### 6.2 실행 순서

```bash
# 1. 기존 DB 백업
cp paleonews.db paleonews.db.backup

# 2. Django 마이그레이션 실행 (새 스키마 생성)
python manage.py migrate

# 3. 레거시 데이터 임포트
LEGACY_DB_PATH=paleonews.db.backup python manage.py migrate articles 0002

# 4. Django 슈퍼유저 생성 (Admin 로그인용)
python manage.py createsuperuser
```

---

## Step 7: Docker 설정 업데이트

### 7.1 Dockerfile

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt1-dev cron && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

# Static files
RUN python manage.py collectstatic --noinput

VOLUME ["/app/data", "/app/logs"]
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
```

### 7.2 docker-compose.yml

```yaml
services:
  web:
    build: .
    command: ["web"]               # gunicorn
    ports:
      - "${WEB_PORT:-8000}:8000"
    env_file: .env
    volumes:
      - data:/app/data
      - logs:/app/logs

  pipeline:
    build: .
    command: ["cron"]              # cron으로 manage.py run_pipeline 실행
    env_file: .env
    volumes:
      - data:/app/data
      - logs:/app/logs

  bot:
    build: .
    command: ["bot"]               # manage.py run_bot
    env_file: .env
    volumes:
      - data:/app/data
      - logs:/app/logs

volumes:
  data:
    driver: local
    driver_opts:
      device: ${DATA_DIR:-/srv/paleonews/data}
      type: none
      o: bind
  logs:
    driver: local
    driver_opts:
      device: ${LOG_DIR:-/srv/paleonews/logs}
      type: none
      o: bind
```

### 7.3 entrypoint.sh 변경

```bash
#!/bin/bash
set -e

# DB 마이그레이션 자동 실행
python manage.py migrate --noinput

case "${1:-web}" in
  web)
    exec gunicorn paleonews.wsgi:application --bind 0.0.0.0:8000
    ;;
  cron)
    # cron 설정 + 실행
    echo "${PIPELINE_CRON:-0 23 * * *} cd /app && python manage.py run_pipeline >> /app/logs/cron.log 2>&1" > /etc/cron.d/paleonews
    chmod 0644 /etc/cron.d/paleonews
    crontab /etc/cron.d/paleonews
    exec cron -f
    ;;
  bot)
    exec python manage.py run_bot
    ;;
  *)
    exec python manage.py "$@"
    ;;
esac
```

---

## Step 8: 테스트 전환

### 8.1 pytest → Django TestCase

```python
# tests/test_models.py
from django.test import TestCase
from articles.models import Article
from users.models import Subscriber, Dispatch


class ArticleModelTest(TestCase):
    def test_url_unique(self):
        Article.objects.create(url="https://example.com/1", title="Test")
        with self.assertRaises(Exception):
            Article.objects.create(url="https://example.com/1", title="Duplicate")

    def test_unsent_query(self):
        article = Article.objects.create(
            url="https://example.com/1", title="Test",
            is_relevant=True, summary_ko="요약"
        )
        sub = Subscriber.objects.create(chat_id="123")

        # 전송 전: unsent에 포함
        unsent = Article.objects.filter(
            is_relevant=True, summary_ko__isnull=False
        ).exclude(
            dispatches__channel="telegram",
            dispatches__subscriber=sub,
            dispatches__status="success"
        )
        self.assertIn(article, unsent)
```

### 8.2 pipeline 모듈 테스트

`test_filter.py`, `test_fetcher.py`는 DB 무관 로직이므로 거의 변경 없음.

---

## 구현 순서 (작업 단계)

| 단계 | 작업 | 예상 변경 |
|------|------|----------|
| **1** | Django 프로젝트 생성 + settings.py | 신규 파일 3개 |
| **2** | 모델 정의 + `makemigrations` | models.py 2개 |
| **3** | pipeline/ 디렉토리로 기존 로직 이동 | 파일 이동만 |
| **4** | management commands 구현 | 커맨드 7개 |
| **5** | admin.py 설정 | admin.py 2개 |
| **6** | bot.py ORM 전환 | 기존 파일 수정 |
| **7** | 데이터 마이그레이션 스크립트 | 마이그레이션 1개 |
| **8** | 기존 db.py, web.py, templates/ 삭제 | 파일 삭제 |
| **9** | Docker 설정 업데이트 | 파일 3개 수정 |
| **10** | 테스트 전환 + 검증 | 테스트 파일 수정 |

---

## 리스크 및 주의사항

1. **SQLite 동시성**: Django + SQLite는 단일 프로세스에 적합. 현재 3개 서비스(web/bot/pipeline)가 동시 접근하는 구조에서 WAL 모드 + busy_timeout으로 충분하지만, 트래픽 증가 시 PostgreSQL 전환 고려.

2. **config.yaml 유지**: 파이프라인 관련 설정(키워드, 모델명, 전용 피드 등)은 Django settings에 넣기엔 성격이 다름. `settings.PIPELINE_CONFIG`로 로딩하여 기존 config.yaml 구조 유지.

3. **봇 프로세스**: Telegram 봇은 장기 실행 프로세스. Django ORM을 봇에서 사용하려면 `django.setup()`을 명시적으로 호출해야 함. management command 내에서 실행하면 자동 처리됨.

4. **기존 entry.py (PyInstaller)**: PyInstaller 빌드를 유지하려면 Django를 포함한 빌드 설정이 필요. 복잡도가 높아지므로 Docker 배포로 일원화 권장.

5. **Django Admin 커스터마이징 한계**: 현재 web.py의 "파이프라인 실행" 버튼 같은 기능은 Django Admin에서 custom action으로 구현 가능하나, 실시간 상태 폴링은 별도 뷰가 필요할 수 있음.

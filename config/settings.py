"""paleonews Django 설정 — P08 §P2.

집 표준(fsis2026 형) 정렬. naverland 와 달리 **admin(로그인) 을 싣는다** — 실제 관리 UI 이고,
나중에 가입을 붙일 문을 열어두기 위해(2026-08-17 결정, P08 §4).

⚠️ admin 을 실으면 `django_session` 이 생긴다 = **bearer 토큰 테이블**. 계약 MUST 상,
운영 DB 사본이 호스트를 떠날 때(오프사이트 백업·개발 미러) 반출 직전에 지워야 한다.
현재 paleonews 백업은 `/srv/paleonews/backup` 에만 있고 호스트를 떠나지 않아 즉시 부담은 없다.
**오프사이트 트랙을 만드는 순간 이 의무가 발동한다** — P08 §P5.

### 단일 컨테이너 all 모드는 유지한다 (P06 보류 사유 ②)
cron 파이프라인 + Telegram bot + web 이 한 컨테이너에서 root 로 돈다. 서비스를 쪼개면
`claude_code` provider 의 구독 인증(`CLAUDE_CODE_OAUTH_TOKEN`, `/root/.claude`) 표면이 늘어나
0.2.8 에서 복구한 구독 과금이 깨진다. ⚠️ `ANTHROPIC_API_KEY` 가 env 에 들어가면 크레딧 과금으로 샌다.
"""
import os
from pathlib import Path

from paleonews.config import load_config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "paleonews-insecure-local-only")
DEBUG = os.environ.get("DJANGO_DEBUG", "").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = ["*"]      # nginx 뒤 사설망.

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "news.apps.NewsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "paleonews" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


def _db_path() -> str:
    """DB 경로의 단일 소스는 여전히 `config.yaml` 의 `db_path` 다.

    CLI·cron·백업·배포 게이트가 전부 그 값을 본다. Django 만 다른 곳을 보게 하면
    **한 프로세스 안에서 두 DB 를 쓰는** 상태가 조용히 생긴다.
    """
    if env := os.environ.get("DB_PATH"):
        return env
    try:
        return load_config(str(BASE_DIR / "config.yaml")).get("db_path", "paleonews.db")
    except FileNotFoundError:
        return str(BASE_DIR / "paleonews.db")


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _db_path(),
        "OPTIONS": {
            # WAL: db.py 가 이미 켜고 있다(같은 파일). 새 DB 부트스트랩용 보험.
            "init_command": "PRAGMA journal_mode=WAL;",
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = False
# ⚠️ USE_TZ=False. 기존 테이블의 시각은 전부 **TEXT 에 담긴 UTC ISO 문자열**이고
# (`fetched_at`, `sent_at`, `started_at` …) 파이프라인이 그 형식으로 직접 쓴다.
# USE_TZ 를 켜면 Django 가 datetime 을 다르게 해석해 CLI 가 쓴 값과 어긋난다.
USE_TZ = False

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

LOGIN_URL = "/admin/login/"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

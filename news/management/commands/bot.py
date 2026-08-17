"""Telegram 봇 데몬의 Django 진입점 — `manage.py bot`.

봇 로직은 `paleonews/bot.py` 그대로다. 이 명령은 **기동 방식만** 집 표준에 맞춘다.

⚠️ 봇은 `claude_code` provider 로 대화한다 — 구독 인증(`CLAUDE_CODE_OAUTH_TOKEN`,
`/root/.claude`)이 이 프로세스에 붙어 있어야 한다. all 모드 단일 컨테이너를 유지하는 이유다.
"""
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Telegram 봇 데몬 실행 (포그라운드)"

    def handle(self, *args, **options):
        from paleonews.bot import run_bot
        from paleonews.db import Database

        from news.views import get_config
        # ⚠️ DB 경로는 **Django settings 를 따른다**(DB_PATH env → config.yaml 순). run_pipeline 과 동일.
        db_path = settings.DATABASES["default"]["NAME"]
        config = {**get_config(), "db_path": db_path}
        db = Database(db_path)
        db.init_tables()
        run_bot(db, config)

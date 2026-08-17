"""파이프라인의 Django 진입점 — `manage.py run_pipeline [단계]`.

**파이프라인 로직은 건드리지 않는다.** `paleonews.__main__` 의 기존 함수를 그대로 호출한다.
단계별 로직(fetch/filter/crawl/summarize/send)과 그 배선은 이미 테스트가 덮고 있고
(`tests/test_pipeline_orchestration.py`), 여기서 다시 쓰면 그 안전망 밖으로 나간다.

컨테이너 cron 이 이 명령을 호출한다. `python -m paleonews run` 도 계속 동작한다 —
CLI 는 걷어내지 않는다(운영자가 컨테이너 안에서 단계별로 돌리는 경로).
"""
from django.conf import settings
from django.core.management.base import BaseCommand

STAGES = ("fetch", "filter", "crawl", "summarize", "send")


class Command(BaseCommand):
    help = "고생물학 뉴스 파이프라인 실행 (fetch → filter → crawl → summarize → send)"

    def add_arguments(self, parser):
        parser.add_argument("stage", nargs="?", choices=STAGES,
                            help="한 단계만 실행 (생략하면 전체)")

    def handle(self, *args, **options):
        from paleonews import __main__ as cli
        from paleonews.db import Database

        # 설정·DB 경로의 단일 소스는 config.yaml + app_settings overlay 다(뷰와 같은 함수).
        from news.views import get_config
        config = get_config()
        # ⚠️ DB 경로는 **Django settings 를 따른다**(DB_PATH env → config.yaml 순으로 이미 해석됨).
        # `config["db_path"]` 를 그대로 쓰면 DB_PATH 를 무시해 다른 DB 를 건드린다 — 실제로
        # 이 명령이 처음엔 개발 DB 를 크롤했다.
        db_path = settings.DATABASES["default"]["NAME"]
        config = {**config, "db_path": db_path}
        db = Database(db_path)
        db.init_tables()
        try:
            stage = options.get("stage")
            if not stage:
                cli._run_pipeline(db, config)
            else:
                getattr(cli, f"cmd_{stage}")(db, config)
        finally:
            db.close()

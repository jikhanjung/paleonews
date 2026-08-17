"""기존 SQLite 스키마를 그대로 덮는 모델 — P08 §P2.

`inspectdb` 출력에서 손질했다. naverland(§P1)와 같은 규칙:

1. **`db_table`·컬럼명 고정.** 운영 DB(articles 2,948 / dispatches 784)를 옮기지 않고
   자리에서 이어받는다 — 초기 마이그레이션은 `--fake-initial`.
2. **필드 타입을 기존 컬럼에 맞춘다**(TEXT → `TextField`). CharField 로 바꾸면 새 DB 를
   마이그레이션으로 만들 때 운영과 다른 스키마가 나온다.
3. 시각은 전부 **TEXT 에 담긴 UTC ISO 문자열**이다(`DateTimeField` 가 아니다). 파이프라인이
   `datetime.now(timezone.utc).isoformat()` 로 직접 쓰고 SQL 에서 문자열로 비교한다.
   타입을 바꾸면 CLI 가 쓴 값과 ORM 이 읽는 값이 어긋난다.

## `users` 를 auth.User 로 만들지 않은 이유 (P08 §4 에서의 의도적 이탈)

P08 은 "users ↔ Django `auth.User` 1:1 Profile"을 적어뒀지만, 여기서는 **`Subscriber` 독립
모델**로 둔다. 이유: 이 표의 사람들은 **자격증명이 없다** — 텔레그램 chat_id 나 이메일뿐이고
로그인을 하지 않는다. 지금 auth.User 로 승격하면 없는 username·password 를 지어내야 한다.
admin 로그인은 **운영자**용이고 그건 `auth_user` 가 따로 맡는다(운영자 ≠ 구독자).

SaaS 문은 그대로 열려 있다: 나중에 구독자에게 로그인을 주면
`user = OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True)` **가산 컬럼** 하나면 된다.
P08 이 피하려던 "테이블 재설계"는 이 방식으로도 생기지 않는다.
"""
from django.db import models


class Article(models.Model):
    """수집된 기사 (`articles`). 파이프라인이 단계별로 컬럼을 채운다."""

    url = models.TextField(unique=True)
    title = models.TextField()
    summary = models.TextField(blank=True, null=True)        # RSS 발췌
    source = models.TextField(blank=True, null=True)
    feed_url = models.TextField(blank=True, null=True)
    published = models.TextField(blank=True, null=True)
    fetched_at = models.TextField()
    is_relevant = models.BooleanField(blank=True, null=True)  # NULL = 아직 필터 전
    summary_ko = models.TextField(blank=True, null=True)
    title_ko = models.TextField(blank=True, null=True)
    body = models.TextField(blank=True, null=True)           # 크롤한 본문(요약에만 쓰임)
    # 크롤 실패 횟수. 이게 없던 시절 죽은 URL 이 큐 앞을 막아 6개월간 크롤이 0건이었다(0.3.4).
    crawl_attempts = models.IntegerField(default=0)

    class Meta:
        db_table = "articles"

    def __str__(self):
        return self.title_ko or self.title


class Subscriber(models.Model):
    """수신자 (`users`). **운영자가 아니라 구독자다** — 위 모듈 docstring 참조."""

    telegram_chat_id = models.TextField(unique=True, blank=True, null=True)
    username = models.TextField(blank=True, null=True)
    display_name = models.TextField(blank=True, null=True)
    email = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)     # 파이프라인 실패 통지 대상
    # JSON 배열 문자열. **NULL = 전체 수신**("*" 도 NULL 로 저장된다) — 발송 대상을 가르는 값.
    keywords = models.TextField(blank=True, null=True)
    notify_telegram = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=True)
    created_at = models.TextField()
    updated_at = models.TextField()

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.display_name or self.username or self.telegram_chat_id or f"#{self.pk}"


class Dispatch(models.Model):
    """발송 기록 (`dispatches`). 중복 발송 방지의 근거이자 운영 이력."""

    article = models.ForeignKey(Article, models.PROTECT)
    channel = models.TextField()                      # telegram | email | slack | discord
    sent_at = models.TextField()
    status = models.TextField()                       # success | failed | filtered
    # 구독자를 지워도 **발송 이력은 남긴다**(운영 데이터). 컬럼이 이미 nullable 이다.
    # ⚠️ 현행 `db.remove_user()` 는 dispatches 를 건드리지 않아, 이력이 있는 사용자를 지우면
    # FK 제약(PRAGMA foreign_keys=ON)에 걸린다. ORM 경로는 SET_NULL 로 그 함정을 없앤다 —
    # **의도한 동작 변경**이며 웹을 ORM 으로 옮길 때 DEPLOY.md 에 명시한다.
    user = models.ForeignKey(Subscriber, models.SET_NULL, blank=True, null=True)

    class Meta:
        db_table = "dispatches"


class Memory(models.Model):
    """Telegram 챗봇이 사용자별로 기억하는 내용 (`memories`)."""

    user = models.ForeignKey(Subscriber, models.CASCADE)   # 현행 remove_user 와 동일
    content = models.TextField()
    created_at = models.TextField()

    class Meta:
        db_table = "memories"


class Feed(models.Model):
    """RSS 피드 소스 (`feeds`). sources.txt 에서 이관됐고 이제 웹·CLI 로 운영자가 관리."""

    url = models.TextField(unique=True)
    title = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.TextField()
    updated_at = models.TextField()

    class Meta:
        db_table = "feeds"

    def __str__(self):
        return self.title or self.url


class PipelineRun(models.Model):
    """파이프라인 회차 기록 (`pipeline_runs`)."""

    started_at = models.TextField()
    finished_at = models.TextField(blank=True, null=True)
    fetched = models.IntegerField(default=0)
    new_articles = models.IntegerField(default=0)
    relevant = models.IntegerField(default=0)
    crawled = models.IntegerField(default=0)
    summarized = models.IntegerField(default=0)
    # ⚠️ **회차 증분**이지 누적 총계가 아니다(0.3.4 에서 수정). 그 이전 행에는 누적값이 들어 있다.
    sent = models.IntegerField(default=0)
    errors = models.TextField(blank=True, null=True)      # 단계별 실패를 줄바꿈으로 모은 것
    status = models.TextField(default="running")

    class Meta:
        db_table = "pipeline_runs"


class AppSetting(models.Model):
    """`config.yaml` 위에 얹는 런타임 설정 overlay (`app_settings`).

    ⚠️ **Django settings 로 옮기지 않는다**(P06 보류 사유 ④). 점 표기 키
    (`llm.provider`, `summarizer.model` …)를 매 요청 config 에 overlay 하는 구조라,
    프로세스-정적인 Django settings 와 성격이 다르다. `llm.provider` 값이 구독 과금 경로를 정한다.
    """

    key = models.TextField(primary_key=True)
    value = models.TextField()
    updated_at = models.TextField()

    class Meta:
        db_table = "app_settings"

    def __str__(self):
        return f"{self.key}={self.value}"

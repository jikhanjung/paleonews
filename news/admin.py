"""Django admin 등록.

admin 은 **모델 CRUD 만** 덮는다. 파이프라인 실행·상태 폴링, provider·모델 드롭다운,
사용자별 키워드 편집은 admin 으로 표현되지 않아 전용 화면(`news/views.py`)에 남는다
— P06 이 "Django Admin 이 web.py 를 대체한다"를 과대평가라고 본 이유가 이것이다.

여기 admin 은 그 화면들을 **대체하지 않고 보완한다**: 기사 본문 확인, 발송 이력 조회처럼
전용 화면에 없던 밑바닥 조회가 공짜로 생긴다.
"""
from django.contrib import admin

from .models import AppSetting, Article, Dispatch, Feed, Memory, PipelineRun, Subscriber


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("id", "title_ko", "title", "source", "is_relevant", "fetched_at",
                    "crawl_attempts")
    list_filter = ("is_relevant", "source")
    search_fields = ("title", "title_ko", "url", "source")
    ordering = ("-id",)
    # 운영 데이터는 파이프라인이 채운다 — admin 에서 손으로 만들 일이 없다.
    readonly_fields = ("url", "fetched_at")


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    """구독자 — **운영자(`auth_user`)와 다른 존재다.** 로그인하지 않는다."""

    list_display = ("id", "display_name", "telegram_chat_id", "email", "is_active",
                    "is_admin", "keywords")
    list_filter = ("is_active", "is_admin", "notify_telegram", "notify_email")
    search_fields = ("username", "display_name", "telegram_chat_id", "email")


@admin.register(Dispatch)
class DispatchAdmin(admin.ModelAdmin):
    list_display = ("id", "article", "channel", "status", "sent_at", "user")
    list_filter = ("channel", "status")
    ordering = ("-id",)


@admin.register(Feed)
class FeedAdmin(admin.ModelAdmin):
    list_display = ("id", "url", "title", "is_active", "created_at")
    list_filter = ("is_active",)


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ("id", "started_at", "finished_at", "status", "fetched", "new_articles",
                    "relevant", "crawled", "summarized", "sent")
    list_filter = ("status",)
    ordering = ("-id",)


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    """⚠️ `llm.provider` 값이 구독 과금 경로를 정한다 — 여기서 바꾸면 즉시 반영된다."""

    list_display = ("key", "value", "updated_at")


@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "content", "created_at")

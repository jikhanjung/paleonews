"""URL 라우팅 — FastAPI `web.py` 의 경로를 그대로 옮겼다.

경로가 바뀌면 템플릿 안의 form action 과 fetch 호출이 깨진다. 특성화 테스트가 응답은 지키지만
**경로 자체는 지키지 않으므로** 여기서 이름을 바꾸지 않는다.
"""
from django.contrib import admin
from django.urls import path

from news import views

urlpatterns = [
    path("healthz", views.healthz),          # 인증 없음 — smoke 가 소비

    path("", views.dashboard),
    path("articles", views.articles_list),

    path("users", views.users_list),
    path("users/add", views.users_add),
    path("users/<int:user_id>", views.user_detail),
    path("users/<int:user_id>/edit", views.user_edit),
    path("users/<int:user_id>/toggle", views.users_toggle),
    path("users/<int:user_id>/keywords", views.users_keywords),
    path("users/<int:user_id>/email", views.users_email),
    path("users/<int:user_id>/delete", views.users_delete),
    path("users/<int:user_id>/admin", views.users_toggle_admin),

    path("settings", views.settings_page),
    path("settings/models/update", views.settings_models_update),
    path("settings/sources/add", views.sources_add),
    path("settings/sources/remove", views.sources_remove),
    path("settings/sources/toggle", views.sources_toggle),

    path("pipeline/run", views.pipeline_run),
    path("pipeline/status", views.pipeline_status),

    path("admin/", admin.site.urls),
]

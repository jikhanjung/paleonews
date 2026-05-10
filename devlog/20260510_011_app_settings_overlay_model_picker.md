# DB 기반 설정 overlay + /settings에 모델 셀렉터 추가

**날짜**: 2026-05-10

## 배경

`/settings` 페이지에서 LLM provider, 필터/요약/챗 모델을 표시만 할 수 있고 변경할 수 없었음. config.yaml을 호스트에서 직접 편집하는 방식은 운영 친화적이지 않고, 사용자가 잘못된 yaml 문법으로 저장하면 컨테이너가 다음 cron부터 멈춤.

또한 Anthropic이 새 모델을 출시할 때마다 사용자가 정확한 model id 문자열을 외워서 입력해야 함 — `Anthropic().models.list()` API가 있으니 카탈로그를 동적으로 읽어와 드롭다운으로 보여주면 깔끔.

## 변경 사항

### 1. `app_settings` 테이블

`paleonews/db.py`:

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

CRUD 메서드: `get_setting(key)`, `set_setting(key, value)` (UPSERT), `get_all_settings()`, `delete_setting(key)`.

key는 dot-path(`summarizer.model`, `llm.provider`)로 명명, value는 string. 타입 강제는 호출자 책임.

### 2. config overlay 헬퍼

`paleonews/config.py`에 `apply_settings_overlay(config, overrides) -> dict` 추가:

```python
overlay = apply_settings_overlay(yaml_config, {
    "summarizer.model": "claude-sonnet-4-6",
    "llm.provider": "claude_code",
})
# overlay["summarizer"]["model"] == "claude-sonnet-4-6"
# overlay["llm"]["provider"] == "claude_code"
```

deepcopy 기반이라 원본 yaml dict 불변. 중간 dict가 없으면 자동 생성(`chat.model` overlay 시 `chat` 키 생성).

### 3. 적용 시점

| 컨텍스트 | 동작 |
|---|---|
| **CLI / cron 파이프라인** | `__main__.py:main()`이 `init_tables()` 직후 `config = apply_settings_overlay(config, db.get_all_settings())` 1회 적용. 매 호출마다 새 프로세스라 DB 변경이 다음 cron 실행부터 자동 반영 |
| **Web UI** | `web.py:get_config()`가 매 호출마다 yaml(캐시) + DB(매번) overlay 재구성. UI에서 모델 변경 후 페이지 새로고침이면 즉시 반영 |
| **Telegram 봇 데몬** | startup 시 1회. 변경 적용에는 컨테이너 재시작 필요 — settings.html에 안내 문구 |

### 4. /settings 모델 폼

`paleonews/web.py`:
- `get_available_models()` — Anthropic SDK `client.models.list(limit=50)` 호출, 1시간 메모리 캐시. 실패 시 빈 리스트 반환 → 템플릿이 자동으로 텍스트 입력으로 폴백
- `POST /settings/models/update` — provider/필터/요약/챗 4개 필드를 `db.set_setting`으로 저장 후 `/settings`로 리다이렉트

`paleonews/templates/settings.html`:
- 기존 "시스템 설정" 카드의 모델 행을 분리해서 새 "모델 설정" 카드 + form
- provider: 드롭다운(anthropic/openai/claude_code)
- 필터/요약/챗 모델: `available_models`가 있으면 셀렉트, 없으면 텍스트 입력으로 graceful degrade
- 현재 선택값이 카탈로그에 없으면(legacy/이미 사라진 모델) "(legacy)" 라벨로 보존
- 폼 하단에 "다음 cron부터 즉시 반영, 봇은 재시작 필요" 안내

### 5. 검증

```python
# DB 메서드
db.set_setting("summarizer.model", "claude-sonnet-4-6")
db.get_setting("summarizer.model")              # "claude-sonnet-4-6"
db.set_setting("summarizer.model", "claude-opus-4-7")  # UPSERT
db.delete_setting("llm.provider")
db.get_all_settings()                           # {"summarizer.model": "claude-opus-4-7"}

# Overlay
apply_settings_overlay(
    {"summarizer": {"model": "old", "max": 20}},
    {"summarizer.model": "NEW", "chat.model": "new"},
)
# {"summarizer": {"model": "NEW", "max": 20}, "chat": {"model": "new"}}
```

기존 41개 테스트 통과.

### 프로덕션 배포

```
$ curl -s http://127.0.0.1:8100/settings | grep -oE '<option[^>]+selected[^>]*>[^<]+'
... 'claude-haiku-4-5-20251001 (selected)' — 현재 yaml 값 정확히 표시
```

8개 Anthropic 모델 카탈로그가 드롭다운에 정상 표시. provider/모델 변경 폼 동작 확인.

## 운영 영향

- 이번 배포 시점에 `app_settings` 테이블은 비어있음 → yaml 값 그대로 사용
- 사용자가 /settings에서 모델 변경 시 → DB에 row 생성 → 다음 cron부터 새 모델 사용
- Anthropic이 새 모델 출시하면 1시간 내(또는 컨테이너 재시작 후) 자동으로 드롭다운에 등장
- DB가 진실의 원천이 되었으므로, 설정 백업/복원은 `paleonews.db` 파일만 챙기면 됨

## 후속 작업 후보

- 키워드 편집 UI (현재도 config.yaml 직접 편집 안내). 같은 overlay 패턴으로 `filter.keywords`도 DB로 옮길 수 있음
- 봇 챗 모델은 데몬 재시작 없이 반영하려면 매 chat 호출 시 DB 재조회 필요 — 현재는 startup 시 1회만 읽음
- OpenAI provider도 모델 카탈로그(`OpenAI().models.list()`) 추가 — provider별 모델 목록 분기

## 버전 이력

| 버전 | 내용 |
|------|------|
| 0.2.6 | app_settings 테이블, config overlay 헬퍼, /settings 모델 폼(드롭다운) |

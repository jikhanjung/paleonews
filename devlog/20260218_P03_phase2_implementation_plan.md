# Phase 2 구현 계획: 기능 개선 및 다중 사용자 지원

> 작성일: 2026-02-18
> 상위 문서: `20260218_P01_paleonews_plan_draft.md`
> 선행: Phase 1 MVP 완료 (`20260218_001_phase1_mvp_implementation.md`)

## 목표

Phase 1의 단일 사용자 파이프라인을 확장하여:
1. 다중 사용자 구독/키워드 관리
2. 필터링 품질 개선 (파생어, LLM 2차 필터)
3. 요약 품질 향상 (기사 본문 크롤링)
4. 추가 전송 채널 (Email, Slack/Discord)
5. 에러 알림 및 자동 실행

---

## 현재 아키텍처 (Phase 1)

```
sources.txt → Fetcher → DB → Filter(키워드) → Summarizer(Claude) → Telegram(1명)
```

## 목표 아키텍처 (Phase 2)

```
sources.txt → Fetcher → DB → Filter(키워드+LLM) → Crawler(본문) → Summarizer(Claude)
                                                                        ↓
                                                              사용자별 키워드 매칭
                                                                        ↓
                                                         Dispatcher(Telegram/Email/Webhook)
                                                                        ↓
                                                              사용자 A, B, C ...
```

---

## Step 1: 다중 사용자 지원

### 목표

Telegram 봇 명령어로 사용자 등록/해지 및 키워드 관리. 서버 상시 실행 없이 cron 기반으로 동작.

### DB 스키마 확장

```sql
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT UNIQUE NOT NULL,
    username    TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_keywords (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    keyword     TEXT NOT NULL,
    UNIQUE(user_id, keyword)
);
```

### 봇 명령어

| 명령어 | 동작 |
|--------|------|
| `/start` | 구독 등록 (users 테이블에 추가) |
| `/stop` | 구독 해지 (is_active = 0) |
| `/keywords` | 내 관심 키워드 목록 확인 |
| `/add <키워드>` | 키워드 추가 (예: `/add 공룡`) |
| `/remove <키워드>` | 키워드 삭제 |
| `/all` | 전체 기사 받기 모드 (키워드 필터 없이) |
| `/help` | 사용법 안내 |

### 메시지 처리 방식 (cron 기반)

```python
def process_bot_updates(db, bot_token):
    """Telegram getUpdates API로 새 메시지를 가져와 처리."""
    # 1. getUpdates 호출 (offset 기반으로 이전 메시지 건너뛰기)
    # 2. 각 메시지에서 명령어 파싱
    # 3. DB 업데이트 (사용자 등록/해지, 키워드 추가/삭제)
    # 4. 응답 메시지 전송
```

- `last_update_id`를 DB 또는 파일에 저장하여 중복 처리 방지
- cron 실행 시 파이프라인 전에 먼저 호출

### 사용자별 발송 로직

```python
def send_to_users(db, articles, bot_token):
    """각 사용자의 키워드에 맞는 기사만 필터링하여 전송."""
    active_users = db.get_active_users()
    for user in active_users:
        user_keywords = db.get_user_keywords(user["id"])
        if not user_keywords:
            # 키워드 미설정 → 전체 기사 전송
            matched = articles
        else:
            # 사용자 키워드로 2차 필터링
            matched = [a for a in articles if user_keyword_match(a, user_keywords)]
        if matched:
            briefing = generate_briefing(matched, date)
            dispatcher = TelegramDispatcher(bot_token, user["chat_id"])
            await dispatcher.send_briefing(briefing)
```

### 핵심 함수

```python
# db.py 추가
class Database:
    def save_user(self, chat_id: str, username: str) -> int: ...
    def deactivate_user(self, chat_id: str): ...
    def get_active_users(self) -> list[dict]: ...
    def add_user_keyword(self, user_id: int, keyword: str): ...
    def remove_user_keyword(self, user_id: int, keyword: str): ...
    def get_user_keywords(self, user_id: int) -> list[str]: ...
    def get_last_update_id(self) -> int: ...
    def set_last_update_id(self, update_id: int): ...

# 새 파일: paleonews/bot.py
def process_bot_updates(db, bot_token): ...
def handle_command(db, bot_token, chat_id, username, command, args): ...
```

### 완료 기준

- `/start`로 구독, `/stop`으로 해지 동작
- `/add`, `/remove`로 키워드 관리 동작
- 키워드 설정한 사용자는 맞춤 기사만 수신
- 키워드 미설정 사용자는 전체 기사 수신

---

## Step 2: 키워드 필터링 개선

### 목표

현재 단어 경계(`\b`) 매칭으로 인해 `fossilized`, `extinction event` 같은 파생어/복합어를 놓치는 문제 해결.

### 변경 사항 — `paleonews/filter.py`

```python
# 기존: 단어 경계 매칭 (fossil ≠ fossilized)
re.search(rf"\b{re.escape(kw)}\b", text)

# 변경: 접두사 매칭 (fossil → fossil, fossils, fossilized 모두 매칭)
re.search(rf"\b{re.escape(kw)}", text)
```

### 추가 키워드 (config.yaml)

```yaml
filter:
  keywords:
    # 기존 키워드 유지 + 추가
    - archaeolog        # archaeology, archaeological
    - phylogenet        # phylogenetic, phylogenetics
    - morpholog         # morphology, morphological
    - biostratigraph    # biostratigraphy, biostratigraphic
    - paleoecolog       # paleoecology, paleoecological
    - taphonomic        # taphonomic (taphonomy는 기존에 있음)
```

### 완료 기준

- `fossilized`, `fossils` 등 파생어 매칭 확인
- 기존 테스트 업데이트 (단어 경계 → 접두사)
- 오탐(false positive) 증가가 크지 않은지 확인

---

## Step 3: LLM 기반 2차 필터링

### 목표

키워드로 1차 필터 후, 경계선 기사(키워드 매칭되었으나 실제로는 무관한 기사)를 LLM으로 정밀 판정하여 품질 향상.

### 적용 대상

- 키워드 매칭은 되었으나 전용 피드가 아닌 기사 (Nature, Science 종합 피드)
- 전용 피드 기사는 LLM 판정 생략 (비용 절감)

### 구현 — `paleonews/filter.py` 확장

```python
LLM_FILTER_PROMPT = """\
다음 기사가 고생물학(paleontology)과 직접 관련이 있는지 판단해주세요.
고생물학: 화석, 멸종 생물, 지질시대 생물, 고인류학, 진화 고생물학 등

제목: {title}
요약: {summary}

"yes" 또는 "no"로만 답변하세요."""

def llm_filter(client: Anthropic, article: dict, model: str) -> bool:
    """LLM으로 고생물학 관련 여부를 판정. True=관련."""
    ...
```

### 필터링 로직 변경

```
기사가 전용 피드 출처인가?
  ├─ Yes → is_relevant = True (LLM 생략)
  └─ No  → 키워드 매칭
              ├─ 매칭됨 → LLM 2차 판정
              │            ├─ yes → is_relevant = True
              │            └─ no  → is_relevant = False
              └─ 매칭 안 됨 → is_relevant = False
```

### 비용 고려

- Haiku 모델 사용 (빠르고 저렴, yes/no 판정에 충분)
- 1차 키워드 필터를 먼저 적용하여 LLM 호출 최소화
- config에 `llm_filter.enabled` 옵션 추가 (끄기 가능)

### config.yaml 추가

```yaml
filter:
  keywords: [...]
  llm_filter:
    enabled: true
    model: "claude-haiku-4-5-20251001"
```

### 완료 기준

- Nature 종합 피드에서 고생물학 무관 기사 제거 확인
- LLM 필터 on/off 전환 가능
- 비용이 합리적 범위인지 확인 (기사당 ~100 토큰)

---

## Step 4: 기사 본문 크롤링

### 목표

현재 RSS의 제목+요약(description)만으로 요약하는데, 본문까지 가져와서 요약 품질 향상.

### 구현 — 새 파일 `paleonews/crawler.py`

```python
import httpx
from readability import Document  # readability-lxml

async def crawl_article(url: str) -> str | None:
    """기사 URL에서 본문 텍스트 추출. 실패 시 None 반환."""
    ...

def extract_text(html: str) -> str:
    """HTML에서 본문 텍스트 추출 (readability 사용)."""
    ...
```

### DB 스키마 확장

```sql
ALTER TABLE articles ADD COLUMN body TEXT;  -- 크롤링된 본문
```

### 파이프라인 변경

```
fetch → filter → crawl(신규) → summarize → send
```

### Summarizer 프롬프트 변경

```python
ARTICLE_PROMPT_WITH_BODY = """\
아래 영문 기사를 한국어로 요약해주세요.

제목: {title}
본문: {body}
출처: {source}

다음 형식으로 정확히 답변하세요:
제목: (한국어 제목, 30자 이내)
요약: (핵심 내용 3~4문장, 이 연구/발견이 왜 중요한지 포함)"""
```

### 고려 사항

- 크롤링 실패 시 기존 summary(RSS description)로 폴백
- Rate limiting: 서버 부담 방지를 위해 요청 간 1~2초 딜레이
- robots.txt 존중
- 본문이 너무 길면 앞부분만 사용 (토큰 비용 관리)

### 의존성 추가

```toml
dependencies = [
    ...
    "readability-lxml",   # HTML → 본문 추출
]
```

### 완료 기준

- 주요 출처(Nature, ScienceDaily, Phys.org)에서 본문 추출 확인
- 크롤링 실패 시 기존 요약으로 폴백 동작
- 요약 품질이 체감적으로 향상

---

## Step 5: 추가 전송 채널

### 목표

Telegram 외에 Email, Slack/Discord Webhook 채널 추가.

### 5-A: Email Dispatcher — `paleonews/dispatcher/email.py`

```python
class EmailDispatcher(BaseDispatcher):
    def __init__(self, smtp_host, smtp_port, sender, password, recipients): ...

    async def send_briefing(self, briefing: str) -> bool:
        """HTML 뉴스레터 형식으로 이메일 전송."""
        ...
```

### 5-B: Webhook Dispatcher — `paleonews/dispatcher/webhook.py`

```python
class WebhookDispatcher(BaseDispatcher):
    def __init__(self, webhook_url: str, platform: str = "slack"): ...

    async def send_briefing(self, briefing: str) -> bool:
        """Slack/Discord webhook으로 전송."""
        ...
```

### config.yaml 확장

```yaml
channels:
  telegram:
    enabled: true
    parse_mode: "HTML"
    max_message_length: 4096
  email:
    enabled: false
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    sender: ""          # .env에서 관리
    recipients: []
  slack:
    enabled: false
    webhook_url: ""     # .env에서 관리
  discord:
    enabled: false
    webhook_url: ""     # .env에서 관리
```

### .env 확장

```
EMAIL_PASSWORD=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### 완료 기준

- Email 전송 동작 확인
- Slack/Discord webhook 전송 동작 확인
- 채널별 enabled/disabled 전환 가능

---

## Step 6: 에러 알림

### 목표

파이프라인 실패 시 관리자에게 알림 전송.

### 구현 — `paleonews/__main__.py` 수정

```python
def _run_pipeline(db, config):
    errors = []
    try:
        cmd_fetch(db, config)
    except Exception as e:
        errors.append(f"Fetch 실패: {e}")

    try:
        cmd_filter(db, config)
    except Exception as e:
        errors.append(f"Filter 실패: {e}")

    # ... 각 단계 동일

    if errors:
        notify_admin(config, errors)

def notify_admin(config, errors):
    """관리자 chat_id로 에러 메시지 전송."""
    ...
```

### config.yaml 추가

```yaml
admin:
  telegram_chat_id: ""  # 관리자 chat_id (.env에서 관리)
```

### 완료 기준

- 파이프라인 단계별 에러 발생 시 관리자에게 Telegram 알림
- 에러가 있어도 나머지 단계는 계속 실행

---

## Step 7: cron 자동 실행 설정

### 목표

매일 정해진 시각에 파이프라인 자동 실행.

### crontab 설정

```bash
# 매일 오전 9시 실행
0 9 * * * cd /home/jikhanjung/projects/paleonews && /home/jikhanjung/projects/paleonews/dist/paleonews run >> /var/log/paleonews.log 2>&1
```

### 실행 흐름 (run 명령 수정)

```
1. process_bot_updates()  → 새 사용자 명령 처리
2. cmd_fetch()            → RSS 수집
3. cmd_filter()           → 필터링
4. cmd_crawl()            → 본문 크롤링 (선택)
5. cmd_summarize()        → 한국어 요약
6. cmd_send_to_users()    → 사용자별 맞춤 발송
7. notify_admin()         → 에러 시 관리자 알림
```

### 완료 기준

- cron 등록 후 매일 자동 실행 확인
- 로그 파일에 실행 이력 기록

---

## 구현 순서 및 의존성

| 순서 | Step | 주요 산출물 | 의존성 |
|------|------|------------|--------|
| 1 | 키워드 필터링 개선 | filter.py 수정 | 없음 (독립적) |
| 2 | 다중 사용자 지원 | db.py 확장, bot.py 신규 | 없음 |
| 3 | LLM 2차 필터링 | filter.py 확장 | Step 1 |
| 4 | 기사 본문 크롤링 | crawler.py 신규 | 없음 |
| 5 | 추가 전송 채널 | email.py, webhook.py | Step 2 |
| 6 | 에러 알림 | __main__.py 수정 | Step 2 |
| 7 | cron 자동 실행 | crontab 설정 | Step 1~6 전체 |

### 병렬 진행 가능

- Step 1 (키워드 개선) + Step 2 (다중 사용자) + Step 4 (크롤링)는 독립적이므로 병렬 진행 가능
- Step 3 (LLM 필터)는 Step 1 이후
- Step 5, 6은 Step 2 이후
- Step 7은 모든 기능 완성 후

---

## 완료 정의

Phase 2가 완료되었다고 판단하는 기준:

1. 다수 사용자가 봇 명령어로 구독/해지/키워드 관리 가능
2. 키워드 파생어가 정상 매칭됨
3. LLM 2차 필터로 오탐이 감소함
4. 본문 크롤링으로 요약 품질이 향상됨
5. Email 또는 Webhook 채널 중 1개 이상 동작
6. 에러 발생 시 관리자에게 알림
7. cron으로 매일 자동 실행
8. 각 기능에 대한 테스트 존재

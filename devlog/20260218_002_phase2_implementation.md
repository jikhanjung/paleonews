# Phase 2 구현 완료 (다중 사용자 제외)

> 작성일: 2026-02-18

## 요약

Phase 2 계획서(`20260218_P03`)에서 다중 사용자 지원(Step 2)을 제외한 나머지 기능을 모두 구현했다.

---

## 구현 내역

### Step 1: 키워드 필터링 개선

**변경 파일**: `paleonews/filter.py`, `config.yaml`, `tests/test_filter.py`

- 단어 경계 매칭(`\b...\b`) → 접두사 매칭(`\b...`)으로 변경
  - `fossil` → `fossil`, `fossils`, `fossilized` 모두 매칭
  - `extinct` → `extinct`, `extinction` 매칭
  - 단어 시작 경계는 유지 → `distinctly` 같은 비관련 단어는 매칭 안 됨
- 키워드 추가: `archaeolog`, `phylogenet`, `morpholog`, `biostratigraph`, `paleoecolog`
- 테스트 업데이트: 접두사 매칭 테스트, 부분 단어 비매칭 테스트 추가

### Step 3: LLM 기반 2차 필터링

**변경 파일**: `paleonews/filter.py`, `config.yaml`, `paleonews/__main__.py`

- `llm_filter()` 함수 추가: Claude Haiku로 고생물학 관련 여부 판정 (yes/no)
- 적용 대상: 키워드 매칭된 비전용 피드 기사만 (전용 피드는 생략)
- LLM 실패 시 보수적 접근 (기사 유지)
- `config.yaml`에 `filter.llm_filter.enabled` / `filter.llm_filter.model` 설정 추가
- `__main__.py`에서 LLM 필터 활성화 시 Anthropic 클라이언트 생성하여 전달

### Step 4: 기사 본문 크롤링

**신규 파일**: `paleonews/crawler.py`
**변경 파일**: `paleonews/db.py`, `paleonews/summarizer.py`, `paleonews/__main__.py`, `pyproject.toml`, `config.yaml`

- `crawler.py`: `readability-lxml`로 기사 HTML에서 본문 텍스트 추출
  - Rate limiting: 요청 간 1.5초 딜레이
  - 본문 최대 5000자 제한 (토큰 비용 관리)
  - 크롤링 실패 시 None 반환 (에러 무시)
- `db.py`: `body` 컬럼 추가, `get_uncrawled()`, `save_body()` 메서드 추가
  - 기존 DB 자동 마이그레이션 (`ALTER TABLE` 감지)
- `summarizer.py`: 본문이 있으면 `ARTICLE_PROMPT_WITH_BODY` 사용 (3~4문장 요약)
  - 본문 없으면 기존 RSS summary 기반 프롬프트 폴백
- 파이프라인에 `crawl` 단계 추가 (filter → **crawl** → summarize)
- CLI에 `crawl` 서브커맨드 추가
- `pyproject.toml`에 `readability-lxml` 의존성 추가
- `config.yaml`에 `crawler.max_per_run` 설정 추가

### Step 5: 추가 전송 채널

**신규 파일**: `paleonews/dispatcher/email.py`, `paleonews/dispatcher/webhook.py`
**변경 파일**: `paleonews/__main__.py`, `config.yaml`, `.env.example`

- **EmailDispatcher**: SMTP로 뉴스레터 전송 (plain text + HTML)
- **WebhookDispatcher**: Slack/Discord webhook 전송
  - Slack: `{"text": ...}` 형식
  - Discord: `{"content": ...}` 형식 (2000자 제한)
- `__main__.py`의 `cmd_send()` 리팩토링: 채널별 독립 발송
  - 각 채널은 `config.yaml`에서 `enabled` 플래그로 제어
  - 채널별로 별도의 발송 이력 관리 (dispatches 테이블)
- `config.yaml`에 `channels` 섹션 추가 (telegram, email, slack, discord)
- `.env.example`에 `EMAIL_PASSWORD`, `SLACK_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL` 추가

### Step 6: 에러 알림

**변경 파일**: `paleonews/__main__.py`

- `_run_pipeline()` 각 단계를 try/except로 감싸기
  - 한 단계 실패해도 나머지 단계 계속 실행
  - 에러 메시지 수집
- `_notify_admin()`: 에러 발생 시 관리자 Telegram으로 알림 전송
  - `ADMIN_CHAT_ID` 환경변수 우선, 없으면 `TELEGRAM_CHAT_ID` 사용

---

## 파이프라인 변경

```
Phase 1: fetch → filter(키워드) → summarize → send(Telegram)
Phase 2: fetch → filter(키워드+LLM) → crawl(본문) → summarize(본문활용) → send(다중채널)
                                                                            ↓
                                                              에러 발생 시 관리자 알림
```

---

## 미구현 (Phase 2에서 보류)

- **다중 사용자 지원** (Step 2): 사용자 등록/키워드 관리 — 별도 단계로 진행 예정

---

## 설정 파일 변경 요약

### config.yaml 추가 항목

```yaml
filter:
  llm_filter:
    enabled: true
    model: "claude-haiku-4-5-20251001"

crawler:
  max_per_run: 20

channels:
  telegram:
    enabled: true
  email:
    enabled: false
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    sender: ""
    recipients: []
  slack:
    enabled: false
  discord:
    enabled: false
```

### .env 추가 항목

```
EMAIL_PASSWORD=
SLACK_WEBHOOK_URL=
DISCORD_WEBHOOK_URL=
ADMIN_CHAT_ID=  # (선택) 없으면 TELEGRAM_CHAT_ID 사용
```

---

## cron 자동 실행

```bash
# 매일 오전 9시 실행
0 9 * * * cd /home/jikhanjung/projects/paleonews && ~/venv/paleonews/bin/paleonews run >> /var/log/paleonews.log 2>&1
```

---

## Git 커밋

- `118bb03` — Implement Phase 2: improved filtering, crawling, multi-channel dispatch, error alerts

---

## 다음 단계

- 다중 사용자 지원 (Telegram 봇 명령어 기반 구독/키워드 관리)
- Phase 3: 로깅 체계화, 모니터링, 피드 소스 관리 CLI

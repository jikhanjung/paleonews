# PaleoNews 시스템 계획 (초안)

> 작성일: 2026-02-18

## 목표

매일 고생물학 관련 RSS 피드를 수집하여, 주목할 만한 뉴스를 선별하고 한국어로 번역/요약한 뒤 사용자가 지정한 채널로 전송하는 자동화 시스템.

---

## 시스템 구성도

```
[RSS Feeds] → [Fetcher] → [Filter/Scorer] → [LLM 요약·번역] → [Dispatcher] → [채널]
  sources.txt     ↓             ↓                   ↓                ↓
                중복 제거     고생물학 관련도      한국어 뉴스       Telegram
                신규 판별     점수 매기기         브리핑 생성       Email
                                                                   Slack
                                                                   Discord 등
```

## 파이프라인 단계

### 1단계: Feed 수집 (Fetcher)

- `sources.txt`의 RSS/Atom 피드를 파싱하여 기사 목록 수집
- 각 기사에서 추출할 정보: 제목, 링크, 요약(description), 발행일, 저널/출처명
- 이미 처리한 기사를 추적하여 중복 방지 (URL 기반 dedup)
- 피드 파싱 실패 시 로깅 후 건너뛰기 (전체 파이프라인 중단 방지)

### 2단계: 필터링 및 점수 매기기 (Filter/Scorer)

- Nature, Science 같은 종합 저널은 고생물학과 무관한 기사가 대부분이므로 필터링 필요
- 방법 A (키워드 기반): 고생물학 관련 키워드로 1차 필터링 (fossil, dinosaur, paleontology, extinction, Cretaceous 등)
- 방법 B (LLM 기반): 제목+요약을 LLM에 넘겨 고생물학 관련도 판정
- 실용적 접근: 키워드로 1차 필터 → LLM으로 2차 정밀 판정 (비용 절감)
- palaeontology 전용 피드(Nature palaeontology, ScienceDaily fossils 등)는 필터 없이 통과

### 3단계: 요약 및 번역 (Summarizer/Translator)

- 선별된 기사들을 LLM(Claude API)으로 처리
  - 논문/기사의 핵심 내용을 2~3문장으로 한국어 요약
  - 왜 주목할 만한지 한 줄 코멘트 추가
- 일일 브리핑 포맷으로 구성:
  - 날짜, 기사 수
  - 기사별: 한국어 제목, 요약, 원문 링크, 출처

### 4단계: 전송 (Dispatcher)

- 채널별 포매터를 두어 같은 내용을 채널에 맞게 변환
- 초기 지원 채널 후보:
  - **Telegram Bot** — 가장 간단하게 시작할 수 있음 (우선 구현)
  - **Email** — 뉴스레터 형식
  - **Slack/Discord Webhook** — 팀 공유용
- 채널 추가는 인터페이스만 맞추면 확장 가능하도록 설계

---

## 기술 스택 (안)

| 구성 요소 | 선택지 | 비고 |
|-----------|--------|------|
| 언어 | Python 3.11+ | feedparser, httpx 등 생태계 활용 |
| RSS 파싱 | `feedparser` | 검증된 라이브러리 |
| HTTP | `httpx` | async 지원 |
| LLM | Claude API (`anthropic` SDK) | 필터링 + 요약/번역 |
| 상태 저장 | SQLite | 처리 이력, 중복 방지 |
| 스케줄링 | cron 또는 systemd timer | 매일 1회 실행 |
| 전송 | `python-telegram-bot`, `smtplib` 등 | 채널별 라이브러리 |
| 설정 | YAML 또는 TOML | 채널 설정, API 키 등 |

---

## 데이터 모델 (SQLite)

```sql
-- 수집된 기사
articles (
    id          INTEGER PRIMARY KEY,
    url         TEXT UNIQUE,        -- 중복 방지 키
    title       TEXT,
    summary     TEXT,               -- 원문 요약 (영문)
    source      TEXT,               -- 출처 (Nature, Science 등)
    published   DATETIME,
    fetched_at  DATETIME,
    is_relevant BOOLEAN,            -- 고생물학 관련 여부
    score       REAL                -- 관련도/중요도 점수
)

-- 발송 이력
dispatches (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER REFERENCES articles(id),
    channel     TEXT,               -- telegram, email 등
    sent_at     DATETIME,
    status      TEXT                -- success, failed
)
```

---

## 디렉토리 구조 (안)

```
paleonews/
├── sources.txt
├── config.yaml              # 설정 (API 키 참조, 채널 설정, 스케줄)
├── paleonews/
│   ├── __init__.py
│   ├── main.py              # 엔트리포인트: 파이프라인 실행
│   ├── fetcher.py           # RSS 수집
│   ├── filter.py            # 필터링/점수 매기기
│   ├── summarizer.py        # LLM 요약·번역
│   ├── dispatcher/
│   │   ├── __init__.py
│   │   ├── base.py          # 채널 인터페이스
│   │   ├── telegram.py
│   │   ├── email.py
│   │   └── webhook.py       # Slack/Discord
│   └── db.py                # SQLite 관리
├── tests/
├── devlog/
└── pyproject.toml
```

---

## 구현 순서

### Phase 1: 최소 동작 버전 (MVP)

1. **프로젝트 세팅** — pyproject.toml, 의존성, 기본 구조
2. **Fetcher** — sources.txt 읽기 → RSS 파싱 → 기사 목록 반환
3. **DB** — SQLite 초기화, 기사 저장, 중복 체크
4. **Filter** — 키워드 기반 1차 필터링
5. **Summarizer** — Claude API로 한국어 요약 생성
6. **Dispatcher (Telegram)** — Telegram Bot으로 브리핑 전송
7. **main.py** — 전체 파이프라인 연결, CLI로 실행

### Phase 2: 개선

- LLM 기반 2차 필터링 (관련도 판정 고도화)
- 추가 채널 (Email, Slack/Discord)
- 기사 본문 크롤링 (요약 품질 향상)
- 에러 알림 (파이프라인 실패 시 통지)

### Phase 3: 운영 안정화

- 로깅 체계화
- 모니터링 (몇 건 수집/발송되었는지)
- 피드 소스 관리 UI 또는 CLI
- 사용자별 관심 키워드/분야 설정

---

## 고려 사항

- **비용 관리**: Nature 종합 피드 등은 하루 수십 건이므로 키워드 필터로 LLM 호출 최소화
- **Rate Limit**: 피드 서버에 부담 주지 않도록 적절한 간격으로 요청
- **시간대**: 발행일 기준으로 최근 24시간 기사만 수집 (또는 마지막 실행 이후)
- **API 키 관리**: 환경변수 또는 `.env` 파일 사용, 절대 커밋하지 않음

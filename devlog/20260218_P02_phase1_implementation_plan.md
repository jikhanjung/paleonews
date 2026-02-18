# Phase 1 구현 계획: 최소 동작 버전 (MVP)

> 작성일: 2026-02-18
> 상위 문서: `20260218_P01_paleonews_plan_draft.md`

## 목표

`sources.txt`의 RSS 피드에서 고생물학 뉴스를 수집 → 키워드 필터링 → Claude API로 한국어 요약 → Telegram으로 전송하는 파이프라인을 end-to-end로 동작시킨다.

---

## Step 1: 프로젝트 세팅

### 할 일

- `pyproject.toml` 생성 (프로젝트 메타데이터, 의존성, 스크립트 엔트리포인트)
- 패키지 디렉토리 구조 생성
- `.gitignore` 작성 (`.env`, `*.db`, `__pycache__/`, `.venv/` 등)
- `.env.example` 작성 (필요한 환경변수 목록 안내)
- `config.yaml` 기본 설정 파일

### 의존성

```toml
[project]
name = "paleonews"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "feedparser",       # RSS/Atom 파싱
    "httpx",            # HTTP 클라이언트
    "anthropic",        # Claude API
    "python-telegram-bot",  # Telegram 전송
    "pyyaml",           # 설정 파일
    "python-dotenv",    # .env 로딩
]
```

### 설정 파일 구조 (`config.yaml`)

```yaml
sources_file: "sources.txt"
db_path: "paleonews.db"

# 전용 피드: 필터링 없이 모든 기사를 관련으로 판정
dedicated_feeds:
  - "nature.com/subjects/palaeontology"
  - "sciencedaily.com/rss/fossils"
  - "phys.org/rss-feed/biology-news/paleontology"
  - "wiley"
  - "cambridge.org"
  - "academic.oup.com"

filter:
  keywords:
    - fossil
    - dinosaur
    - paleontology
    - palaeontology
    - paleobiology
    - extinct
    - extinction
    - cretaceous
    - jurassic
    - triassic
    - cambrian
    - devonian
    - permian
    - cenozoic
    - mesozoic
    - paleozoic
    - neanderthal
    - hominin
    - hominid
    - mammoth
    - pterosaur
    - ichthyosaur
    - ammonite
    - trilobite
    - megafauna
    - stratigraphy
    - taphonomy

summarizer:
  model: "claude-sonnet-4-20250514"
  max_articles_per_run: 20

telegram:
  # chat_id는 .env에서 관리
  parse_mode: "HTML"
  max_message_length: 4096
```

### 디렉토리 구조

```
paleonews/
├── pyproject.toml
├── config.yaml
├── sources.txt
├── .env.example          # ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
├── .gitignore
├── paleonews/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── fetcher.py
│   ├── filter.py
│   ├── summarizer.py
│   ├── dispatcher/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── telegram.py
│   └── db.py
├── tests/
│   ├── __init__.py
│   ├── test_fetcher.py
│   ├── test_filter.py
│   └── test_db.py
└── devlog/
```

### 완료 기준

- `pip install -e .` 로 설치 가능
- `python -m paleonews --help` 실행 시 CLI 도움말 출력

---

## Step 2: Fetcher (RSS 수집)

### 할 일 — `paleonews/fetcher.py`

- `sources.txt`에서 피드 URL 목록을 읽는 함수
- 각 URL을 `feedparser`로 파싱하여 기사 리스트 반환
- 피드별 파싱 실패 시 로깅 후 건너뛰기

### 기사 데이터 구조

```python
@dataclass
class Article:
    url: str                    # 기사 고유 링크
    title: str                  # 원문 제목
    summary: str                # 원문 요약 (description)
    source: str                 # 출처 이름 (피드 title에서 추출)
    feed_url: str               # 피드 URL (전용 피드 판별용)
    published: datetime | None  # 발행일
```

### 핵심 함수

```python
def load_sources(path: str) -> list[str]:
    """sources.txt에서 피드 URL 목록 반환"""

def fetch_feed(url: str) -> list[Article]:
    """단일 피드를 파싱하여 Article 리스트 반환"""

def fetch_all(sources: list[str]) -> list[Article]:
    """모든 피드를 순회하며 전체 Article 수집"""
```

### 고려 사항

- `feedparser`는 동기 라이브러리이므로 MVP에서는 순차 처리 (Phase 2에서 async 고려)
- User-Agent 헤더를 적절히 설정하여 차단 방지
- 발행일 파싱: `feedparser`의 `published_parsed` 활용, 없으면 None

### 완료 기준

- 10개 피드를 모두 파싱하여 기사 목록 출력 가능
- 파싱 실패 피드가 있어도 나머지는 정상 수집

---

## Step 3: DB (SQLite 상태 관리)

### 할 일 — `paleonews/db.py`

- SQLite DB 초기화 (테이블 생성)
- 기사 저장 (INSERT OR IGNORE로 중복 방지)
- 미처리 기사 조회
- 발송 이력 기록

### 스키마

```sql
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT,
    source      TEXT,
    feed_url    TEXT,
    published   TEXT,           -- ISO 8601
    fetched_at  TEXT NOT NULL,  -- ISO 8601
    is_relevant BOOLEAN,       -- NULL=미판정, 1=관련, 0=무관
    summary_ko  TEXT,          -- 한국어 요약 (LLM 생성)
    title_ko    TEXT           -- 한국어 제목 (LLM 생성)
);

CREATE TABLE IF NOT EXISTS dispatches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL REFERENCES articles(id),
    channel     TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    status      TEXT NOT NULL   -- 'success' | 'failed'
);
```

### 핵심 함수

```python
class Database:
    def __init__(self, db_path: str): ...
    def init_tables(self): ...
    def save_articles(self, articles: list[Article]) -> int:
        """기사 저장, 새로 추가된 건수 반환"""
    def get_unfiltered(self) -> list[dict]:
        """is_relevant가 NULL인 기사 반환"""
    def mark_relevant(self, article_id: int, is_relevant: bool): ...
    def get_unsummarized(self) -> list[dict]:
        """is_relevant=True이고 summary_ko가 NULL인 기사"""
    def save_summary(self, article_id: int, title_ko: str, summary_ko: str): ...
    def get_unsent(self, channel: str) -> list[dict]:
        """요약 완료되었지만 해당 채널로 미발송인 기사"""
    def record_dispatch(self, article_id: int, channel: str, status: str): ...
```

### 완료 기준

- DB 파일 자동 생성 및 테이블 초기화
- 같은 URL 기사를 두 번 저장해도 중복 없음
- 파이프라인 각 단계의 상태 조회 가능

---

## Step 4: Filter (키워드 필터링)

### 할 일 — `paleonews/filter.py`

- 전용 피드 여부 판별: `config.yaml`의 `dedicated_feeds` 패턴 매칭
- 종합 피드 기사: 제목 + 요약에서 키워드 매칭
- 판정 결과를 DB에 저장

### 핵심 함수

```python
def is_dedicated_feed(feed_url: str, patterns: list[str]) -> bool:
    """전용 피드인지 URL 패턴으로 판별"""

def keyword_match(title: str, summary: str, keywords: list[str]) -> bool:
    """제목 또는 요약에 키워드가 포함되면 True (대소문자 무시)"""

def filter_articles(db: Database, config: dict) -> int:
    """미판정 기사를 필터링하고 DB 갱신, 관련 기사 수 반환"""
```

### 필터링 로직

```
기사가 전용 피드 출처인가?
  ├─ Yes → is_relevant = True
  └─ No  → 키워드 매칭
              ├─ 매칭됨 → is_relevant = True
              └─ 매칭 안 됨 → is_relevant = False
```

### 완료 기준

- Nature 종합 피드에서 고생물학 무관 기사 필터링 확인
- 전용 피드 기사는 전부 통과 확인
- 키워드 매칭은 대소문자 무시

---

## Step 5: Summarizer (LLM 요약/번역)

### 할 일 — `paleonews/summarizer.py`

- 관련 판정된 기사를 Claude API로 한국어 요약
- 기사별 개별 요약 + 전체 브리핑 텍스트 생성

### 핵심 함수

```python
def summarize_article(client: Anthropic, article: dict) -> tuple[str, str]:
    """단일 기사 → (한국어 제목, 한국어 요약) 반환"""

def generate_briefing(articles: list[dict], date: str) -> str:
    """요약된 기사 목록을 일일 브리핑 텍스트로 조합"""
```

### LLM 프롬프트 설계

**기사별 요약 프롬프트:**

```
당신은 고생물학 전문 과학 저널리스트입니다.
아래 영문 기사를 한국어로 요약해주세요.

제목: {title}
요약: {summary}
출처: {source}

다음 형식으로 답변하세요:
제목: (한국어 제목, 30자 이내)
요약: (핵심 내용 2~3문장, 이 연구/발견이 왜 중요한지 포함)
```

### 브리핑 출력 포맷

```
🦴 고생물학 뉴스 브리핑 (2026-02-18)
━━━━━━━━━━━━━━━━━━━━━━

📌 한국어 제목 1
요약 내용 2~3문장...
🔗 원문: https://...
📰 출처: Nature

──────────────────────

📌 한국어 제목 2
...

━━━━━━━━━━━━━━━━━━━━━━
총 N건의 뉴스가 수집되었습니다.
```

### 비용 고려

- Sonnet 모델 사용 (속도와 비용의 균형)
- 하루 최대 20건 제한 (`max_articles_per_run`)
- 제목+요약만 전달 (본문 크롤링은 Phase 2)

### 완료 기준

- 영문 기사 → 자연스러운 한국어 요약 생성
- 브리핑 포맷이 가독성 있게 출력

---

## Step 6: Dispatcher — Telegram

### 할 일 — `paleonews/dispatcher/telegram.py`

- Telegram Bot API로 브리핑 메시지 전송
- 메시지 길이 제한(4096자) 초과 시 분할 전송
- 발송 결과를 DB에 기록

### 사전 준비 (수동)

1. BotFather에서 봇 생성 → 토큰 발급
2. 봇과 대화 시작 또는 채널/그룹에 추가
3. chat_id 확인
4. `.env`에 설정:
   ```
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```

### 핵심 함수

```python
class TelegramDispatcher:
    def __init__(self, bot_token: str, chat_id: str): ...

    async def send_briefing(self, briefing: str) -> bool:
        """브리핑 텍스트를 Telegram으로 전송"""

    def split_message(self, text: str, limit: int = 4096) -> list[str]:
        """긴 메시지를 기사 단위로 분할"""
```

### 완료 기준

- 브리핑 메시지가 Telegram 채팅에 도착
- 긴 브리핑이 여러 메시지로 분할 전송

---

## Step 7: main.py — 파이프라인 통합

### 할 일 — `paleonews/main.py`

- 전체 파이프라인을 순차 실행하는 CLI 엔트리포인트
- 각 단계의 진행 상황을 콘솔에 출력

### CLI 인터페이스

```bash
# 전체 파이프라인 실행
python -m paleonews run

# 개별 단계 실행 (디버깅용)
python -m paleonews fetch      # 피드 수집만
python -m paleonews filter     # 필터링만
python -m paleonews summarize  # 요약만
python -m paleonews send       # 전송만

# 상태 확인
python -m paleonews status     # DB 통계 출력
```

### 파이프라인 흐름

```python
def run_pipeline(config):
    db = Database(config["db_path"])
    db.init_tables()

    # 1. 수집
    sources = load_sources(config["sources_file"])
    articles = fetch_all(sources)
    new_count = db.save_articles(articles)
    print(f"수집: {len(articles)}건, 신규: {new_count}건")

    # 2. 필터링
    relevant = filter_articles(db, config)
    print(f"고생물학 관련: {relevant}건")

    # 3. 요약
    unsummarized = db.get_unsummarized()
    client = Anthropic()
    for article in unsummarized[:config["summarizer"]["max_articles_per_run"]]:
        title_ko, summary_ko = summarize_article(client, article)
        db.save_summary(article["id"], title_ko, summary_ko)
    print(f"요약 완료: {len(unsummarized)}건")

    # 4. 전송
    unsent = db.get_unsent("telegram")
    if unsent:
        briefing = generate_briefing(unsent, date.today().isoformat())
        dispatcher = TelegramDispatcher(...)
        await dispatcher.send_briefing(briefing)
        for a in unsent:
            db.record_dispatch(a["id"], "telegram", "success")
    print(f"전송: {len(unsent)}건")
```

### 완료 기준

- `python -m paleonews run` 한 번으로 수집→필터→요약→전송 완료
- 두 번 실행해도 같은 기사가 중복 처리되지 않음
- 개별 서브커맨드로 단계별 실행 가능

---

## 테스트 계획

| 대상 | 테스트 내용 | 방법 |
|------|------------|------|
| Fetcher | 피드 파싱, 실패 처리 | 로컬 XML 파일로 단위 테스트 |
| DB | 중복 방지, 상태 전이 | in-memory SQLite로 단위 테스트 |
| Filter | 키워드 매칭, 전용 피드 판별 | 고정 데이터로 단위 테스트 |
| Summarizer | 프롬프트 포맷, 브리핑 생성 | LLM 호출 mock으로 포맷 테스트 |
| 통합 | 전체 파이프라인 | 실제 피드로 수동 E2E 테스트 |

```bash
# 테스트 실행
pytest tests/

# 단일 테스트
pytest tests/test_filter.py -v
```

---

## 구현 순서 및 예상 작업량

| 순서 | Step | 주요 산출물 | 의존성 |
|------|------|------------|--------|
| 1 | 프로젝트 세팅 | pyproject.toml, 디렉토리, .gitignore | 없음 |
| 2 | DB | db.py, 스키마 | Step 1 |
| 3 | Fetcher | fetcher.py, test_fetcher.py | Step 1, 2 |
| 4 | Filter | filter.py, test_filter.py | Step 2, 3 |
| 5 | Summarizer | summarizer.py | Step 2, 4 |
| 6 | Telegram | dispatcher/telegram.py | Step 5 |
| 7 | 통합 | main.py, CLI | Step 3~6 전체 |

---

## 완료 정의

Phase 1이 완료되었다고 판단하는 기준:

1. `python -m paleonews run` 실행 시 10개 피드에서 기사를 수집한다
2. 고생물학 관련 기사만 필터링된다
3. 필터링된 기사에 대해 한국어 요약이 생성된다
4. Telegram 채팅으로 일일 브리핑이 전송된다
5. 재실행 시 이미 처리된 기사는 건너뛴다
6. 주요 모듈에 대한 단위 테스트가 존재한다

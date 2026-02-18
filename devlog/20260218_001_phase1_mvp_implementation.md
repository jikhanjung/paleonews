# Phase 1 MVP 구현 완료

> 작성일: 2026-02-18

## 요약

Phase 1 계획서(`20260218_P02`)에 따라 MVP 전체 파이프라인을 구현하고, 실제 RSS 피드 수집부터 Telegram 전송까지 end-to-end 동작을 확인했다.

---

## 구현 내역

### Step 1: 프로젝트 세팅 (이전 세션에서 완료)

- `pyproject.toml`, `.gitignore`, `.env.example`, `config.yaml` 작성
- 패키지 디렉토리 구조 생성
- CLI 골격 (`__main__.py`) 작성

### Step 2: DB 모듈 — `paleonews/db.py`

- SQLite 기반 `Database` 클래스 구현
- `articles` 테이블: URL 기반 중복 방지 (`INSERT OR IGNORE`)
- `dispatches` 테이블: 채널별 발송 이력 관리
- 파이프라인 각 단계별 상태 조회 메서드:
  - `get_unfiltered()`, `get_unsummarized()`, `get_unsent()`
  - `mark_relevant()`, `save_summary()`, `record_dispatch()`
- `get_stats()`: 전체/관련/요약/전송 건수 통계

### Step 3: Fetcher 모듈 — `paleonews/fetcher.py`

- `Article` dataclass 정의 (url, title, summary, source, feed_url, published)
- `load_sources()`: `sources.txt`에서 피드 URL 목록 로드
- `fetch_feed()`: 단일 피드를 `feedparser`로 파싱
- `fetch_all()`: 모든 피드 순회하며 기사 수집
- HTML 태그 제거, 발행일 파싱, 피드 실패 시 건너뛰기 처리

### Step 4: Filter 모듈 — `paleonews/filter.py`

- `is_dedicated_feed()`: 전용 피드 URL 패턴 매칭 (필터 없이 통과)
- `keyword_match()`: 제목+요약에서 키워드 매칭 (대소문자 무시, 단어 경계)
- `filter_articles()`: 미판정 기사를 필터링하고 DB 갱신

### Step 5: Summarizer 모듈 — `paleonews/summarizer.py`

- `summarize_article()`: Claude API로 영문 기사 → 한국어 제목+요약 생성
- `generate_briefing()`: 요약된 기사 목록을 일일 브리핑 텍스트로 조합
- 모델: `claude-sonnet-4-20250514`, 1회 최대 20건 제한

### Step 6: Telegram Dispatcher — `paleonews/dispatcher/telegram.py`

- `BaseDispatcher` 추상 클래스 (`dispatcher/base.py`)
- `TelegramDispatcher`: Telegram Bot API로 브리핑 전송
- `split_message()`: 4096자 초과 시 기사 단위로 메시지 분할

### Step 7: 파이프라인 통합 — `paleonews/__main__.py`

- 서브커맨드: `run`, `fetch`, `filter`, `summarize`, `send`, `status`
- `run`: 전체 파이프라인 순차 실행 (fetch → filter → summarize → send)
- 각 단계별 진행 상황 콘솔 출력

### 테스트 — `tests/`

- `test_db.py`: 테이블 초기화, 중복 방지, 상태 전이, 발송 흐름, 통계 (6개)
- `test_fetcher.py`: 소스 파일 로드, 잘못된 URL 처리 (2개)
- `test_filter.py`: 전용 피드 판별, 키워드 매칭 긍정/부정/대소문자/경계 (5개)
- 총 13개 테스트 전부 통과

### PyInstaller 빌드

- `entry.py`: pyinstaller용 엔트리포인트 (relative import 문제 해결)
- `paleonews.spec`: 빌드 설정 파일
- `pyproject.toml`에 `[project.scripts]` 추가 (`paleonews` 명령어 등록)
- `dist/paleonews`: 19MB 단일 실행파일 생성 확인

---

## 실행 결과

### 피드 수집

```
10개 피드에서 288건 수집
- AAAS Science: 41건
- ScienceDaily Fossils: 60건
- Journal of Paleontology: 2건
- Nature: 75건
- Nature Palaeontology: 30건
- Phys.org Paleontology: 30건
- Systematic Biology: 13건
- Wiley Cladistics: 18건
- Wiley Palaeontology: 7건
- Wiley Papers in Palaeontology: 12건
```

### 필터링

```
288건 중 175건 관련, 113건 무관
```

### 요약 및 전송

```
40건 한국어 요약 완료 (20건 × 2회 실행)
40건 Telegram 전송 완료 (paleonews_kr_bot → 개인 채팅)
```

---

## 환경 설정

- 가상환경: `~/venv/paleonews`
- Telegram 봇: `@paleonews_kr_bot` (`https://t.me/paleonews_kr_bot`)
- `.env` 파일에 `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 설정

---

## Git 커밋

- `2e5ec4a` — Implement Phase 1 MVP: RSS fetch, filter, summarize, and Telegram dispatch
- `fdeaf23` — Add PyInstaller build support and CLI entry point

---

## 다음 단계 (Phase 2 후보)

- LLM 기반 2차 필터링 (관련도 판정 고도화)
- 다중 사용자 지원 (구독/키워드 관리, Telegram 봇 명령어)
- 추가 채널 (Email, Slack/Discord)
- 기사 본문 크롤링 (요약 품질 향상)
- cron 자동 실행 설정

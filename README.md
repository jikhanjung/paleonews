# PaleoNews

고생물학 뉴스 집계 시스템. RSS 피드에서 고생물학 관련 기사를 수집하고, 키워드+LLM으로 필터링한 뒤, Claude API로 한국어 요약을 생성하여 Telegram/Email/Slack/Discord로 전송합니다.

## 파이프라인

```
RSS Feeds → Fetch → Filter(키워드+LLM) → Crawl(본문) → Summarize(Claude) → Send(다중채널)
```

## 설치

```bash
# Python 3.11+ 필요
python -m venv venv
source venv/bin/activate
pip install -e .
```

## 설정

### .env

```bash
cp .env.example .env
```

필수:
- `ANTHROPIC_API_KEY` — Claude API 키
- `TELEGRAM_BOT_TOKEN` — Telegram 봇 토큰 (BotFather에서 발급)
- `TELEGRAM_CHAT_ID` — 수신할 채팅 ID

선택:
- `EMAIL_PASSWORD` — Email SMTP 비밀번호
- `SLACK_WEBHOOK_URL` — Slack webhook URL
- `DISCORD_WEBHOOK_URL` — Discord webhook URL
- `ADMIN_CHAT_ID` — 에러 알림 수신용 (미설정 시 TELEGRAM_CHAT_ID 사용)

### config.yaml

주요 설정:

```yaml
# RSS 피드 소스
sources_file: "sources.txt"

# 전용 피드 (필터링 없이 통과)
dedicated_feeds:
  - "nature.com/subjects/palaeontology"
  - "sciencedaily.com/rss/fossils"
  ...

# 키워드 필터링 (접두사 매칭)
filter:
  keywords: [fossil, dinosaur, paleontology, ...]
  llm_filter:
    enabled: true                        # LLM 2차 필터 on/off
    model: "claude-haiku-4-5-20251001"

# 본문 크롤링
crawler:
  max_per_run: 20

# 요약
summarizer:
  model: "claude-sonnet-4-20250514"
  max_articles_per_run: 20

# 전송 채널
channels:
  telegram:
    enabled: true
  email:
    enabled: false
  slack:
    enabled: false
  discord:
    enabled: false
```

## 사용법

```bash
# 전체 파이프라인 실행
paleonews run

# 개별 단계 실행
paleonews fetch       # RSS 피드 수집
paleonews filter      # 필터링
paleonews crawl       # 기사 본문 크롤링
paleonews summarize   # Claude API로 한국어 요약
paleonews send        # 전송

# 상태 확인
paleonews status
```

### cron 자동 실행

```bash
# 매일 오전 9시 실행
0 9 * * * cd /path/to/paleonews && /path/to/venv/bin/paleonews run >> /var/log/paleonews.log 2>&1
```

## PyInstaller 빌드

```bash
pip install pyinstaller
pyinstaller --onefile --name paleonews --paths . \
  --hidden-import paleonews.config \
  --hidden-import paleonews.db \
  --hidden-import paleonews.fetcher \
  --hidden-import paleonews.filter \
  --hidden-import paleonews.summarizer \
  --hidden-import paleonews.dispatcher.telegram \
  --hidden-import paleonews.dispatcher.base \
  entry.py
```

실행파일: `dist/paleonews`

## 피드 소스

`sources.txt`에 RSS/Atom 피드 URL을 한 줄에 하나씩 추가:

| 출처 | 유형 |
|------|------|
| Science (AAAS) | 종합 (필터링 필요) |
| ScienceDaily Fossils | 전용 피드 |
| Nature | 종합 + 고생물학 전용 |
| Phys.org Paleontology | 전용 피드 |
| Cambridge University Press | 학술 저널 |
| Oxford Academic | 학술 저널 |
| Wiley Online Library | 학술 저널 (3개) |

## 프로젝트 구조

```
paleonews/
├── paleonews/
│   ├── __main__.py        # CLI 엔트리포인트, 파이프라인 통합
│   ├── config.py          # YAML 설정 로딩
│   ├── db.py              # SQLite DB 관리
│   ├── fetcher.py         # RSS 피드 수집
│   ├── filter.py          # 키워드 + LLM 필터링
│   ├── crawler.py         # 기사 본문 크롤링
│   ├── summarizer.py      # Claude API 한국어 요약
│   └── dispatcher/
│       ├── base.py        # 채널 인터페이스
│       ├── telegram.py    # Telegram 전송
│       ├── email.py       # Email 전송
│       └── webhook.py     # Slack/Discord 전송
├── tests/
├── devlog/                # 개발 로그 및 계획 문서
├── config.yaml
├── sources.txt
├── entry.py               # PyInstaller 엔트리포인트
└── pyproject.toml
```

## 테스트

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

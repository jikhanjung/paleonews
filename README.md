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
- `TELEGRAM_CHAT_ID` — 관리자 채팅 ID (최초 관리자로 자동 등록)

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
paleonews send        # 전송 (등록된 사용자별로 키워드 필터링 후 발송)

# 상태 확인
paleonews status
paleonews status -v   # 상세 통계 (출처별, 실행 이력, 사용자 현황)
```

### cron 자동 실행

```bash
# 매일 오전 9시 실행
0 9 * * * cd /path/to/paleonews && /path/to/venv/bin/paleonews run >> /var/log/paleonews.log 2>&1
```

## 다중 사용자 지원

여러 Telegram 사용자에게 각자의 관심 키워드에 맞는 브리핑을 발송할 수 있습니다.

### 동작 방식

- 파이프라인(fetch/filter/crawl/summarize)은 모든 고생물학 기사를 공통으로 처리
- **전송 단계에서** 각 사용자별로 키워드 필터링을 적용하여 개인화된 브리핑 발송
- `TELEGRAM_CHAT_ID` 환경변수의 사용자가 자동으로 관리자로 등록됨
- Email/Slack/Discord 채널은 기존과 동일하게 동작 (사용자 구분 없음)

### CLI 사용자 관리

```bash
# 사용자 목록
paleonews users list

# 사용자 추가
paleonews users add 123456789
paleonews users add 123456789 --name "홍길동" --admin

# 사용자 삭제
paleonews users remove 123456789

# 키워드 설정
paleonews users keywords 123456789                      # 현재 키워드 확인
paleonews users keywords 123456789 dinosaur fossil      # 키워드 설정
paleonews users keywords 123456789 *                    # 전체 수신으로 변경

# 활성화/비활성화
paleonews users activate 123456789
paleonews users deactivate 123456789
```

### Telegram 봇 데몬

사용자가 직접 구독/키워드를 관리할 수 있는 Telegram 봇을 실행합니다.

```bash
paleonews bot
```

봇 명령어:
- `/start` — 구독 시작 (자동 등록)
- `/stop` — 구독 해제
- `/keywords` — 현재 키워드 확인
- `/keywords dinosaur fossil mammoth` — 키워드 설정
- `/keywords *` — 전체 수신
- `/help` — 도움말

봇 데몬은 파이프라인과 별도로 상시 실행합니다. systemd 서비스로 등록하면 편리합니다:

```ini
# /etc/systemd/system/paleonews-bot.service
[Unit]
Description=PaleoNews Telegram Bot
After=network.target

[Service]
WorkingDirectory=/path/to/paleonews
ExecStart=/path/to/venv/bin/paleonews bot
Restart=always
EnvironmentFile=/path/to/paleonews/.env

[Install]
WantedBy=multi-user.target
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
│   ├── filter.py          # 키워드 + LLM 필터링 + 사용자별 키워드 필터
│   ├── crawler.py         # 기사 본문 크롤링
│   ├── summarizer.py      # Claude API 한국어 요약
│   ├── bot.py             # Telegram 봇 데몬
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

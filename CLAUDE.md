# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

고생물학 뉴스 집계 시스템. RSS 피드에서 기사를 수집 → 키워드+LLM 필터링 → 본문 크롤링 → Claude API로 한국어 요약 → Telegram/Email/Slack/Discord로 전송하는 자동화 파이프라인.

## Tech Stack

- **Language**: Python 3.11+
- **RSS Parsing**: feedparser
- **HTTP**: httpx
- **LLM**: provider 추상화 (`llm.py`) — anthropic | openai | claude_code(CLI). 기본 anthropic, 요약: Sonnet, 필터/챗: Haiku
- **DB**: SQLite (WAL mode)
- **HTML Parsing**: readability-lxml
- **Telegram**: python-telegram-bot
- **Web Admin**: FastAPI + Jinja2 (uvicorn)
- **Config**: YAML + .env (python-dotenv) + DB overlay (`app_settings` 테이블)
- **Deploy**: Docker + nginx + cron (`deploy/`)

## Architecture

```
feeds(DB) → Fetcher → DB → Filter(키워드+LLM) → Crawler(본문) → Summarizer(Claude) → Dispatcher(다중채널)
```

파이프라인은 5단계: `fetch → filter → crawl → summarize → send`

설정은 `config.yaml`(베이스) 위에 `app_settings` 테이블 값을 overlay하여 구성. CLI/cron은 프로세스 시작 시 1회, 웹 UI는 매 요청마다 재구성 (`config.py:apply_settings_overlay`).

## Key Files

- `paleonews/__main__.py` — CLI 엔트리포인트, 파이프라인 통합
- `paleonews/db.py` — SQLite DB (articles, dispatches, users, memories, pipeline_runs, feeds, app_settings 테이블)
- `paleonews/config.py` — config.yaml 로딩 + DB 설정 overlay
- `paleonews/llm.py` — LLM provider 추상화 (anthropic/openai/claude_code)
- `paleonews/fetcher.py` — RSS 피드 수집 (feeds 테이블 기반), Article dataclass
- `paleonews/filter.py` — 키워드 접두사 매칭 + LLM 2차 필터 + 사용자별 키워드 필터
- `paleonews/crawler.py` — 기사 본문 크롤링 (readability)
- `paleonews/summarizer.py` — Claude API 한국어 요약, 브리핑 생성
- `paleonews/dispatcher/` — Telegram, Email, Webhook(Slack/Discord)
- `paleonews/bot.py` — Telegram 봇 데몬 (/start, /stop, /keywords, 챗봇 대화/메모리)
- `paleonews/web.py` — FastAPI 웹 Admin UI (대시보드, 기사/사용자 관리, 설정)
- `paleonews/templates/` — Jinja2 템플릿 (dashboard, articles, users, user_detail, settings)
- `config.yaml` — 베이스 설정 (피드 전용 도메인, 키워드, 모델, 채널, 로깅)
- `sources.txt` — 레거시 RSS URL 목록 (현재 피드는 DB `feeds` 테이블로 이관됨)
- `deploy/` — Dockerfile, docker-compose.yml, entrypoint.sh, nginx

## Commands

```bash
paleonews run          # 전체 파이프라인
paleonews fetch        # RSS 수집
paleonews filter       # 필터링
paleonews crawl        # 본문 크롤링
paleonews summarize    # 한국어 요약
paleonews send         # 전송 (다중 사용자별)
paleonews status       # DB 통계
paleonews users list   # 사용자 목록
paleonews users add <chat_id> [--name NAME] [--admin]
paleonews users remove <chat_id>
paleonews users keywords <chat_id> [keyword ...]  # * = 전체 수신
paleonews users activate <chat_id>
paleonews users deactivate <chat_id>
paleonews users email <chat_id> [email]            # 이메일 주소 설정
paleonews sources list                             # RSS 피드 소스 목록 (feeds 테이블)
paleonews sources add <url>
paleonews sources remove <url>
paleonews sources activate <url> / deactivate <url>
paleonews bot          # Telegram 봇 데몬
paleonews web          # FastAPI 웹 Admin UI 실행
```

## Development

- 가상환경: `~/venv/paleonews`
- 테스트: `~/venv/paleonews/bin/python -m pytest tests/ -v`
- PyInstaller 빌드: `entry.py`를 엔트리포인트로 사용
- 운영 배포: 단일 Docker 컨테이너 `paleonews`(entrypoint `all` 모드 = cron+bot+web 한 컨테이너, root 실행), 이미지 태그 = pyproject 버전. **prod = 빌드 호스트(m710q, 로컬 자기호스팅)** — 원격 GCP 아님, 배포는 로컬 실행
  - **배포·데이터 계약 정렬(0.3.0)**: 매니페스트(`deploy/deploy.toml`) + 동사(`preflight`/`build`/`deploy`/`smoke`/`rollback`) + `/healthz` + 백업 + git-free self-heal. 규약: `../devdocs/wiki/deploy-data-contract.md`, 운영 델타: `DEPLOY.md`
  - 레인: **`has_seed=false`** — 전 테이블이 운영 데이터(시스템 시드 없음). 불변식 = seed 명령 부재. **안전망 = 백업**(`scripts/backup_db.py` hourly + deploy.sh pre-deploy 스냅샷, retention 20)
  - 릴리스: repo 에서 `deploy/preflight.sh` → `scripts/release.sh [버전]`(= `deploy/build.sh` 빌드·push → 로컬 `/srv/paleonews/deploy-prod.sh`). host 스크립트는 이미지에서 self-heal 추출(`deploy/host/*`, `_extract_and_deploy.sh` — `bash -n`+`.previous`+원자 rename). 최초 1회만 `deploy/sync_to_srv.sh` 부트스트랩
  - deploy 엔진: pull → `.env` TAG → maintenance flag → pre-deploy 스냅샷(정지 후, `-wal`/`-shm`/`.mig` 스키마지문) → `up -d` → `/healthz` 대기 → DB 바인딩 게이트+쓰기 프로브(root) → smoke. 롤백 `/srv/paleonews/rollback.sh <이전> [--db=keep|restore]`(기본 keep=운영 데이터 보존)
  - 이미지는 멀티스테이지(`deploy/Dockerfile`): 네이티브 claude 바이너리(Node 불필요) + gosu(dormant, all 모드는 root 유지). host/*·backup_db.py 내장
  - DB: `/srv/paleonews/data/`(디렉터리 마운트 → `/app/data`, WAL 형제 동반), `jikhanjung` 소유(컨테이너 root 가 DAC 우회 쓰기). WAL 은 db.py `PRAGMA journal_mode=WAL` 로 이미 활성. `db.py:_migrate()` 가 기동 시 자동(가산 컬럼)
  - 구독 토큰 만료 시: 호스트 `claude setup-token` → `/srv/paleonews/apply_claude_token.sh <토큰>`(`.env`의 `CLAUDE_CODE_OAUTH_TOKEN` 갱신 + 컨테이너 재생성)

## Conventions

- DB 중복 방지: URL 기반 UNIQUE 제약
- 필터링: 전용 피드는 무조건 통과, 종합 피드는 키워드+LLM 판정
- 에러 처리: 단계별 독립 실행, 한 단계 실패해도 나머지 계속 진행
- 에러 알림: 파이프라인 실패 시 관리자 Telegram으로 통지
- 환경변수: API 키와 토큰은 `.env`에서 관리, 절대 커밋하지 않음

## Status

- Phase 1 (MVP) 완료: 기본 파이프라인 동작
- Phase 2 완료: LLM 필터, 크롤링, 다중 채널, 에러 알림
- Phase 3 완료: 로깅 체계화, 모니터링, 피드 소스 관리 CLI
- Phase 4 완료: 다중 사용자 지원 (users 테이블, 사용자별 키워드 필터, CLI 관리, Telegram 봇 데몬)
- Phase 5 완료: LLM provider 추상화(anthropic/openai/claude_code), Telegram 챗봇+메모리, FastAPI 웹 Admin UI, 이메일 전송, Docker+nginx 배포
- 운영 개선 (2026-05): Dockerfile 장애 수정 + config.yaml 호스트 마운트, RSS 소스 DB 이관(feeds 테이블), `app_settings` 기반 설정 overlay + `/settings`에서 provider·모델 편집(드롭다운)
- 운영 개선 (2026-06, 0.2.8): 구독 OAuth 장기 토큰(`CLAUDE_CODE_OAUTH_TOKEN`) 전환으로 발송 복구, Docker 멀티스테이지+네이티브 claude 바이너리로 이미지 1.13GB→615MB, `scripts/release.sh` 릴리스 자동화 — `devlog/20260624_013_token_renewal_native_claude_slim_image.md`
- 배포·데이터 계약 정렬 (2026-07, 0.3.0): fsis2026 동형 full parity — 매니페스트+동사+/healthz+백업+git-free self-heal. 계획 `devlog/20260714_P07_deploy_data_contract_alignment.md`, 구현 `devlog/20260714_014_deploy_data_contract_alignment.md`
- Phase 6 (Django 전환): 계획만 수립됨, 미착수 — `devlog/20260324_P06_django_migration_plan.md`

현재 버전: `0.3.0` (pyproject.toml)

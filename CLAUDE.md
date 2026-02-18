# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

고생물학 뉴스 집계 시스템. RSS 피드에서 기사를 수집 → 키워드+LLM 필터링 → 본문 크롤링 → Claude API로 한국어 요약 → Telegram/Email/Slack/Discord로 전송하는 자동화 파이프라인.

## Tech Stack

- **Language**: Python 3.11+
- **RSS Parsing**: feedparser
- **HTTP**: httpx
- **LLM**: Claude API (anthropic SDK) — 요약: Sonnet, 필터: Haiku
- **DB**: SQLite (WAL mode)
- **HTML Parsing**: readability-lxml
- **Telegram**: python-telegram-bot
- **Config**: YAML + .env (python-dotenv)

## Architecture

```
sources.txt → Fetcher → DB → Filter(키워드+LLM) → Crawler(본문) → Summarizer(Claude) → Dispatcher(다중채널)
```

파이프라인은 5단계: `fetch → filter → crawl → summarize → send`

## Key Files

- `paleonews/__main__.py` — CLI 엔트리포인트, 파이프라인 통합
- `paleonews/db.py` — SQLite DB (articles, dispatches 테이블)
- `paleonews/fetcher.py` — RSS 피드 수집, Article dataclass
- `paleonews/filter.py` — 키워드 접두사 매칭 + LLM 2차 필터
- `paleonews/crawler.py` — 기사 본문 크롤링 (readability)
- `paleonews/summarizer.py` — Claude API 한국어 요약, 브리핑 생성
- `paleonews/dispatcher/` — Telegram, Email, Webhook(Slack/Discord)
- `config.yaml` — 전체 설정 (피드, 키워드, 모델, 채널)
- `sources.txt` — RSS 피드 URL 목록 (10개)

## Commands

```bash
paleonews run          # 전체 파이프라인
paleonews fetch        # RSS 수집
paleonews filter       # 필터링
paleonews crawl        # 본문 크롤링
paleonews summarize    # 한국어 요약
paleonews send         # 전송
paleonews status       # DB 통계
```

## Development

- 가상환경: `~/venv/paleonews`
- 테스트: `~/venv/paleonews/bin/python -m pytest tests/ -v`
- PyInstaller 빌드: `entry.py`를 엔트리포인트로 사용

## Conventions

- DB 중복 방지: URL 기반 UNIQUE 제약
- 필터링: 전용 피드는 무조건 통과, 종합 피드는 키워드+LLM 판정
- 에러 처리: 단계별 독립 실행, 한 단계 실패해도 나머지 계속 진행
- 에러 알림: 파이프라인 실패 시 관리자 Telegram으로 통지
- 환경변수: API 키와 토큰은 `.env`에서 관리, 절대 커밋하지 않음

## Status

- Phase 1 (MVP) 완료: 기본 파이프라인 동작
- Phase 2 완료 (다중 사용자 제외): LLM 필터, 크롤링, 다중 채널, 에러 알림
- Phase 2 보류: 다중 사용자 지원 (Telegram 봇 명령어 기반 구독/키워드 관리)
- Phase 3 미착수: 로깅 체계화, 모니터링, 피드 소스 관리 CLI

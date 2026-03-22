# Telegram 챗봇 대화 기능, 웹 관리 UI, Docker 배포

**날짜**: 2026-03-22

## 배경

- Telegram 봇이 슬래시 명령어만 처리하고 있어 자유 대화가 불가능했음
- 사용자/설정 관리를 CLI로만 할 수 있어 불편
- 배포 환경 표준화 필요

## 변경 사항

### 1. Telegram 챗봇 대화 기능 (`paleonews/bot.py`)
- `MessageHandler`를 추가하여 일반 텍스트 메시지를 Claude API로 처리
- 고생물학 전문 AI 어시스턴트로서 사용자와 한국어 대화
- 사용자별 기억(memory) 시스템:
  - "기억해줘" → DB에 저장, 이후 대화에서 컨텍스트로 활용
  - "잊어줘" → 특정 기억 삭제
  - `/memories` — 저장된 기억 확인
  - `/forget` — 전체 삭제
- 챗봇 모델은 `config.yaml`의 `chat.model`로 설정 (기본: Haiku)

### 2. DB 스키마 변경 (`paleonews/db.py`)
- `memories` 테이블 추가 (user_id, content, created_at)
- `save_memory`, `get_memories`, `delete_memory`, `clear_memories` 메서드 추가
- `remove_user` 시 해당 사용자의 기억도 함께 삭제

### 3. 웹 관리 UI (`paleonews/web.py`, `paleonews/templates/`)
- FastAPI + Jinja2 기반
- 대시보드 (`/`): 기사 통계, 활성 사용자, 최근 파이프라인 실행 이력
- 사용자 관리 (`/users`): 추가/삭제/활성화/비활성화, 관리자 전환, 키워드 설정
- 설정 (`/settings`): 시스템 설정 조회, RSS 피드 소스 추가/삭제, 필터 키워드 목록
- 실행: `paleonews web [--host HOST] [--port PORT]`

### 4. Docker 배포 (`deploy/`)
- `Dockerfile`: Python 3.12-slim, lxml 의존성 포함
- `docker-compose.yml`: pipeline(수동/cron), bot(상시), web(상시) 3개 서비스
- `.env.example`: 환경변수 템플릿
- 데이터 영속성: `paleonews-data`, `paleonews-logs` 볼륨

### 5. 기타 변경
- `pyproject.toml`: fastapi, uvicorn, jinja2, python-multipart 의존성 추가
- `config.yaml`: `chat.model` 설정 추가
- `__main__.py`: `web` 서브커맨드 추가
### 6. crontab 버그 수정
- 기존: `0 8 * * * /home/jikhanjung/venv/paleonews/bin/python -m paleonews run >> ...`
- 수정: `0 8 * * * cd /home/jikhanjung/projects/paleonews && /home/jikhanjung/venv/paleonews/bin/python -m paleonews run >> ...`
- 원인: cron은 홈 디렉토리에서 실행되므로 상대 경로 `config.yaml`을 찾지 못함
- 로그에 `FileNotFoundError: Config file not found: config.yaml` 반복 확인

## 파일 목록

| 파일 | 변경 |
|------|------|
| `paleonews/bot.py` | 전면 재작성 — 대화 + 기억 기능 |
| `paleonews/db.py` | memories 테이블 + CRUD |
| `paleonews/web.py` | 신규 — FastAPI 웹 UI |
| `paleonews/templates/base.html` | 신규 — 레이아웃 |
| `paleonews/templates/dashboard.html` | 신규 — 대시보드 |
| `paleonews/templates/users.html` | 신규 — 사용자 관리 |
| `paleonews/templates/settings.html` | 신규 — 설정 |
| `paleonews/__main__.py` | web 서브커맨드 추가 |
| `pyproject.toml` | 웹 의존성 추가 |
| `config.yaml` | chat.model 설정 추가 |
| `deploy/Dockerfile` | 신규 |
| `deploy/docker-compose.yml` | 신규 |
| `deploy/.env.example` | 신규 |
| `deploy/README.md` | 신규 |

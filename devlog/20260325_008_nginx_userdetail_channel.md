# Nginx 리버스 프록시 통합, 사용자 상세/편집, 채널 선택

**날짜**: 2026-03-25

## 배경

- Docker 컨테이너가 호스트 포트를 직접 노출하고 있어 nginx를 거치지 않는 서비스가 있었음
- 웹 UI에서 사용자 목록만 볼 수 있고 상세 정보 확인/편집이 불가능했음
- `chat_id`라는 컬럼명이 모호하고 Telegram 없이는 사용자 등록 불가
- 뉴스 수신 채널(Telegram/Email)별 on/off 제어 불가
- 컨테이너 내부 cron이 환경변수 로드 실패로 파이프라인 미실행

## 변경 사항

### 1. Nginx 리버스 프록시 통합

모든 서비스를 nginx 리버스 프록시 뒤에 배치하고, Docker 포트를 `127.0.0.1`로만 바인딩하여 외부 직접 접근 차단.

| 외부 포트 | nginx → | Docker 매핑 | 서비스 |
|-----------|---------|-------------|--------|
| :80 | 정적 | /srv/www | 서비스 링크 페이지 |
| :8080 | proxy | 127.0.0.1:8100→8000 | paleonews |
| :8081 | proxy | 127.0.0.1:8101→8000 | dolfinserver |
| :8082 | proxy | 127.0.0.1:8102→5000 | naverland |
| :8083 | proxy | 127.0.0.1:8103→8000 | ghdb |
| :8084 | proxy | 127.0.0.1:8104→8000 | fsis |

**변경 파일:**
- `/srv/*/docker-compose.yml` — 포트를 `127.0.0.1:81xx`로 변경
- `/etc/nginx/sites-available/*.conf` — 5개 서비스별 리버스 프록시 설정
- `/srv/www/index.html` — 서비스 링크 페이지 (포트 업데이트)

### 2. 배포 스크립트 개선

`/srv/paleonews/deploy.sh`와 `docker-compose.yml`을 수정하여 `TAG` 기반 버전 관리로 전환.

- `docker-compose.yml`: `${IMAGE:-...latest}` → `honestjung/paleonews:${TAG:-0.1.2}`
- `deploy.sh`: 버전 인자 → `.env`의 `TAG` 업데이트 → `docker compose pull/down/up`
- 호스트 crontab에서 paleonews cron 제거 (Docker 내부 cron으로 대체)

### 3. Cron 실행 오류 수정

Docker 컨테이너 내부 cron이 파이프라인을 실행하지 못하는 문제 수정.

**원인:**
- `printenv` + `sed 's/^/export /'`로 생성한 `env.sh`에서 공백/특수문자 파싱 에러
- cron 파일에 `SHELL=/bin/bash` 미지정으로 `/bin/sh`에서 `source` 명령 실패

**수정 (`deploy/entrypoint.sh`):**
- `printenv | sed` → `export -p` (bash가 `declare -x KEY="value"` 형태로 자동 처리)
- cron 파일에 `SHELL=/bin/bash`와 `root` 사용자 명시

### 4. 사용자 상세/편집 페이지

웹 UI에 사용자 상세 페이지 추가.

**새 파일:**
- `paleonews/templates/user_detail.html` — 상세/편집 템플릿

**변경 파일:**
- `paleonews/web.py` — `GET /users/{user_id}` (상세), `POST /users/{user_id}/edit` (편집) 라우트
- `paleonews/db.py` — `update_user(**fields)` 메서드 추가
- `paleonews/templates/users.html` — 목록에서 행 클릭 시 상세 페이지 이동

**상세 페이지 구성:**
- 정보 편집 폼 (모든 필드 한 화면에서 수정)
- 기본 정보 읽기 전용 테이블
- 기억(memories) 목록
- 최근 발송 내역 (20건)
- 사용자 삭제 (위험 영역)

### 5. chat_id → telegram_chat_id 리네이밍 + 선택사항

Telegram 없이도 사용자 등록 가능하도록 변경.

**DB 변경:**
- `chat_id TEXT UNIQUE NOT NULL` → `telegram_chat_id TEXT UNIQUE` (nullable)
- 마이그레이션: `ALTER TABLE RENAME COLUMN` + 테이블 재생성 (NOT NULL 제거)

**코드 변경 (전체 리네이밍):**
- `db.py`: `get_user_by_chat_id()` → `get_user_by_telegram_id()`, `add_user(chat_id=)` → `add_user(telegram_chat_id=)`
- `bot.py`, `__main__.py`, `web.py`, `dispatcher/telegram.py`, 템플릿, 테스트 전체 변경
- CLI: `users add <chat_id>` → `users add --telegram <id> --email <email> --name <name>`
- CLI 식별자: `<chat_id>` → `<user_id>` (숫자 ID 기반)

### 6. 채널별 수신 선택

사용자별로 Telegram/Email 수신 여부를 개별 제어 가능하게 함.

**DB 변경:**
- `notify_telegram BOOLEAN NOT NULL DEFAULT 1` 컬럼 추가
- `notify_email BOOLEAN NOT NULL DEFAULT 1` 컬럼 추가

**전송 로직:**
- Telegram: `notify_telegram=0`이면 건너뜀
- Email: `get_email_users()` 쿼리에 `notify_email=1` 조건 추가

**웹 UI:**
- 사용자 상세 편집 폼에서 Telegram/Email 입력 옆에 "수신" 체크박스 표시
- 해당 채널 값이 있을 때만 체크박스 노출

### 이메일 발송 설정 안내

이메일 발송 기능은 코드상 구현되어 있으나 현재 비활성 상태. 활성화하려면:

1. **config.yaml** — `channels.email.enabled: true`, `sender: 본인gmail주소`
2. **.env** — `EMAIL_PASSWORD=앱비밀번호`
3. Gmail의 경우 [앱 비밀번호](https://myaccount.google.com/apppasswords) 생성 필요
4. 다른 SMTP 서버 사용 시 `smtp_host`, `smtp_port` 변경

## 버전 이력

| 버전 | 내용 |
|------|------|
| 0.1.2 | 사용자 상세/편집 페이지 추가 |
| 0.1.3~0.1.5 | 목록 UI 개선 (행 클릭, 상세 버튼) |
| 0.1.6 | Cron env.sh 수정 (export -p, SHELL=/bin/bash) |
| 0.2.0 | chat_id → telegram_chat_id 리네이밍 + nullable |
| 0.2.1 | 채널별 수신 선택 (notify_telegram, notify_email) |

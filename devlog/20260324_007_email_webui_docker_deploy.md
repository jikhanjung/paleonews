# 이메일 발송, 웹 UI 강화, Docker 단일 컨테이너 배포

**날짜**: 2026-03-24

## 배경

- 이메일 발송 기능이 골격만 있고 실제 동작하지 않았음
- 웹 관리 UI에 기사 목록/검색, 파이프라인 수동 실행, 출처별 통계가 없었음
- Docker 배포가 3개 컨테이너로 분리되어 있어 관리가 번거로웠음
- 배포 자동화 스크립트가 없었음

## 변경 사항

### 1. 이메일 발송 기능 구현

#### DB 스키마 (`paleonews/db.py`)
- `users` 테이블에 `email` 컬럼 추가
- 기존 DB 자동 마이그레이션 (`_migrate`에서 `email` 컬럼 존재 여부 확인 후 추가)
- `add_user()`에 `email` 파라미터 추가
- `update_user_email()` — 사용자 이메일 변경
- `get_email_users()` — 이메일이 등록된 활성 사용자 조회

#### EmailDispatcher (`paleonews/dispatcher/email.py`)
- HTML 뉴스레터 템플릿 추가 — 헤더, 기사 카드(제목/요약/출처/원문링크), 푸터
- `send_articles()` 메서드 — 기사 목록을 받아 HTML + plain text 대체 이메일 발송
- `_escape()` 유틸로 HTML 특수문자 이스케이프
- 기존 `send_briefing()` 호환 유지 (레거시)

#### 파이프라인 연동 (`paleonews/__main__.py`)
- `cmd_send()`의 Email 섹션을 사용자별 발송으로 전면 개편
- Telegram과 동일하게 사용자별 키워드 필터링 적용 후 발송
- config의 `recipients` 리스트 레거시 모드 병행 지원
- dispatch 레코드에 `user_id` 기록

#### CLI (`paleonews/__main__.py`)
- `paleonews users add <chat_id> --email user@example.com` — 사용자 추가 시 이메일 지정
- `paleonews users email <chat_id> [addr]` — 이메일 조회/설정/삭제 서브커맨드 추가
- `paleonews users list` — 이메일 주소 표시 추가

### 2. 웹 UI 강화

#### 기사 목록/검색 페이지 (`/articles`)
- `paleonews/templates/articles.html` 신규
- 제목(영문/한국어), 출처로 텍스트 검색
- 상태 필터: 전체 / 관련 기사 / 요약 완료 / 전송 완료
- 30건 단위 페이지네이션 (이전/다음 + 페이지 번호)
- 한국어 요약 펼쳐보기, 원문 링크
- `db.search_articles()` 메서드 추가 — 검색/필터/페이징 지원 쿼리

#### 파이프라인 수동 실행
- 대시보드 상단에 "파이프라인 실행" 버튼
- `POST /pipeline/run` — 백그라운드 스레드에서 파이프라인 실행 (UI 블로킹 없음)
- `GET /pipeline/status` — JSON API로 실행 상태 조회
- 실행 중 3초 간격 자동 폴링 → 완료 시 페이지 새로고침
- 중복 실행 방지 (실행 중일 때 버튼 비활성화)

#### 출처별 통계
- 대시보드 하단에 출처별 전체/관련/요약 건수 테이블
- 관련 기사 비율 프로그레스 바 시각화
- 기존 `db.get_source_stats()` 활용

#### 사용자 관리에 이메일 필드 추가
- 사용자 추가 폼에 이메일 입력 필드
- 사용자 목록 테이블에 이메일 컬럼
- 각 사용자별 이메일 인라인 편집/저장
- `POST /users/{id}/email` 엔드포인트

#### 네비게이션
- `base.html`에 "기사" 메뉴 링크 추가

#### Starlette 1.0 호환
- `TemplateResponse(name, {"request": request, ...})` →
  `TemplateResponse(request, name, {...})` 형식으로 전체 수정

### 3. Docker 단일 컨테이너 통합

#### entrypoint.sh 개편
- `all` 모드 추가: cron(백그라운드) + bot(백그라운드) + web(포그라운드) 통합 실행
- 기존 개별 모드(`cron`, `run`, `bot`, `web` 등)도 유지
- cron 환경변수 전달: `printenv`로 환경변수를 파일로 덤프 후 cron 작업에서 `source`

#### Dockerfile 수정
- `sed` 패턴 오류 수정: `file:.*logs/paleonews.log` → `file:.*` (따옴표 이중 삽입 문제)

### 4. 배포 자동화 (`/srv/paleonews/`)

#### 디렉토리 구조
```
/srv/paleonews/
├── .env              # 모든 설정 (API키, 포트, 스케줄 등)
├── docker-compose.yml
├── deploy.sh         # 배포 스크립트
├── data/
│   └── paleonews.db  # SQLite DB
└── logs/
```

#### docker-compose.yml
- 3개 서비스 → 1개 서비스(`paleonews`)로 통합
- 컨테이너 이름: `paleonews`
- `.env`에서 모든 설정 읽어옴 (IMAGE, WEB_PORT, PIPELINE_CRON, DATA_DIR, LOG_DIR, API 키 등)

#### deploy.sh
- `./deploy.sh` — .env에 저장된 이미지 버전으로 배포
- `./deploy.sh 0.1.1` — 특정 버전 지정 시 pull → 컨테이너 재시작 → .env의 IMAGE 자동 갱신
- 안전한 .env 파싱 (cron 스케줄의 `*` glob 확장 문제 회피)

#### Docker Hub
- 이미지: `honestjung/paleonews`
- 태그: `0.1.0`, `0.1.1`, `latest`

## 버그 수정

- **Dockerfile sed 패턴**: `file:.*logs/paleonews.log` 패턴이 원본의 닫는 따옴표를 남겨서 `"logs/paleonews.log""` 이중 따옴표 발생 → `file:.*`로 줄 전체 교체하도록 수정
- **Starlette 1.0 비호환**: `TemplateResponse` 호출 시그니처 변경 — dict의 `"request"` 키가 unhashable type 에러 유발 → 새 API 형식으로 전환

## 파일 변경 요약

| 파일 | 변경 |
|------|------|
| `paleonews/db.py` | email 컬럼, 마이그레이션, search_articles, email 관련 메서드 |
| `paleonews/dispatcher/email.py` | HTML 템플릿, send_articles, 전면 재작성 |
| `paleonews/__main__.py` | 사용자별 이메일 발송, email CLI 서브커맨드 |
| `paleonews/web.py` | articles/pipeline/source_stats 엔드포인트, Starlette 1.0 호환 |
| `paleonews/templates/base.html` | 네비게이션에 기사 링크 |
| `paleonews/templates/dashboard.html` | 파이프라인 실행 버튼, 출처별 통계, 자동 폴링 |
| `paleonews/templates/articles.html` | 신규 — 기사 목록/검색/페이징 |
| `paleonews/templates/users.html` | 이메일 컬럼, 이메일 편집 폼 |
| `deploy/Dockerfile` | cron 설치, sed 패턴 수정 |
| `deploy/entrypoint.sh` | all 모드 (통합 실행) |
| `deploy/docker-compose.yml` | 개발용 compose (3서비스 유지) |
| `/srv/paleonews/.env` | 배포 설정 파일 |
| `/srv/paleonews/docker-compose.yml` | 운영용 compose (단일 컨테이너) |
| `/srv/paleonews/deploy.sh` | 배포 자동화 스크립트 |

## 테스트 결과

- 기존 41개 테스트 전체 통과
- Docker 컨테이너 단일 실행 확인 (cron + bot + web)
- 웹 UI 4개 페이지 모두 HTTP 200 확인
- Docker Hub push/pull 정상

## 운영 현황

- 이미지: `honestjung/paleonews:0.1.1`
- 컨테이너: `paleonews` (단일)
- 웹 UI: `http://localhost:8080`
- DB: `/srv/paleonews/data/paleonews.db` (628건 기사, 1명 사용자)

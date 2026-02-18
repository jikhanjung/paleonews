# Phase 4: 다중 사용자 지원 구현

**날짜**: 2026-02-19

## 변경 사항

### DB 스키마 (`paleonews/db.py`)
- `users` 테이블 추가 (chat_id, username, display_name, is_active, is_admin, keywords)
- `dispatches` 테이블에 `user_id` 컬럼 추가 (기존 레코드는 NULL)
- `PRAGMA busy_timeout=5000` 추가 (봇 데몬과 파이프라인 동시 접근 대비)
- `seed_admin()`: TELEGRAM_CHAT_ID에서 관리자 자동 시딩 + 기존 dispatch 백필
- 사용자 CRUD: add_user, get_user, get_user_by_chat_id, get_active_users, get_all_users
- 사용자 키워드: update_user_keywords, get_user_keywords (JSON 배열 저장)
- `get_unsent_for_user()`: 사용자별 미전송 기사 조회
- `record_dispatch()`: user_id 파라미터 추가 (선택적, 기본값 None)

### 사용자별 키워드 필터 (`paleonews/filter.py`)
- `filter_articles_for_user()` 함수 추가
- keywords=None이면 전체 수신, 빈 리스트면 수신 없음
- title_ko/summary_ko를 우선 사용, 없으면 title/summary로 폴백

### 다중 사용자 전송 (`paleonews/__main__.py`)
- `cmd_send()` Telegram 섹션을 사용자 루프로 변경
- 각 사용자별 get_unsent_for_user → filter_articles_for_user → 전송
- 필터링으로 제외된 기사는 "filtered" 상태로 기록 (재처리 방지)
- Email/Slack/Discord는 기존 동작 유지 (user_id=NULL)

### CLI 사용자 관리 (`paleonews/__main__.py`)
- `paleonews users list/add/remove/keywords/activate/deactivate` 서브명령어 추가

### Telegram 봇 데몬 (`paleonews/bot.py`)
- `/start`: 자동 등록 또는 재활성화
- `/stop`: 비활성화
- `/keywords`: 키워드 조회/설정 (* = 전체 수신)
- `/help`: 명령어 안내
- `paleonews bot` 명령어로 실행

### 테스트 (`tests/test_users.py`)
- 18개 테스트 추가 (사용자 CRUD, 키워드 필터, 마이그레이션, 독립 dispatch)
- 기존 14개 테스트 모두 통과 (총 32개)

## 설계 원칙
- 파이프라인(fetch/filter/crawl/summarize)은 변경 없음
- 다중 사용자 로직은 전송 단계와 봇 데몬에만 적용
- 기존 단일 사용자 동작 완전 호환 (TELEGRAM_CHAT_ID 관리자로 자동 시딩)

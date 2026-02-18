# Phase 4: 다중 사용자 지원 구현 계획

**날짜**: 2026-02-19

## 목표

현재 PaleoNews는 단일 사용자(TELEGRAM_CHAT_ID) 전용 시스템. 다중 사용자를 지원하여 여러 Telegram 구독자에게 각자의 관심 키워드에 맞는 브리핑을 발송할 수 있도록 한다.

## 핵심 원칙

파이프라인(fetch/filter/crawl/summarize)은 변경 없음. 다중 사용자 로직은 **전송 단계**와 **봇 데몬**에만 적용.

## DB 스키마 변경

### users 테이블 추가

```sql
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      TEXT UNIQUE NOT NULL,
    username     TEXT,
    display_name TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT 1,
    is_admin     BOOLEAN NOT NULL DEFAULT 0,
    keywords     TEXT,          -- JSON 배열, NULL = 전체 수신
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
```

### dispatches 테이블에 user_id 컬럼 추가

- Telegram: user_id 설정
- Email/Slack/Discord: user_id = NULL (기존 동작 유지)

### 마이그레이션

- TELEGRAM_CHAT_ID → 관리자 사용자 자동 시딩
- 기존 Telegram dispatches에 관리자 user_id 백필
- PRAGMA busy_timeout=5000 추가

## 구현 단계

### Step 1: DB 레이어
- users 테이블, user_id 마이그레이션
- 사용자 CRUD 메서드
- per-user dispatch 메서드 (get_unsent_for_user)

### Step 2: 사용자별 키워드 필터링
- filter_articles_for_user() 함수 (전송 시 적용)
- 사용자 keywords가 NULL이면 전체 수신
- keywords가 있으면 제목/요약에 키워드 매칭

### Step 3: 다중 사용자 전송
- cmd_send()의 Telegram 섹션을 사용자 루프로 변경
- 각 사용자별로 unsent 기사를 필터링하여 전송

### Step 4: CLI 사용자 관리
- paleonews users list/add/remove/keywords/activate/deactivate

### Step 5: Telegram 봇 데몬
- paleonews/bot.py 신규
- /start: 자동 등록
- /stop: 비활성화
- /keywords: 키워드 관리
- paleonews bot 명령어로 실행

## 검증

1. 기존 + 신규 테스트 전체 통과
2. CLI 사용자 관리 동작 확인
3. 관리자에게 브리핑 발송 확인
4. 키워드 필터 적용 확인
5. 봇 /start 자동 등록 확인

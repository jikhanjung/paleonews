# Phase 3 구현 계획: 운영 안정화

> 작성일: 2026-02-18
> 상위 문서: `20260218_P01_paleonews_plan_draft.md`
> 선행: Phase 2 완료 (`20260218_002_phase2_implementation.md`)

## 목표

Phase 2까지 구현된 파이프라인의 운영 안정성을 높이기 위해:
1. 로깅 체계화 — 파일 로깅, 로그 로테이션, 레벨 관리
2. 모니터링 — 실행 이력 기록, 출처별 통계, 상세 상태 조회
3. 피드 소스 관리 CLI — 소스 추가/삭제/목록 조회

※ 사용자별 관심 키워드/분야 설정은 다중 사용자 지원과 함께 별도 진행 예정

---

## Step 1: 로깅 체계화

### 할 일

- 콘솔 + 파일 이중 로깅
- RotatingFileHandler로 로그 파일 로테이션 (크기 기반)
- config.yaml에서 로그 레벨, 파일 경로, 로테이션 설정

### config.yaml 추가

```yaml
logging:
  level: "INFO"           # DEBUG, INFO, WARNING, ERROR
  file: "logs/paleonews.log"
  max_bytes: 5242880      # 5MB
  backup_count: 3         # 최대 3개 백업
```

### 핵심 함수

```python
def setup_logging(config: dict):
    """Configure logging with console and optional file output."""
    # RotatingFileHandler + StreamHandler 설정
```

### 완료 기준

- 콘솔과 파일에 동시 로깅
- 로그 파일이 5MB 초과 시 자동 로테이션
- config에서 로그 레벨 변경 가능

---

## Step 2: 모니터링 (실행 이력 + 상세 통계)

### 할 일

- `pipeline_runs` 테이블 추가: 매 실행의 수집/필터/크롤/요약/전송 건수 기록
- 출처별 기사 통계 조회
- `paleonews status -v`로 상세 정보 출력

### DB 스키마 추가

```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    fetched     INTEGER DEFAULT 0,
    new_articles INTEGER DEFAULT 0,
    relevant    INTEGER DEFAULT 0,
    crawled     INTEGER DEFAULT 0,
    summarized  INTEGER DEFAULT 0,
    sent        INTEGER DEFAULT 0,
    errors      TEXT,
    status      TEXT NOT NULL DEFAULT 'running'
);
```

### 핵심 함수

```python
# db.py 추가
class Database:
    def start_run(self) -> int: ...
    def finish_run(self, run_id: int, **kwargs): ...
    def get_recent_runs(self, limit: int = 5) -> list[dict]: ...
    def get_source_stats(self) -> list[dict]: ...
```

### 출력 예시 (`paleonews status -v`)

```
전체 기사:   290건
관련 기사:   175건
요약 완료:   60건
전송 완료:   60건

--- 출처별 통계 ---
출처                                    전체  관련  요약
Nature                                  77     3     0
Fossils & Ruins News -- ScienceDaily    60    60    60
...

--- 최근 실행 이력 ---
  2026-02-18 13:51:57  [success]  수집:288 신규:2 관련:0 크롤:20 요약:20 전송:20
```

### 완료 기준

- 매 `run` 실행 시 이력이 DB에 기록됨
- `status -v`로 출처별 통계와 최근 실행 이력 확인 가능

---

## Step 3: 피드 소스 관리 CLI

### 할 일

- `paleonews sources list` — 피드 URL 목록 출력
- `paleonews sources add <URL>` — 피드 추가 (중복 검사)
- `paleonews sources remove <URL>` — 피드 삭제

### 핵심 함수

```python
def cmd_sources(config: dict, args):
    """Manage feed sources in sources.txt."""
    # list: 파일 읽어서 출력
    # add: 중복 체크 후 추가
    # remove: 해당 URL 행 삭제
```

### 완료 기준

- `sources list`로 현재 피드 목록 확인
- `sources add`로 새 피드 추가 (중복 시 경고)
- `sources remove`로 피드 삭제 (없으면 경고)

---

## 구현 순서

| 순서 | Step | 주요 산출물 | 의존성 |
|------|------|------------|--------|
| 1 | 로깅 체계화 | __main__.py, config.yaml | 없음 |
| 2 | 모니터링 | db.py, __main__.py | Step 1 |
| 3 | 피드 소스 관리 | __main__.py | 없음 |

---

## 완료 정의

Phase 3이 완료되었다고 판단하는 기준:

1. 파일 로깅이 동작하고 로테이션이 설정됨
2. 파이프라인 실행 이력이 DB에 기록됨
3. `status -v`로 출처별 통계와 실행 이력 조회 가능
4. CLI로 피드 소스 추가/삭제/조회 가능
5. 기존 테스트가 모두 통과

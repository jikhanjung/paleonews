# Phase 3 구현 완료: 운영 안정화

> 작성일: 2026-02-18

## 요약

Phase 3 계획서(`20260218_P04`)의 전체 항목을 구현했다. 로깅 체계화, 파이프라인 모니터링, 피드 소스 관리 CLI가 추가되었다.

---

## 구현 내역

### Step 1: 로깅 체계화

**변경 파일**: `paleonews/__main__.py`, `config.yaml`, `.gitignore`

- `setup_logging(config)` 함수 구현
  - 콘솔 + 파일 이중 로깅 (`StreamHandler` + `RotatingFileHandler`)
  - 로그 포맷: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
  - 로그 파일 디렉토리 자동 생성 (`mkdir -p`)
- `config.yaml`에 `logging` 섹션 추가
  - `level`: 로그 레벨 (기본 INFO)
  - `file`: 로그 파일 경로 (`logs/paleonews.log`)
  - `max_bytes`: 로테이션 크기 (5MB)
  - `backup_count`: 백업 파일 수 (3개)
- `.gitignore`에 `logs/` 추가

### Step 2: 모니터링 (실행 이력 + 상세 통계)

**변경 파일**: `paleonews/db.py`, `paleonews/__main__.py`

- `pipeline_runs` 테이블 추가 (Phase 2 에러 알림 구현 시 함께 추가됨)
  - 각 실행의 시작/종료 시간, 단계별 처리 건수, 에러 메시지, 상태 기록
- DB 메서드 추가
  - `start_run() -> int`: 실행 시작 기록, run_id 반환
  - `finish_run(run_id, **kwargs)`: 실행 완료 기록 (건수, 에러, 상태)
  - `get_recent_runs(limit=5)`: 최근 실행 이력 조회
  - `get_source_stats()`: 출처별 기사 통계 (전체/관련/요약 건수)
- `cmd_status(db, verbose)` 함수 확장
  - 기본: 전체/관련/요약/전송 건수 출력
  - `-v` 옵션: 출처별 통계 테이블 + 최근 실행 이력 추가 출력
- 각 파이프라인 커맨드가 처리 건수를 반환하도록 변경
  - `cmd_fetch() -> tuple[int, int]` (수집, 신규)
  - `cmd_filter() -> int` (관련)
  - `cmd_crawl() -> int` (크롤링)
  - `cmd_summarize() -> int` (요약)
- `_run_pipeline()`에서 run_id 추적 및 완료 시 `finish_run()` 호출

### Step 3: 피드 소스 관리 CLI

**변경 파일**: `paleonews/__main__.py`

- `cmd_sources(config, args)` 함수 구현
  - `paleonews sources list`: 현재 피드 URL 목록 (번호 포함) 출력
  - `paleonews sources add <URL>`: 중복 검사 후 피드 추가
  - `paleonews sources remove <URL>`: 해당 URL 행 삭제
- argparse에 `sources` 서브커맨드 및 하위 파서 추가
  - `list`, `add` (url 인자), `remove` (url 인자)

---

## 출력 예시

### `paleonews status`

```
전체 기사:   290건
관련 기사:   175건
요약 완료:   60건
전송 완료:   60건
```

### `paleonews status -v`

```
전체 기사:   290건
관련 기사:   175건
요약 완료:   60건
전송 완료:   60건

--- 출처별 통계 ---
출처                                    전체  관련  요약
----------------------------------------------------------
Nature                                  77     3     0
Fossils & Ruins News -- ScienceDaily    60    60    60
...

--- 최근 실행 이력 ---
  2026-02-18 13:51:57  [success]  수집:288 신규:2 관련:0 크롤:20 요약:20 전송:20
```

### `paleonews sources list`

```
피드 소스 (10개):
  1. https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science
  2. https://www.sciencedaily.com/rss/fossils_ruins.xml
  ...
```

---

## 설정 파일 변경 요약

### config.yaml 추가 항목

```yaml
logging:
  level: "INFO"
  file: "logs/paleonews.log"
  max_bytes: 5242880      # 5MB
  backup_count: 3
```

### .gitignore 추가 항목

```
logs/
```

---

## 파이프라인 변경

```
Phase 2: fetch → filter → crawl → summarize → send + 에러 알림
Phase 3: (동일) + 파일 로깅 + 실행 이력 기록 + 소스 관리 CLI
```

---

## 다음 단계

- 다중 사용자 지원 (Telegram 봇 명령어 기반 구독/키워드 관리)
- 스케줄링 고도화 (cron 외 옵션)
- 웹 대시보드 (선택)

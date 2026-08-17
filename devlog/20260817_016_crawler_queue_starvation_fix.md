# 크롤 큐 기아(starvation) 복구 — 6개월간 본문 크롤 0건 (0.3.4)

**날짜**: 2026-08-17
**대상**: `paleonews/crawler.py`, `paleonews/db.py`, `paleonews/__main__.py`, `config.yaml`
**결론**: 크롤러 자체는 멀쩡했다. **큐 정렬이 없어서** 죽은 URL 48건이 신규 기사를 6개월간 굶겼다.

## 발견

0.3.3 배포 후 운영 상태를 점검하던 중 `pipeline_runs` 의 `crawled` 컬럼이 **최근 6회차 전부 0** 인 것을 발견.
DB 를 확인하니:

```
sqlite> select sum(body is not null), count(*), max(case when body is not null then fetched_at end) from articles;
125|2948|2026-02-18T12:42:20
```

- 최근 30일 관련 기사 **118건 중 body 보유 0건**
- 본문이 마지막으로 채워진 것은 **2026-02-18** — 즉 Phase 2 개발 직후부터 죽어 있었다

파이프라인은 매 회차 `success` 로 끝났고 크롤 실패는 `logger.debug` 로 삼켜져 있어서, 6개월간 아무 신호도
나오지 않았다. 그 사이 모든 한국어 요약은 RSS 제목+발췌만 보고 생성됐다(`summarizer.py` 는 body 가
100자 미만이면 조용히 발췌 모드로 폴백). 실제 요약 길이 220~260자가 그 증거.

## 원인

```python
# db.py (before)
def get_uncrawled(self) -> list[dict]:
    rows = self.conn.execute(
        "SELECT * FROM articles WHERE is_relevant = 1 AND body IS NULL"   # ORDER BY 없음
    ).fetchall()

# crawler.py (before)
targets = uncrawled[:max_crawl]        # max_per_run: 20
...
if body: db.save_body(...)             # 실패는 아무것도 기록하지 않음
```

세 가지가 겹쳤다:

1. **ORDER BY 부재** → SQLite 가 rowid 오름차순으로 돌려주므로 **가장 오래된 것부터** 나온다.
2. 큐 맨 앞 **48건이 전부 `academic.oup.com`**(2026-02-18 수집분). Cloudflare 로 **403** — 실측 확인.
3. **실패 기록이 없음** → 재시도 제한이 없다. `max_per_run: 20` 이라 매일 밤 같은 20개 죽은 URL 만
   두드리고 큐는 한 칸도 전진하지 못했다.

전형적인 head-of-line blocking. 크롤러 코드 자체는 정상이라, 오늘자 phys.org / sciencedaily URL 로
직접 돌려보면 둘 다 200 에 본문 5000자를 정상 추출한다.

## 수정

**큐 (`db.get_uncrawled`)** — 세 가지를 바꿈:

```python
WHERE is_relevant = 1 AND body IS NULL AND summary_ko IS NULL AND crawl_attempts < ?
ORDER BY id DESC
```

- `ORDER BY id DESC` — **신규 우선**. 오늘 기사가 어제 실패에 인질로 잡히지 않는다.
- `summary_ko IS NULL` — body 는 `summarizer.py` 에서만 소비된다(전 코드베이스 grep 확인). 이미 요약이
  끝난 기사를 뒤늦게 크롤해봐야 쓸 데가 없으므로 큐에서 제외 → 기존 백로그 166건이 즉시 사라진다.
- `crawl_attempts < max_attempts` — 영구 실패 URL 은 은퇴.

**실패 기록** — `db.record_crawl_failure()` 신설, `crawler.crawl_articles()` 가 body 를 못 받으면 호출.
스키마 가산 컬럼 `articles.crawl_attempts INTEGER NOT NULL DEFAULT 0`, `_migrate()` 자동 처리.

**관측성** — 이게 6개월 숨은 진짜 이유라서 같이 고침:
- `logger.debug("Failed to crawl %s")` → `logger.warning("Failed to crawl %s: %s", url, e)` (예외 내용 포함)
- content-type 불일치 / 추출 100자 미만 스킵도 warning
- 대상이 있는데 **전건 실패면 `logger.error`** — 같은 장애가 재발하면 이번엔 로그에 남는다

**설정** — `config.yaml` 에 `crawler.max_attempts: 3`.

## 곁다리 수정

`_run_pipeline` 이 `run_data["sent"]` 에 `db.get_stats()["sent"]`(전체 누적 dispatch 수)를 그대로
넣고 있었다. 마지막 회차 값 784 = dispatches 테이블 전체 개수. 전송 전후 스냅샷 차이로 교체해
회차 증분을 기록하게 함. 과거 행은 누적값 그대로 남는다.

## 검증

- 유닛 테스트 `tests/test_crawler.py` 6종 신설(정렬, 요약분 제외, 시도 상한 은퇴, 실패 카운트,
  마이그레이션, 그리고 **기아 회귀 테스트** — 죽은 URL 2건 + 슬롯 2개 상황에서 신규 2건이 크롤되는지).
  전체 스위트 48 → **54 passed**.
- prod DB 사본(`backup/paleonews_20260817_13.sqlite3`)에 다음 회차 상태를 재현해 **실 네트워크로** 크롤:
  살아있는 URL 2건은 본문 5000자 저장, OUP 죽은 URL 은 `crawl_attempts=1` 기록 후 다음 회차 큐에 잔류
  (3회 후 은퇴). 백로그는 `summary_ko IS NULL` 조건으로 큐 크기 0 — 의도대로.

## 배포 후 확인

다음 파이프라인 실행은 23:00 UTC(08:00 KST). 그 뒤:

```sql
select crawled from pipeline_runs order by id desc limit 1;                       -- > 0 이어야 함
select count(*) from articles where body is not null and fetched_at > date('now','-2 days');
```

## 교훈

`/healthz` 200 과 `pipeline_runs.status = success` 는 **파이프라인이 일을 했다는 증거가 아니다**.
0.3.3(템플릿 누락 500)도 같은 형태였다 — smoke 는 통과하는데 실제 산출물이 비어 있는 유형.
단계별 산출량이 0 이면 성공으로 처리하지 말고 소리를 내야 한다.

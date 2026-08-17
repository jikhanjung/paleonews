# P08 — paleonews · naverland Django 표준화 계획 (통합 아님)

**날짜**: 2026-08-17
**대상**: `~/projects/paleonews`(FastAPI 0.3.4), `~/projects/naverland`(Flask 0.1.15)
**결정**: **둘 다 Django 로 전환하되 repo 는 분리 유지.** 단일 프로젝트 통합은 하지 않는다.
**선례**: `fsis2026`(Django 5.2 + 배포계약 레퍼런스), 그 외 `cdGTS`·`strati2026`·`fcmanager`·`dolfinserver`
**관련**: `devlog/20260714_015_p06_django_migration_reevaluation.md`(P06 보류), `../devdocs/wiki/deploy-data-contract.md`

---

## 0. 결정과 근거

### 통증의 정체
"자잘한 프로젝트를 **서로 다른 프레임워크로** 여러 개" — 진짜 비용은 repo 개수가 아니라
**프레임워크 이질성으로 인한 컨텍스트 스위칭**이다. 이 호스트의 5개 프로젝트가 전부 Django인데
paleonews(FastAPI)와 naverland(Flask)만 예외다. 스택을 하나로 만들면 repo 가 둘이어도 머릿속 모델은 하나다.

### 왜 통합하지 않는가
1. **두 프로젝트의 미래가 갈린다.** paleonews 는 이미 멀티유저로 지어져 있다(`users` per-user 키워드·채널,
   `memories`, `dispatches.user_id`) — SaaS 뼈대가 실재한다. 게다가 **요약은 기사당 1회라 사용자 수에
   비례하지 않는다**(팬아웃만 늘어남) = SaaS 에 유리한 비용 구조. 반면 naverland 는 인증도 사용자 개념도
   없는 개인 도구이고 네이버 스크래핑이라 ToS 민감도가 있다. 외부 노출 제품 안에 들고 다닐 물건이 아니다.
2. **통합 DB 면 남의 이메일과 개인 땅 북마크가 한 파일에 들어간다.**
3. **통합은 일방향 문, 표준화는 아니다.** 그리고 *Django 프로젝트 둘을 나중에 합치는 비용*은
   *FastAPI 와 Flask 를 지금 합치는 비용*보다 훨씬 싸다. 표준화를 먼저 하면 선택지가 둘 다 남는다.

### 통합했을 때 실제로 줄었을 것 (참고 — 포기하는 몫)
nginx conf 2→1, `/srv` 스크립트 9+9→9, 크론 4→3, 컨테이너 2→1, 버전 체계 2→1.
대신 매일 02:00 크롤 3분간 두 서비스가 같이 내려가고(naverland 는 단일 라이터 보장을 위해
컨테이너를 내린다), 백업 복원이 전부-아니면-전무가 된다. **이 몫은 나중에 회수 가능하다** — §6.

---

## 1. 실측 (2026-08-17)

| | paleonews | naverland |
|---|---|---|
| 웹 | FastAPI + Jinja2 (서버 렌더) | Flask JSON API + 정적 SPA |
| LOC | 3,443 | 3,477 |
| DB | SQLite 7테이블 / articles 2,948 | SQLite 8테이블 / snapshots 39,860 · current 2,808 |
| 배경작업 | 컨테이너 cron 파이프라인 + Telegram bot 데몬 | **호스트** cron Playwright 크롤러 (down→크롤→up) |
| 인증 | 없음 (Telegram chat_id 기반 users) | 없음 |
| 테스트 | 54 passed | **0** |
| 버전 | `pyproject.toml` semver | `VERSION` 파일 |
| 계약 준수 | 매니페스트·동사·healthz·백업 ✓ / **백업 검증 ✗** | 동일 ✓ / **백업 검증 ✗** |

### 대체 불가능한 데이터
- naverland `bookmarks`(3행) — 크롤로 복구 불가능한 **유일한 순수 수기 데이터**(메모). 키가 `parcel_key`.
- naverland `article_snapshots`(39,860) — **시계열이라 소급 재수집 불가**. 사실상 대체 불가로 취급.
- paleonews `users`·`memories`·`app_settings`, 그리고 `summary_ko`(재생성에 LLM 비용).

계약 문서가 **두 프로젝트를 백업 검증 미준수로 이름 붙여 놓았다**(5개 중 나머지 3개는 상환 완료).

---

## 2. 무엇을 공유하나 — 코드가 아니라 규약

집의 다른 5개 프로젝트도 플랫폼 코드를 **공유하지 않고 복사**한다(백업 검증 이식 때 cdGTS·fsis2026·
fcmanager 가 같은 날 각자 이식했고 서로를 몰랐다). 그 방식을 따른다.

| 항목 | 통일 대상 |
|---|---|
| 스택 | Django 5.2 + SQLite(WAL, `transaction_mode=IMMEDIATE`) |
| 프로젝트 구조 | `config/settings.py` + `manage.py` + 앱 디렉터리 (fsis2026 형) |
| 배포 | `deploy.toml` 매니페스트 + 동사(preflight/build/deploy/smoke/rollback) + `/healthz` + self-heal — **이미 둘 다 준수** |
| 백업 | `backup_db.py` + **스냅샷 검증 + 실패 시 prune 금지**(부채 상환) |
| 버전 | `pyproject.toml` semver 로 통일 (naverland `VERSION` 파일 폐기) |
| 문서 | `CLAUDE.md` · `DEPLOY.md`(append-only) · `devlog/` |

**공유하지 않는 것**: DB, 컨테이너, 이미지, `/srv` 디렉터리, nginx conf, 포트(8100/8102). 전부 현행 유지.

---

## 3. 단계 계획

### P0 — 선행 안전망 (두 방향 어디로 가든 순이득, 전환과 무관하게 값어치 있음)

1. **naverland 특성화 테스트(characterization test)** — 이 계획 전체에서 가장 중요한 한 걸음.
   현행 Flask 19개 엔드포인트의 응답을 운영 DB 사본으로 떠서 골든 파일로 고정한다.
   반드시 포함: 중복 묶기(`_group_duplicates`), 평당가·통계 모수, 변동일 필터(KST/UTC 경계), 지목 필터.
   *근거: 730줄에 테스트 0개인데 최근 devlog 3건이 전부 이 영역의 버그 수정이다. 테스트 없이 ORM 으로
   옮기면 값이 조용히 바뀌고, 그걸 알아챌 방법이 없다.*
2. **백업 검증 선상환** — 양쪽 `backup_db.py` 에 스냅샷 검증 + 실패 시 prune 금지.
   전환 중엔 백업이 유일한 되돌림 수단이므로 전환 **전에** 끝나야 한다.
   (cdGTS 0.1.68 · fsis2026 0.5.85 · fcmanager 0.6.24 에 있는 코드를 이식)
3. retention granularity 점검(`RETAIN_COUNT × 주기 ≥ 오프사이트 간격`).

**완료 기준**: 골든 테스트가 현행 Flask 에서 전부 통과. 양쪽 백업이 검증된 스냅샷만 채택.

### P1 — naverland → Django (먼저 하는 쪽)

먼저 하는 이유: LLM·구독 빌링·봇 데몬이 없어 **장애 반경이 작고**, ORM+테스트 실익은 더 크다.
paleonews 전환에서 쓸 이관 레시피를 낮은 위험으로 먼저 검증하는 의미도 있다.

1. `inspectdb` → 8테이블 모델. `Meta.db_table` 로 **기존 테이블명 고정**, FK 정리.
2. **초기 마이그레이션은 `--fake-initial`.** 39,860 스냅샷 위에 CREATE TABLE 이 돌면 안 된다. 사본 리허설 필수.
   `bookmarks` 는 별도 dump 후 대조.
   - 🔧 이관 김에 갚을 것: `articles_current.status` 가 CREATE TABLE 에 빠져 있어 **백업에서 새 DB 로
     복구하면 크롤러 첫 run 에 즉사**하는 잠복 버그(운영 DB 엔 수동 ALTER 로만 존재). 모델에 넣으면 해소.
3. Flask 19 엔드포인트 → Django view. **골든 diff 0 이 배포 조건.**
   `_group_duplicates()` 같은 파이썬 헬퍼는 그대로 옮긴다(가격이 TEXT 라 SQL 재작성 금지).
4. 크롤러 → `manage.py crawl_naver`. **호스트 실행 유지** — Playwright 를 이미지에 넣지 않는다.
   `run-crawler.sh` 의 down→크롤→up 단일 라이터 규율 **무변경 이식**(trap 복구 포함).
   호스트 venv 에 Django 추가 + `DJANGO_SETTINGS_MODULE`·`DATABASE_PATH` 고정.
5. static SPA(1,603줄)는 `staticfiles` 로 서빙만 바꾼다. **HTML/JS 무수정.**

**완료 기준**: 골든 diff 0 · 크롤 1회 정상 · `/healthz` 행 수 일치 · 구 이미지 폐기.
**되돌리기**: 이미지 태그 롤백 + 구 Flask 이미지 재기동(`--fake-initial` 이라 스키마 무변경).

### P2 — paleonews → Django

1. `inspectdb` + `--fake-initial` (P1 과 같은 규율). `db.py:_migrate()` → Django migration 으로 대체.
2. `web.py` 5화면 → Django admin + 커스텀 뷰. **admin 이 안 덮는 것**(P06 사유 ③, 여전히 유효):
   파이프라인 실행 버튼·상태 폴링(`/pipeline/run`, `/pipeline/status`), provider·모델 드롭다운
   (`app_settings` overlay) → admin action + 전용 뷰로 명시 재작성.
3. `app_settings` overlay 는 **Django settings 로 옮기지 않는다**(P06 사유 ④). 모델로 남기고 접근자만 유지.
4. 파이프라인 5단계 → `manage.py run_pipeline`(+ 단계별 서브명령). cron 항목 무변경.
5. **단일 컨테이너 all 모드(cron+bot+web, root) 유지, 서비스 분리 금지**(P06 사유 ②).
   `CLAUDE_CODE_OAUTH_TOKEN` 구독 빌링 표면 무변경 — **`ANTHROPIC_API_KEY` 가 env 에 들어가면 깨진다.**
6. 54개 테스트 이식(순수 함수 테스트는 거의 그대로 돈다).

**완료 기준**: 파이프라인 1회 완주(fetch→send) + 텔레그램 실수신 + 54 테스트 통과 + 웹 5화면 200 + 요약 1건 구독 과금 확인.

### P3 — 규약 정합
버전 체계 통일, `CLAUDE.md`/`DEPLOY.md`/계약 기록(`deploy-data-contract-record.md`) 갱신,
naverland `HANDOFF.md` 정리.

---

## 4. SaaS 문을 열어두기 위해 지금 정할 것 (paleonews)

지금 멀티테넌시를 **구현하지 않는다**. 다만 나중에 재작업이 되지 않도록 P2 에서 이것만 정해둔다.

| 항목 | 지금 결정 | 이유 |
|---|---|---|
| `users` ↔ Django `auth.User` | `User` **1:1 Profile** 로 모델링(지금은 Profile 만 채워도 무방) | 나중에 가입을 붙일 때 테이블 재설계가 안 생긴다 |
| 테넌트 스코프 | `articles`·`feeds` 는 **공용**(테넌트 무관), `dispatches`·`memories`·키워드는 사용자별 — 현 구조 유지 | 이게 SaaS 비용 구조의 핵심(요약 1회, 팬아웃 N). 흐트러뜨리지 않는다 |
| LLM provider | `llm.py` 추상화 유지 | API 빌링 전환이 설정 변경만으로 끝난다 — 이미 좋은 상태 |
| admin 로그인 | 도입 (Django auth) | 도입하는 순간 **`django_session` 위생 의무**(계약 MUST)가 생긴다 → §5 |
| PII | `users.email` 존재 | 백업 반출 시 세션 토큰과 함께 위생 대상 |

---

## 5. 위험과 완화

| 위험 | 실체 | 완화 |
|---|---|---|
| **운영 데이터 파손** | 초기 마이그레이션이 CREATE TABLE 을 돌리면 39,860 스냅샷·2,948 기사가 날아간다 | `--fake-initial` + 사본 리허설 + P0 검증된 백업 + pre-deploy 스냅샷 |
| **naverland 로직 회귀** | 테스트 0개인 730줄. 중복 묶기·평당가·KST 경계는 최근에도 틀렸던 곳 | P0 골든 테스트가 **선행 조건**. diff 0 아니면 배포 금지 |
| **구독 빌링 파손** | `ANTHROPIC_API_KEY` 유입·서비스 분리 시 크레딧 과금으로 샌다 | 단일 컨테이너·env 무변경을 제약으로 못박고, 배포 후 실제 요약 1건으로 확인 |
| **롤백 규칙 약화** | 지금은 가산 컬럼뿐이라 `--db=keep` 이 항상 안전. Django migration 이 들어오면 **"직전 배포에 migration 있으면 keep 금지"** 가 처음으로 발동 | 매니페스트에 명시 + migration 포함 릴리스는 `DEPLOY.md` 에 표시 |
| **`django_session` 위생 (신규 의무)** | admin 로그인 도입 시 bearer 토큰 테이블이 생긴다. 계약 MUST — 운영 DB 사본이 호스트를 떠날 때 삭제. `SECRET_KEY` 가 달라도 안 막힌다 | 백업/반출 경로에 초크포인트 1곳(fsis2026 0.5.87 형) |
| **크롤러 호스트 실행 복잡화** | 관리 명령이 되면 호스트 venv 에 Django + settings + DATABASE_PATH 필요 | self-heal 추출 범위 확대 + `run-crawler.sh` 가 env 고정 |
| **단일 라이터 규율 상실** | naverland 는 컨테이너를 내리고 크롤한다 | `run-crawler.sh` 무변경 이식 |

---

## 6. 나중에 통합하고 싶어지면

둘 다 Django 가 된 뒤라면 통합은 **훨씬 싼 작업**으로 남는다 — 참고용으로만 기록:

- 앱 디렉터리 이동 + `INSTALLED_APPS` 합치기 + urlconf 를 경로 prefix 로 병합.
- DB 는 `ATTACH` 후 테이블 복사(**테이블명 충돌 없음** — 확인함: paleonews `articles/dispatches/users/
  memories/pipeline_runs/feeds/app_settings` vs naverland `runs/articles_current/article_snapshots/
  article_details/article_events/bookmarks/regions/tracked_areas`).
- 그때 치르는 대가: 매일 02:00 크롤 3분간 동반 다운, 백업 복원이 전부-아니면-전무(테이블 스코프 복원은
  수작업), paleonews SaaS 포기.

즉 **지금 통합을 안 해도 잃는 선택지는 없다.** 반대 방향(통합 후 분리)은 그렇지 않다.

---

## 7. 미결

1. **순서 확인** — naverland 선행을 권장(반경 작음 + 레시피 검증). paleonews 선행을 원하시면 P1↔P2 교체.
2. **admin 로그인 도입 여부** — 도입 권장(SaaS 문 + 실제 관리 UI). 대가는 §5 세션 위생 의무.
3. **P0 만 먼저 하고 재판단할지, P1 까지 이어서 갈지.**
4. paleonews SaaS 를 실제로 추진할지는 **이 계획의 범위 밖**. P2 는 그 문을 닫지 않는 선에서만 설계한다.

# 배포·데이터 계약 정렬 (Full Parity) — 계획

**날짜**: 2026-07-14
**성격**: 계획(P) 문서. cross-project 배포·데이터 계약(`../devdocs/wiki/deploy-data-contract.md`)에 paleonews를 fsis2026과 **동형(full parity)**으로 정렬한다.

## 배경 (왜)

계약 문서는 1인-운영 ~30개 프로젝트를 **동일한 배포 인터페이스**(매니페스트 + 동사 + 불변식 + 백업)로 균질화해 인지 부하를 없애기 위한 규약이다. 활성 3개(cdGTS·fsis2026·fcmanager)는 이미 정렬됐고, paleonews만 제각각이다.

paleonews의 실제 리스크는 계약이 겨냥하는 종류다: **0.2.8 devlog(6/21 장애, [[20260624_013_token_renewal_native_claude_slim_image]])** — 요약이 전건 실패해도 `pipeline_runs.status`가 `success`로 찍혀 겉으론 정상처럼 보였다. 계약의 안전망(pre-deploy 스냅샷 + hourly 백업 + smoke 검증)이 이런 조용한 손실·실패를 잡는다.

**데이터 레인**: paleonews는 **운영 데이터가 전부**(articles/dispatches/users/memories/feeds/app_settings)이고 시스템 시드 레인이 없다 → **`has_seed=false`**(fcmanager 선례). 불변식은 seed 명령의 **부재**로 성립하고, **백업이 유일한 안전망**이다. feeds는 원래 sources.txt(개발자 목록)였으나 이제 웹/CLI로 운영자가 관리 → 운영 데이터로 분류.

## 스택 차이 (적응 포인트)

paleonews는 Django가 아니라 **FastAPI+CLI, raw sqlite3, Django 마이그레이션 없음**. 단일 컨테이너 "all" 모드(cron + telegram bot + web).

이미 유리한 점(컷오버 불필요):
- **DB 디렉터리 마운트** — `/srv/paleonews/data:/app/data`, WAL 형제 동반. fsis가 겪은 파일→디렉터리 전환 불필요.
- **WAL 이미 활성** — `db.py`의 `PRAGMA journal_mode=WAL`. WAL+디렉터리 마운트 "한 세트" 이미 충족.
- **버전 단일 소스** — `pyproject.toml`. `/healthz`·smoke는 `importlib.metadata.version("paleonews")`로 읽음.
- **migrate 동사** — `db.py:_migrate()`가 `init_tables()`에서 매 기동 시 자동(가산 컬럼만, 하위호환). 컨테이너 기동으로 성립.

## 산출물

### A. 선언층
1. `deploy/deploy.toml` — `contract_version=1`, `instance="paleonews"`, `image="honestjung/paleonews"`, `target="m710q"`(prod=빌드 호스트, 로컬 자기호스팅 — 계획 초안의 dolfinid 는 오류, 구현 중 정정), `has_seed=false`, `services=["paleonews"]`, `rollback_db="keep"`, `db_path="/srv/paleonews/data/paleonews.db"`, `health_url="/healthz"`, `health_probe="http://127.0.0.1:8100/healthz"`. `[verbs]` 매핑, `seed="(없음)"`. `[targets.prod]`.
2. `DEPLOY.md`(루트) — 릴리스별 append-only 운영 델타 + 레인 경계(전 테이블 운영, seed 없음) + 불변식 요약. preflight가 출력.

### B. 동사 — 빌드 호스트(m710q)
3. `deploy/build.sh` — `X.Y.Z [--fast]`: (pytest) → pyproject 버전 bump+조건부 커밋 → build → push `:X.Y.Z`+`:latest`.
4. `deploy/preflight.sh` — 위험 표면 diff(`deploy/`·`.env`·`config.yaml`·`Dockerfile`·`entrypoint.sh`·`db.py`) + **seed 냄새 lint**(WHERE 없는 대량 `DELETE`/`.all().delete()`, CLI에 `seed` 서브파서 존재 — `has_seed=false`라 깨끗해야 정상) + DEPLOY.md 출력.
5. `deploy/remote-prod.sh` — `exec ssh <PROD_HOST> /srv/paleonews/deploy-prod.sh "$@"`.
6. `deploy/sync_to_srv.sh` — 최초 1회 부트스트랩(host 스크립트 `/srv/paleonews`에 `cp -p`). 이후 self-heal.
7. `scripts/release.sh`(수정) — `build.sh`→`remote-prod.sh` 얇은 오케스트레이터로 재편. repo→/srv 직접 복사 제거(self-heal로 대체).

### C. 동사 — 운영 호스트(m710q 로컬), 이미지 내장 + self-heal
8. `deploy/host/deploy-prod.sh` / `deploy-dev.sh` — 2줄 래퍼(`DEPLOY_SNAPSHOT=1`/`0` → `exec _extract_and_deploy.sh`).
9. `deploy/host/_extract_and_deploy.sh` — git-free 추출: pull → create → `.new`로 cp → `bash -n` → `.previous` → 원자 `mv -f` → 자기교체 → `exec deploy.sh`.
10. `deploy/host/deploy.sh`(엔진, fsis 7단계 적응): pull → `.env` TAG sed(현 로직 재사용) → maintenance flag(경량) → **pre-deploy 스냅샷**(`down` 후 `cp -p` DB + `-wal`/`-shm` + `.mig` 스키마 지문, retention 20) → `up -d`(전 서비스) + liveness 루프 `/healthz` → **DB 바인딩 게이트 + 쓰기 프로브** → `smoke.sh`.
11. `deploy/host/smoke.sh` — `/healthz` 200 + stdlib python3 JSON 검증(version 일치·db true·counts.articles≥0).
12. `deploy/host/rollback.sh` — `--db=keep`(기본, 이미지만 전환) | `restore`(정지 후 스냅샷 복원). keep 가드=`.mig` 스키마 지문 변경 시 `--force` 요구.
13. `deploy/host/docker-compose.yml` — 현 `deploy/docker-compose.yml`을 host용으로 이동(`${TAG}`, `127.0.0.1:8100:8000`, 디렉터리 마운트 유지).

### D. 백업 (안전망 — has_seed=false라 최우선)
14. `scripts/backup_db.py`(stdlib only) — `sqlite3.connect().backup()` 온라인 백업 → 원자 `os.replace`. hourly(RETAIN 12) + `prune_pre_deploy`(20, `-wal`/`-shm`/`.mig` 형제 동반, deploy.sh와 retention 단일화) + 디스크 가드. `/srv/paleonews`에 hourly cron 등록.

### E. 이미지 / 앱
15. `deploy/Dockerfile`(수정) — `COPY deploy/host /app/deploy/host` + `COPY scripts/backup_db.py /app/scripts/` + `gosu` 설치.
16. `deploy/entrypoint.sh`(수정) — gosu 스캐폴딩 이식 + **root escape hatch**. uid=`APP_RUN_UID` env > `/app/data` 소유자. 소유자 uid 0이면 **root 유지**(paleonews all 모드는 cron 데몬·`/root/.claude`·`/root/.local/bin/claude`가 root 요구 → 실운영 root, 현 동작 무변화). 비-root 마운트 소유 시에만 `chown`+`gosu UID:GID env HOME=/tmp` 발동(claude 인증은 `CLAUDE_CODE_OAUTH_TOKEN` env라 HOME 독립). 쓰기 프로브는 uid 무관하게 항상 포함.
17. `paleonews/web.py`(수정) — `/healthz`: `{status, version, db, counts:{articles, feeds}}`. DB 실패 시 503.
18. `pyproject.toml` — `0.2.8 → 0.3.0`.
19. `CLAUDE.md` — 배포 섹션 신 계약 구조로 갱신.

### F. 기록
20. 완료 후 구현 devlog(`20260714_014_*`) 별도 작성.

## 설계 판단 (리뷰 반영)

- **gosu**: full parity로 스캐폴딩 이식하되 실활성 경로는 **root**(paleonews의 cron/`/root/.claude` 요구). fsis의 "파일-마운트-stays-root"와 동일 논리 = 정당한 이식. 비-root는 마운트 소유 uid로 발동만 가능한 dormant 인프라. **쓰기 프로브는 uid 무관하게 항상 포함**.
- **maintenance**: admin UI + cron이라 사용자 향 스테이크 낮음 → 경량 flag만.
- **dev target**: 실질 prod 단일. `deploy-dev.sh`는 parity 스텁.

## 검증
1. 신규 `.sh` 전부 `bash -n`, `python3 -m py_compile scripts/backup_db.py`.
2. `/healthz` 실동작(web 기동 → curl JSON 확인).
3. smoke.sh 로컬 실행 PASS + 버전 불일치 FAIL 확인.
4. backup_db.py 실 DB 1회 실행 → 원자 백업·retention 확인.
5. preflight 실행 → 위험 표면·seed 냄새(깨끗)·DEPLOY.md 출력.
6. `~/venv/paleonews/bin/python -m pytest tests/ -v` 회귀.
7. (선택) `docker build` → gosu·`/app/deploy/host` 내장 확인.
8. 실배포는 사용자 주도(계약 §롤아웃) — 최초 sync_to_srv.sh 부트스트랩 후 self-heal.

# 배포·데이터 계약 정렬 (full parity) — 구현 (0.3.0)

**날짜**: 2026-07-14
**계획**: [[20260714_P07_deploy_data_contract_alignment]]

cross-project 배포·데이터 계약(`../devdocs/wiki/deploy-data-contract.md`)에 paleonews를
fsis2026과 **동형(full parity)**으로 정렬. 활성 3개(cdGTS·fsis2026·fcmanager)에 이어 네 번째.

## 데이터 레인 판정

paleonews는 **`has_seed=false`**(fcmanager 선례) — 전 DB 테이블이 운영 데이터
(articles/dispatches/pipeline_runs/users/memories/feeds/app_settings)이고 시스템 시드 레인이 없다.
`feeds`는 원래 `sources.txt`(개발자 목록)에서 이관됐으나 이제 웹 `/settings`·CLI `sources`로
운영자가 관리 → 운영 데이터. 불변식은 seed 명령의 **부재**로 성립하고, **백업이 유일한 안전망**이다
(6/21 장애 [[20260624_013_token_renewal_native_claude_slim_image]]처럼 조용한 실패를 잡는 층).

## 스택 적응 (Django 아님)

FastAPI + CLI + raw sqlite3, Django 마이그레이션 없음. 이미 유리한 점:
- **DB 디렉터리 마운트**(`/srv/paleonews/data:/app/data`, WAL 형제 동반) — fsis 의 파일→디렉터리 컷오버 불필요.
- **WAL 이미 활성**(`db.py`의 `PRAGMA journal_mode=WAL`).
- **버전 단일 소스** `pyproject.toml` → `/healthz`·smoke 는 `importlib.metadata.version("paleonews")`.
- **migrate** = `db.py:_migrate()` 가 컨테이너 기동 시 자동(가산 컬럼만, 하위호환) → 별도 스텝 없이 성립.

fsis 의 Django 특정 부분을 적응:
- deploy.sh migrate/showmigrations 제거 — 기동=자동 migrate. rollback keep 가드의 `.mig` 사이드카는
  Django 마이그레이션 수 대신 **스키마 지문**(sqlite_master SQL 의 sha256, 정지 상태에서 계산)으로 대체.
- DB 바인딩 게이트: `manage.py shell` 대신 `python3 -c "from paleonews.config import load_config; ..."`.
- smoke: `/healthz` JSON 을 stdlib python3 로 검증(counts.articles/feeds 정수). SSL 리다이렉트 헤더 불요(평문 admin UI).

## 산출물

- **선언층**: `deploy/deploy.toml`(매니페스트) + `DEPLOY.md`(운영 델타 append-only).
- **빌드 호스트 동사**: `deploy/{build,preflight,remote-prod,sync_to_srv}.sh`. `scripts/release.sh` 는
  얇은 오케스트레이터(build → 로컬 deploy-prod.sh)로 재편.
- **운영 host 동사(이미지 내장, self-heal)**: `deploy/host/{deploy-prod,deploy-dev,_extract_and_deploy,deploy,smoke,rollback}.sh`
  + `deploy/host/docker-compose.yml`(기존 `deploy/docker-compose.yml` 이동).
- **백업**: `scripts/backup_db.py`(sqlite3 온라인 백업, hourly 12 + pre_deploy 20, 형제 동반 prune).
- **앱**: `web.py` `/healthz`(version/db/counts, 실패 시 503), `pyproject.toml` 0.2.8→0.3.0.
- **이미지**: `deploy/Dockerfile` 에 `deploy/host`·`backup_db.py` COPY + gosu 설치. `entrypoint.sh` 에
  gosu uid 감지 스캐폴딩 + root escape hatch.

## 설계 판단

- **prod = 빌드 호스트(m710q, 로컬 자기호스팅)** — 대부분 프로젝트(원격 GCP)와 다르다. 배포는 로컬
  실행(ssh 불요). repo 와 `/srv/paleonews` 는 같은 머신이지만 분리돼 git-free 원칙은 유지.
  *(계획 초안은 계약 인프라 표만 보고 target=dolfinid 로 잘못 적었다 — 구현 중 실 운영 위치
  확인해 m710q 로 정정. paleonews 컨테이너 `0.2.8` 2주째 m710q 로컬 가동 중이었음.)*
- **gosu 는 dormant, 컨테이너는 root 유지** — all 모드는 cron 데몬 + `/root/.claude` +
  `/root/.local/bin/claude` 가 root 를 요구한다. fsis 의 "파일-마운트 인스턴스 stays-root" 와 동일
  논리로 gosu 스캐폴딩만 이식(비-root 마운트 소유 시 발동 가능). `/srv/paleonews/data` 는
  `jikhanjung` 소유지만 root 는 DAC 우회로 쓰기 가능 → **쓰기 프로브는 실서비스 uid(root)로 검증**
  (fsis 는 서비스=마운트 소유자라 dir-owner 로 프로브했으나 paleonews 는 서비스=root 라 root 로).

## 검증 (실 운영 DB 사본으로)

운영 DB(`/srv/paleonews/data/paleonews.db`, articles 2214·feeds 10·users 1)를 sqlite3 온라인 백업으로
사본 떠서 테스트:
- **`/healthz`**(실 uvicorn 경로 = async·이벤트루프 단일 스레드 lazy get_db): 사본 대해
  `{"status":"ok","version":"0.3.0","db":true,"counts":{"articles":2214,"feeds":10,"users":1}}` 정확 반환.
- **`_migrate()`**: 사본에 재실행 — 실 스키마에서 크래시 없음(2214건 보존). *(참고: 운영 DB 에
  마이그레이션 잔재 `users_new` 테이블이 남아 있으나 `users` 는 정상 — 별건.)*
- **smoke.sh**: PASS(0.3.0) / FAIL(버전 불일치) / FAIL(503 error body) 세 경로 확인.
- **backup_db.py**: 사본 대해 원자 온라인 백업(2.5MB) + pre_deploy prune 동작.
- **preflight.sh**: 위험 표면 플래그 + seed 냄새 lint 🟢(seed_* 없음·무가드 대량삭제 없음 = 불변식 성립) + DEPLOY.md 출력.
- **pytest**: 41 passed. 신규 `.sh` 전부 `bash -n`, `deploy.toml` tomllib 파싱 OK.

## 운영 반영 (다음 배포)

- 코드 정렬만 완료(미커밋·미배포). 실배포는 사용자 주도(계약 §롤아웃).
- 최초 배포: `deploy/sync_to_srv.sh`(host 래퍼 부트스트랩) → 이후 self-heal. 첫 배포 때 기존
  `/srv/paleonews/{docker-compose.yml,deploy.sh}` 는 신 host 세트로 교체됨.
- hourly 백업 cron 1회 등록: `0 * * * * python3 /srv/paleonews/scripts/backup_db.py >> /srv/paleonews/logs/backup.log 2>&1`.

## 버전 이력

| 버전 | 내용 |
|------|------|
| 0.3.0 | 배포·데이터 계약 정렬(full parity) — 매니페스트+동사(preflight/build/deploy/smoke/rollback)+/healthz+백업(hourly+pre-deploy 스냅샷)+git-free self-heal+gosu 스캐폴딩(dormant). has_seed=false, prod=m710q 로컬. |

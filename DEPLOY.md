# PaleoNews — 배포 운영 델타 노트 (append-only)

> 배포·데이터 계약(`../devdocs/wiki/deploy-data-contract.md`)의 얇은 정형 층.
> devlog 는 "무슨 일이 있었나"의 서사이고, 이 파일은 **배포 시 봐야 할 운영 델타**를
> 릴리스별로 한두 줄로 뽑은 권위 소스다. `deploy/preflight.sh` 가 이 파일을 출력한다.
> 새 릴리스는 **맨 위 표에 append** (오래된 것 삭제 금지).

## 불변식 (Invariant)

> **paleonews 는 `has_seed=false` — 전 테이블이 운영 데이터이고 시스템 시드 레인이 없다.
> 배포 파이프라인은 운영 데이터를 나르지도 지우지도 않는다. 안전망은 파이프라인이
> 아니라 백업(`scripts/backup_db.py` hourly + deploy.sh pre-deploy 스냅샷)이다.**

### 데이터 레인 경계
- **운영 데이터(전부, in-app/CLI 로만 입력·백업이 잡음)**: `articles`, `dispatches`,
  `pipeline_runs`, `users`, `memories`, `feeds`, `app_settings`.
  - `feeds` 는 원래 `sources.txt`(개발자 목록)에서 이관됐으나 이제 웹 `/settings` · CLI
    `sources add/remove` 로 운영자가 관리 → **운영 데이터**로 분류(시드 아님).
- **시스템 시드**: 없음. `config.yaml`(키워드·전용 피드·모델 기본값)은 이미지에 실려
  배포와 함께 나가지만 DB 를 건드리지 않는다(overlay 는 `app_settings` 가 우선).
- **불변식 강제 방식**: seed 명령의 **부재**. paleonews 의 DB DELETE 는 전부 WHERE 절이
  있고(단건 삭제) 무가드 대량 삭제/`seed_*` CLI 가 없다 → preflight 냄새 lint 가 깨끗해야 정상.

## 배포 절차 요약
> **prod = 빌드 호스트(m710q, 로컬 자기호스팅)** — 대부분 프로젝트와 달리 원격 GCP 가 아니라
> 이 머신에서 직접 굴린다. 배포는 로컬 실행(ssh 불요). repo(`~/projects/paleonews`)와 배포
> 디렉터리(`/srv/paleonews`)는 분리돼 있어 git-free 원칙은 유지. 컨테이너는 **root** 로 실행.
- 빌드(m710q): `deploy/preflight.sh` → `deploy/build.sh X.Y.Z [--fast]`.
- 배포(m710q 로컬, git-free): `/srv/paleonews/deploy-prod.sh X.Y.Z` (또는 repo 에서 `scripts/release.sh X.Y.Z`).
  - 이미지에서 host 스크립트 추출(self-heal) → pre-deploy 스냅샷 → 스왑 → `/healthz` 대기 → DB 게이트+쓰기 프로브 → smoke.
- 롤백: `/srv/paleonews/rollback.sh <이전 X.Y.Z>` (기본 `--db=keep`, 운영 데이터 보존).
- 최초 부트스트랩(1회): repo 머신에서 `deploy/sync_to_srv.sh`, 이후 self-heal.
- 백업 cron(1회 등록): `0 * * * * python3 /srv/paleonews/scripts/backup_db.py`.

## 릴리스별 운영 델타

| 버전 | 운영 델타 (배포 시 확인) |
|------|--------------------------|
| 0.3.5 | **백업 검증 도입 — 계약 MUST 미준수 상환**(naverland 와 같은 날 동형 적용). `sqlite3.backup()` 은 소스를 **검증 없이** 복사하므로 소스가 깨지면 스냅샷도 깨진 채 채택되고, prune 이 계속 돌아 **RETAIN_COUNT 시간이면 성한 스냅샷이 전부 사라진다**(백업이 스스로를 오염). 이제 스냅샷마다 `PRAGMA integrity_check` → 실패 시 ① 미채택 ② **prune 중단**(과거 보존) ③ 증거 사본 1개 보존 ④ DB 옆 `INTEGRITY_FAIL` 센티넬 → `/healthz` **degraded**(HTTP 200 유지) → `smoke.sh` 실패. 복구되면 다음 정시에 자동 해제. **retention 12 → 24**(daily·오프사이트 트랙이 없어 이 hourly 창이 안전망 전부). 부수 수정: 스냅샷을 `journal_mode=DELETE` 로 내리고 커넥션을 명시적으로 close — 종전엔 `with sqlite3.connect(...)`(트랜잭션 컨텍스트지 close 아님)라 백업 디렉터리에 `-wal`/`-shm` 고아가 남을 수 있었다(데이터 손실은 없었음, 실측 확인). **배포 후 확인**: `python3 /srv/paleonews/scripts/backup_db.py` 수동 1회 → `integrity ok` 로그 + `backup/` 에 `.tmp*` 잔재 0개. |
| 0.3.4 | **크롤 단계 복구 — 2026-02-18 이후 6개월간 본문 크롤이 0건이었다.** `get_uncrawled()` 에 ORDER BY 도 실패 마킹도 없어 rowid 순 큐 맨 앞의 `academic.oup.com` 48건(Cloudflare 403)이 `max_per_run: 20` 슬롯을 매일 전부 소모 → 신규 기사에 영원히 도달 못 함. 그 사이 모든 한국어 요약이 RSS 발췌만 보고 생성됐다(요약 220~260자). 수정: 큐를 **신규 우선(id DESC)** + **미요약分만** + `crawl_attempts >= max_attempts`(기본 3) 은퇴, 크롤 실패 로그를 debug→**warning** 으로 승격(전건 실패 시 error). 스키마 가산: `articles.crawl_attempts`(자동 마이그레이션). **배포 후 확인: 다음 파이프라인 실행(23:00 UTC) 후 `pipeline_runs.crawled > 0`**, 그리고 `select count(*) from articles where body is not null and fetched_at > date('now','-2 days')` 가 0 이 아닐 것. 겸사겸사 `pipeline_runs.sent` 가 누적 총계 대신 회차 증분을 기록하도록 수정(과거 행은 누적값 그대로). |
| 0.3.3 | **웹 페이지 500 복구 — 템플릿이 wheel 에 안 들어가고 있었다.** `pyproject.toml` 에 `[tool.setuptools.package-data]` 가 없어 `paleonews/templates/*.html` 6개가 설치 패키지에서 통째로 빠졌고, 대시보드·기사·사용자·상세·설정 **5개 페이지가 전부 500**(`TemplateNotFound`)이었다. `/healthz` 는 200 이라 smoke 가 통과했고 그래서 오래 숨어 있었다. **배포 후 확인: `/healthz` 말고 실제 페이지(`/`, `/articles`, `/users`, `/settings`)가 200 인지 볼 것.** 앞으로 비-py 자산을 추가하면 package-data 에 같이 등록해야 한다. |
| 0.3.2 | **로그 자격증명 마스킹.** httpx 가 요청 URL 을 INFO 로 찍는데 Telegram 은 토큰을 URL **경로**에 담아, 봇 폴링마다(10초 주기) 토큰이 평문으로 기록되고 있었다 — 2026-08-17 실측 `/srv/paleonews/logs` 4개 파일에 **104,075건**, 퍼미션 0664(세계 읽기). `log_redact.RedactingFilter` 를 **핸들러**에 부착해 서드파티 로거(httpx)까지 덮는다. 기존 로그는 삭제·truncate 로 0건 처리 완료, 파일 퍼미션 0640 으로 축소. 소급 정리가 또 필요하면 `sudo scripts/redact_existing_logs.sh`. **배포 후 확인**: 컨테이너 로그의 telegram 요청이 `bot<id>:<redacted>` 로 나오는지. **토큰 재발급은 하지 않기로 결정**(2026-08-17) — 파일을 지워도 과거 노출은 되돌려지지 않으므로 추후 재검토 대상으로 남긴다. |
| 0.3.1 | **배포 중 점검 페이지**(nginx maintenance flag, fsis 동형). `deploy/nginx/paleonews.conf` 를 `/etc/nginx/sites-available/` 에 설치 필요(root, 1회): `sudo cp deploy/nginx/paleonews.conf /etc/nginx/sites-available/paleonews.conf && sudo nginx -t && sudo systemctl reload nginx`. deploy.sh 가 maintenance.flag 자동 토글. 수동: `/srv/paleonews/maintenance.sh {short\|planned\|off\|status}`. |
| 0.3.0 | 배포·데이터 계약 정렬(full parity). **매니페스트+동사+/healthz+백업+self-heal 신설.** 최초 배포는 `sync_to_srv.sh` 1회 부트스트랩 후 self-heal 전환 + hourly `backup_db.py` cron 등록. 컨테이너 여전히 root(cron·`/root/.claude` 요구) — gosu 는 dormant. |
| 0.2.8 | 구독 인증 = `.env` 의 `CLAUDE_CODE_OAUTH_TOKEN`(장기 토큰). **만료 시 `/srv/paleonews/apply_claude_token.sh <토큰>`** (`claude setup-token` → env 갱신 + 컨테이너 재생성). `ANTHROPIC_API_KEY` 는 크레딧 폴백이라 주석 처리 유지. |

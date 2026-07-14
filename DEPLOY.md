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
| 0.3.1 | **배포 중 점검 페이지**(nginx maintenance flag, fsis 동형). `deploy/nginx/paleonews.conf` 를 `/etc/nginx/sites-available/` 에 설치 필요(root, 1회): `sudo cp deploy/nginx/paleonews.conf /etc/nginx/sites-available/paleonews.conf && sudo nginx -t && sudo systemctl reload nginx`. deploy.sh 가 maintenance.flag 자동 토글. 수동: `/srv/paleonews/maintenance.sh {short\|planned\|off\|status}`. |
| 0.3.0 | 배포·데이터 계약 정렬(full parity). **매니페스트+동사+/healthz+백업+self-heal 신설.** 최초 배포는 `sync_to_srv.sh` 1회 부트스트랩 후 self-heal 전환 + hourly `backup_db.py` cron 등록. 컨테이너 여전히 root(cron·`/root/.claude` 요구) — gosu 는 dormant. |
| 0.2.8 | 구독 인증 = `.env` 의 `CLAUDE_CODE_OAUTH_TOKEN`(장기 토큰). **만료 시 `/srv/paleonews/apply_claude_token.sh <토큰>`** (`claude setup-token` → env 갱신 + 컨테이너 재생성). `ANTHROPIC_API_KEY` 는 크레딧 폴백이라 주석 처리 유지. |

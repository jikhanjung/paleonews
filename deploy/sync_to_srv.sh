#!/bin/bash
# deploy/sync_to_srv.sh — **repo 있는 머신에서** 최초 부트스트랩용(git-free 전환). host/* → /srv/paleonews.
#
# 상시 배포는 git-free 다: /srv/paleonews/deploy-{prod,dev}.sh X.Y.Z 가 이미지에서 모든 host 파일을
# 추출하고, 부트스트랩 파일(deploy-prod/dev.sh · _extract_and_deploy.sh)까지 self-heal 하므로
# 이후 repo/git pull 은 영영 불필요.
#
# repo 가 없는 운영 호스트는 이 스크립트 대신 **이미지에서 직접**(git-free) 부트스트랩할 수 있다:
#   cd /srv/paleonews && CID=$(docker create honestjung/paleonews:X.Y.Z)
#   for f in _extract_and_deploy.sh deploy-prod.sh deploy-dev.sh; do docker cp "$CID:/app/deploy/host/$f" ./; done
#   docker rm "$CID" && chmod +x _extract_and_deploy.sh deploy-prod.sh deploy-dev.sh
#
# 최초 1회: /srv/paleonews 생성 + .env / config.yaml / claude / data 준비 후 실행.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOST_DEST="${HOST_DEST:-/srv/paleonews}"
HOST_SRC="$PROJECT_DIR/deploy/host"

if [ ! -d "$HOST_DEST" ]; then
    echo "ERROR: $HOST_DEST not found." >&2
    echo "       이 스크립트는 운영 호스트에서만 실행." >&2
    exit 1
fi

echo "=== bootstrap host/* → $HOST_DEST/ ==="
# 상시 부트스트랩 파일(호스트에 남는 것) — git-free 배포의 진입점.
cp -p "$HOST_SRC"/deploy-prod.sh          "$HOST_DEST/"
cp -p "$HOST_SRC"/deploy-dev.sh           "$HOST_DEST/"
cp -p "$HOST_SRC"/_extract_and_deploy.sh  "$HOST_DEST/"
# 나머지는 배포 시 이미지에서 추출되지만, 최초 부트스트랩 편의를 위해 함께 심는다.
cp -p "$HOST_SRC"/deploy.sh               "$HOST_DEST/"
cp -p "$HOST_SRC"/smoke.sh                "$HOST_DEST/"
cp -p "$HOST_SRC"/rollback.sh             "$HOST_DEST/"
cp -p "$HOST_SRC"/docker-compose.yml      "$HOST_DEST/"
# apply_claude_token.sh — 구독 토큰 갱신 도구(호스트 상주).
cp -p "$PROJECT_DIR"/scripts/apply_claude_token.sh "$HOST_DEST/" 2>/dev/null || true
# 호스트 cron 이 쓰는 유일한 스크립트(stdlib only).
mkdir -p "$HOST_DEST/scripts"
cp -p "$PROJECT_DIR"/scripts/backup_db.py "$HOST_DEST/scripts/"
chmod +x "$HOST_DEST"/deploy-prod.sh "$HOST_DEST"/deploy-dev.sh "$HOST_DEST"/_extract_and_deploy.sh \
         "$HOST_DEST"/deploy.sh "$HOST_DEST"/smoke.sh "$HOST_DEST"/rollback.sh
echo "  bootstrap synced (deploy-prod/dev + _extract_and_deploy + deploy/smoke/rollback/compose + backup_db.py)."
echo ""
echo "다음: hourly 백업 cron 1회 등록 (아직이면):"
echo "  (crontab -l 2>/dev/null; echo '0 * * * * python3 /srv/paleonews/scripts/backup_db.py >> /srv/paleonews/logs/backup.log 2>&1') | crontab -"
echo ""
echo "=== 상시 배포(git-free): /srv/paleonews/deploy-prod.sh X.Y.Z  (이미지 추출 → 스냅샷 → 스왑 → smoke) ==="

#!/bin/bash
# deploy/remote-prod.sh — 운영 서버에 원격 배포하는 얇은 SSH 래퍼(계약 `remote` 동사, parity용).
#
# ⚠️ paleonews 는 **prod = 빌드 호스트(m710q)** 라 실사용은 로컬 배포다:
#     /srv/paleonews/deploy-prod.sh X.Y.Z   (또는 scripts/release.sh X.Y.Z)
# 이 스크립트는 다른 머신에서 빌드해 m710q(또는 미래의 원격 호스트)로 밀 때만 쓴다.
# 운영 서버의 /srv/paleonews/deploy-prod.sh 를 SSH 로 실행할 뿐 — 실제 로직은 서버 쪽(self-heal, git-free).
#
# Usage: PROD_HOST=<host> ./deploy/remote-prod.sh X.Y.Z
# Env:
#   PROD_HOST   원격 SSH 대상 (기본 m710q — 원격에서 밀 때만 의미 있음. 로컬이면 deploy-prod.sh 직접)
#   PROD_DEPLOY 원격 배포 스크립트 경로 (기본 /srv/paleonews/deploy-prod.sh)
set -euo pipefail

VERSION=${1:-}
if [ -z "$VERSION" ]; then
    echo "Usage: $0 X.Y.Z" >&2
    exit 1
fi

PROD_HOST=${PROD_HOST:-m710q}
PROD_DEPLOY=${PROD_DEPLOY:-/srv/paleonews/deploy-prod.sh}

echo "=== remote deploy → ${PROD_HOST}:${PROD_DEPLOY} $* ==="
exec ssh "$PROD_HOST" "$PROD_DEPLOY" "$@"

#!/bin/bash
# /srv/paleonews/deploy-dev.sh — 스냅샷 없는 배포(테스트/일회성). paleonews 는 실질 prod 단일이라
# 상시 쓰진 않지만, 계약 동사 parity(prod=snapshot / dev=no-snapshot 대칭)를 위해 둔다.
# Usage: /srv/paleonews/deploy-dev.sh X.Y.Z
set -euo pipefail
DEPLOY_SNAPSHOT=0 exec "$(dirname "$0")/_extract_and_deploy.sh" "$@"

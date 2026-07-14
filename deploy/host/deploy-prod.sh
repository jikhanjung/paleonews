#!/bin/bash
# /srv/paleonews/deploy-prod.sh — 프로덕션 배포(m710q 로컬, git-free). 배포 전 DB 스냅샷을 뜬다.
# Usage: /srv/paleonews/deploy-prod.sh X.Y.Z
#
# 운영 디렉터리(/srv/paleonews)는 앱 소스(repo/git)가 필요 없다 — 모든 host 파일을 **이미지**
# (/app/deploy/host/*)에서 추출한다(_extract_and_deploy.sh). 부트스트랩 파일도 매 배포 self-heal →
# 최초 1회 심으면 이후 손댈 게 없다. prod=빌드 호스트라 보통 로컬 실행(원격이면 deploy/remote-prod.sh).
set -euo pipefail
DEPLOY_SNAPSHOT=1 exec "$(dirname "$0")/_extract_and_deploy.sh" "$@"

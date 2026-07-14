#!/usr/bin/env bash
#
# release.sh — PaleoNews 릴리스 오케스트레이터 (repo 에서 실행, 빌드 호스트 m710q).
#
# 배포·데이터 계약 정렬(0.3.0) 후 얇은 래퍼가 됐다. 실제 로직은 동사 스크립트에 있다:
#   1) deploy/build.sh   — test + bump(pyproject) + docker build + push :X.Y.Z + :latest
#   2) /srv/paleonews/deploy-prod.sh — 로컬 배포(git-free self-heal 추출 → 스냅샷 → 스왑 → smoke)
#
# **prod = 빌드 호스트(m710q)** 라 배포는 로컬 실행(ssh 불요). 배포 산출물 복사도 안 한다 —
# host 스크립트는 이미지에서 self-heal 추출된다(_extract_and_deploy.sh). 최초 1회만
# deploy/sync_to_srv.sh 로 부트스트랩. (원격 빌드 호스트에서 배포할 땐 deploy/remote-prod.sh.)
#
# 사용법:
#   scripts/release.sh [버전]          # 버전 생략 시 pyproject.toml 에서 읽음
#   scripts/release.sh 0.3.1
#   scripts/release.sh 0.3.1 --fast    # 테스트 건너뛰고 빌드
#   scripts/release.sh --no-build      # 빌드/푸시 건너뛰고 배포만
#   scripts/release.sh --no-deploy     # 빌드/푸시까지, 배포는 직접
#
set -euo pipefail

DO_BUILD=1
DO_DEPLOY=1
FAST=""
VERSION=""

for arg in "$@"; do
    case "$arg" in
        --no-build)  DO_BUILD=0 ;;
        --no-deploy) DO_DEPLOY=0 ;;
        --fast)      FAST="--fast" ;;
        -*)          echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
        *)           VERSION="$arg" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "$VERSION" ]]; then
    VERSION="$(grep -oP '^version\s*=\s*"\K[^"]+' pyproject.toml | head -1)"
fi
if [[ -z "$VERSION" ]]; then
    echo "ERROR: 버전을 결정할 수 없습니다 (인자/pyproject.toml 모두 비어 있음)." >&2
    exit 1
fi

echo "=== PaleoNews release ${VERSION} (build=${DO_BUILD} deploy=${DO_DEPLOY}) ==="
echo

if [[ "$DO_BUILD" == "1" ]]; then
    ./deploy/build.sh "$VERSION" $FAST
else
    echo "--- 빌드/푸시 건너뜀 (--no-build) ---"
fi

DEPLOY_ENTRY="/srv/paleonews/deploy-prod.sh"
if [[ "$DO_DEPLOY" == "1" ]]; then
    echo
    if [[ -x "$DEPLOY_ENTRY" ]]; then
        echo "--- 로컬 배포 ($DEPLOY_ENTRY $VERSION) ---"
        "$DEPLOY_ENTRY" "$VERSION"
    else
        echo "ERROR: $DEPLOY_ENTRY 없음 — 최초 부트스트랩 필요:" >&2
        echo "  ./deploy/sync_to_srv.sh   # host 래퍼 설치(이후 self-heal)" >&2
        echo "  그 뒤 다시: scripts/release.sh $VERSION --no-build" >&2
        exit 1
    fi
else
    echo
    echo "빌드 완료. 배포는 직접 실행하세요:"
    echo "  $DEPLOY_ENTRY $VERSION"
fi

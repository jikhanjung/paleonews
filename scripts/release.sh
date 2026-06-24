#!/usr/bin/env bash
#
# release.sh — PaleoNews 릴리스 오케스트레이터 (repo 에서 실행).
#
#   1) 이미지 빌드 (deploy/Dockerfile)  → honestjung/paleonews:<ver> + :latest
#   2) 레지스트리 push
#   3) 배포 산출물을 배포 디렉터리(/srv/paleonews)로 복사
#        - deploy/docker-compose.yml
#        - deploy/deploy.sh
#        - scripts/apply_claude_token.sh
#      (.env / config.yaml / claude / data / logs 등 호스트 상태는 건드리지 않음)
#   4) 배포 디렉터리에서 deploy.sh <ver> 실행 (pull + 컨테이너 재생성)
#
# 사용법:
#   scripts/release.sh [버전]          # 버전 생략 시 pyproject.toml 에서 읽음
#   scripts/release.sh 0.2.9
#   scripts/release.sh --no-build      # 빌드/푸시 건너뛰고 복사+배포만
#   scripts/release.sh --no-deploy     # 빌드/푸시+복사까지, 배포는 직접
#   TARGET=/srv/paleonews scripts/release.sh   # 배포 디렉터리 override
#
set -euo pipefail

IMAGE="honestjung/paleonews"
TARGET="${TARGET:-/srv/paleonews}"
DO_BUILD=1
DO_DEPLOY=1
VERSION=""

for arg in "$@"; do
    case "$arg" in
        --no-build)  DO_BUILD=0 ;;
        --no-deploy) DO_DEPLOY=0 ;;
        -*)          echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
        *)           VERSION="$arg" ;;
    esac
done

# repo 루트 (이 스크립트는 <repo>/scripts/release.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# 버전: 인자 > pyproject.toml
if [[ -z "$VERSION" ]]; then
    VERSION="$(grep -oP '^version\s*=\s*"\K[^"]+' pyproject.toml | head -1)"
fi
if [[ -z "$VERSION" ]]; then
    echo "ERROR: 버전을 결정할 수 없습니다 (인자/pyproject.toml 모두 비어 있음)." >&2
    exit 1
fi

echo "=== PaleoNews release ${VERSION} ==="
echo "repo:   $REPO_ROOT"
echo "target: $TARGET"
echo "build=${DO_BUILD} deploy=${DO_DEPLOY}"
echo

if [[ "$DO_BUILD" == "1" ]]; then
    echo "--- [1/3] 빌드 ---"
    docker build -f deploy/Dockerfile -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" .
    echo
    echo "--- [2/3] push ---"
    docker push "${IMAGE}:${VERSION}"
    docker push "${IMAGE}:latest"
    echo
else
    echo "--- [1-2/3] 빌드/푸시 건너뜀 (--no-build) ---"
fi

echo "--- [3/3] 배포 산출물 동기화 → $TARGET ---"
if [[ ! -d "$TARGET" ]]; then
    echo "ERROR: 배포 디렉터리 $TARGET 가 없습니다." >&2
    exit 1
fi
# 호스트 상태(.env/config.yaml/claude/data/logs)는 절대 복사하지 않는다.
install -m 0644 deploy/docker-compose.yml      "$TARGET/docker-compose.yml"
install -m 0755 deploy/deploy.sh               "$TARGET/deploy.sh"
install -m 0755 scripts/apply_claude_token.sh  "$TARGET/apply_claude_token.sh"
echo "  복사: docker-compose.yml, deploy.sh, apply_claude_token.sh"
echo

if [[ "$DO_DEPLOY" == "1" ]]; then
    echo "--- 배포 실행 ($TARGET/deploy.sh $VERSION) ---"
    ( cd "$TARGET" && ./deploy.sh "$VERSION" )
else
    echo "복사 완료. 배포는 직접 실행하세요:"
    echo "  cd $TARGET && ./deploy.sh $VERSION"
fi

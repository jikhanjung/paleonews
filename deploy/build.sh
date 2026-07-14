#!/bin/bash
# deploy/build.sh — Test, bump version, build and push Docker image. (빌드 호스트 m710q 전용)
# Usage: ./deploy/build.sh X.Y.Z [--fast]
#   --fast : 테스트 건너뜀(배포 스크립트/문서 전용 변경 시). 앱 코드 변경 시엔 --fast 없이 전체 테스트.
#
# 책임 분리:
#   - 본 스크립트: m710q 에서 test + bump(pyproject.toml) + docker build + push
#   - 배포(m710q 로컬, prod=빌드 호스트)는 git-free: /srv/paleonews/deploy-prod.sh X.Y.Z 가 이미지에서
#     host 파일을 추출(_extract_and_deploy.sh). git pull / sync_to_srv.sh 불요(최초 부트스트랩만).
set -e

VERSION=""
FAST=0
for arg in "$@"; do
    case "$arg" in
        --fast|--skip-tests) FAST=1 ;;
        *) VERSION="$arg" ;;
    esac
done

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 버전: 인자 > pyproject.toml
if [ -z "$VERSION" ]; then
    VERSION="$(grep -oP '^version\s*=\s*"\K[^"]+' pyproject.toml | head -1)"
fi
if [ -z "$VERSION" ]; then
    echo "Usage: $0 X.Y.Z [--fast]  (또는 pyproject.toml 에 version)"
    exit 1
fi

VENV="${VENV:-$HOME/venv/paleonews/bin/activate}"
IMAGE=honestjung/paleonews

if [ "$FAST" = "1" ]; then
    echo "=== [1/4] Tests SKIPPED (--fast) — 배포/문서 전용 변경 가정. 앱 코드 바뀌면 --fast 빼고 재빌드 ==="
else
    echo "=== [1/4] Running tests ==="
    # shellcheck disable=SC1090
    source "$VENV"
    python -m pytest tests/ -q
    echo "All tests passed."
fi

echo ""
echo "=== [2/4] Bumping version to $VERSION (pyproject.toml) ==="
sed -i "s/^version\s*=\s*\".*\"/version = \"$VERSION\"/" pyproject.toml
git add pyproject.toml
if git diff --cached --quiet; then
    echo "(version already at $VERSION, no commit)"
else
    git commit -m "Bump version to $VERSION"
fi

echo ""
echo "=== [3/4] Building image $IMAGE:$VERSION ==="
docker build -f deploy/Dockerfile -t "$IMAGE:$VERSION" -t "$IMAGE:latest" .

echo ""
echo "=== [4/4] Pushing image ==="
docker push "$IMAGE:$VERSION"
docker push "$IMAGE:latest"

echo ""
echo "=== Done: $IMAGE:$VERSION ==="
echo ""
echo "다음 단계 (m710q 로컬 — git-free, git pull/sync 불요):"
echo "  /srv/paleonews/deploy-prod.sh $VERSION           # 로컬 배포(이미지 추출 → 스냅샷 → 스왑 → smoke)"
echo "  또는 repo 에서: scripts/release.sh $VERSION --no-build"
echo "  (부트스트랩 래퍼가 아직 없거나 바뀌었으면 repo 머신에서 1회: ./deploy/sync_to_srv.sh)"

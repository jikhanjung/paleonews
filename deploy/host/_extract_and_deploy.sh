#!/bin/bash
# /srv/paleonews/_extract_and_deploy.sh — git-free 배포 코어. deploy-{prod,dev}.sh 가 호출.
# 이미지에서 host 파일을 추출한 뒤 그 (갓 추출한) deploy.sh 로 위임한다. **운영 서버 repo/git pull 불필요.**
#
# 자기 치유(self-heal): 부트스트랩 파일(deploy-prod/dev.sh · 이 스크립트)도 이미지에서 매 배포 갱신.
#   - deploy-prod/dev.sh: 이미 exec 로 넘어와 프로세스가 사라졌으니 덮어써도 안전(즉시 반영).
#   - 이 스크립트 자신: 임시파일 → 원자 rename. 실행 중 bash 는 옛 inode 를 계속 읽고, 새 버전은 다음 배포부터.
# → 최초 1회만 이미지에서 부트스트랩(docker cp)하면, 이후 모든 파일이 이미지에서 자기 치유 → git 영영 불필요.
#
# 호출: DEPLOY_SNAPSHOT=0|1 /srv/paleonews/_extract_and_deploy.sh X.Y.Z
# 상시 존재해야 하는 호스트 파일 = 이 스크립트 + deploy-prod.sh + deploy-dev.sh + .env + config.yaml + claude/ + data/.
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then echo "Usage: DEPLOY_SNAPSHOT=0|1 $0 X.Y.Z"; exit 1; fi

ROOT=/srv/paleonews
IMAGE="honestjung/paleonews:${VERSION}"

echo "=== [0/7] Pull + extract host files from ${IMAGE} (git-free) ==="
docker pull "$IMAGE"

CID=$(docker create "$IMAGE")
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT

# 안전 추출(계약 self-heal 안전망): 임시로 꺼내 `bash -n` 문법 검사를 통과할 때만 교체하고,
# 기존 파일은 `<f>.previous` 로 보존한 뒤 원자 rename. 이미지에 실린 새 스크립트가 깨져 있어도
# 기존(작동하던) 부트스트랩 경로까지 함께 망가지지 않게 하는 최소 안전망.
safe_extract_sh() {
    local f="$1" tmp="${ROOT}/.${1}.new"
    if ! docker cp "${CID}:/app/deploy/host/${f}" "$tmp" 2>/dev/null; then
        echo "  (이미지에 ${f} 없음 — 구버전, 건너뜀)"; return 0
    fi
    if ! bash -n "$tmp" 2>/dev/null; then
        echo "  ✗ ${f}: 추출본 문법 오류(bash -n) — 교체 안 함(기존 유지). 이미지 확인 필요."
        rm -f "$tmp"; return 0
    fi
    chmod +x "$tmp"
    [ -f "${ROOT}/${f}" ] && cp -p "${ROOT}/${f}" "${ROOT}/${f}.previous" || true
    mv -f "$tmp" "${ROOT}/${f}"          # 원자 rename(같은 fs)
    echo "  extracted ${f} (bash -n 통과, 이전본 → ${f}.previous)"
}

# 운영 스크립트 — bash -n 검증 후 교체.
for f in deploy.sh smoke.sh rollback.sh maintenance.sh; do safe_extract_sh "$f"; done
# 비스크립트(구문 검사 대상 아님) — 그대로 추출. (maintenance_planned.html 은 생성물이라 추출 안 함.)
for f in docker-compose.yml maintenance.html maintenance_planned.html.template; do
    docker cp "${CID}:/app/deploy/host/${f}" "${ROOT}/${f}" 2>/dev/null && echo "  extracted ${f}" \
        || echo "  (이미지에 ${f} 없음 — 구버전, 건너뜀)"
done
# backup_db.py — 호스트 cron 이 쓰는 유일한 스크립트(python, bash -n 대상 아님). 그대로 추출.
mkdir -p "${ROOT}/scripts"
docker cp "${CID}:/app/scripts/backup_db.py" "${ROOT}/scripts/backup_db.py" 2>/dev/null \
    && echo "  extracted scripts/backup_db.py" || true
# apply_claude_token.sh — 구독 토큰 갱신 도구. 있으면 갱신.
docker cp "${CID}:/app/scripts/apply_claude_token.sh" "${ROOT}/apply_claude_token.sh" 2>/dev/null \
    && chmod +x "${ROOT}/apply_claude_token.sh" && echo "  extracted apply_claude_token.sh" || true

# 부트스트랩 래퍼 — exec 로 넘어와 안전하지만, 깨진 걸 심으면 다음 배포가 막히니 bash -n 검증 후 교체.
for f in deploy-prod.sh deploy-dev.sh; do safe_extract_sh "$f"; done
# 이 스크립트 자신 — 임시파일 → bash -n → 원자 rename(옛 inode 로 계속 실행, 새 버전은 다음 배포부터).
if docker cp "${CID}:/app/deploy/host/_extract_and_deploy.sh" "${ROOT}/.ead.new" 2>/dev/null; then
    if bash -n "${ROOT}/.ead.new" 2>/dev/null; then
        chmod +x "${ROOT}/.ead.new"
        [ -f "${ROOT}/_extract_and_deploy.sh" ] && cp -p "${ROOT}/_extract_and_deploy.sh" "${ROOT}/_extract_and_deploy.sh.previous" || true
        mv -f "${ROOT}/.ead.new" "${ROOT}/_extract_and_deploy.sh"
        echo "  self-heal _extract_and_deploy.sh (bash -n 통과, 다음 배포부터 반영)"
    else
        echo "  ✗ _extract_and_deploy.sh: 추출본 문법 오류 — 교체 안 함(기존 유지)."; rm -f "${ROOT}/.ead.new"
    fi
fi

docker rm -f "$CID" >/dev/null; trap - EXIT
chmod +x "${ROOT}/deploy.sh" "${ROOT}/smoke.sh" "${ROOT}/rollback.sh" "${ROOT}/maintenance.sh" \
         "${ROOT}/deploy-prod.sh" "${ROOT}/deploy-dev.sh" 2>/dev/null || true

echo ""
exec "${ROOT}/deploy.sh" "$@"        # 버전 + 플래그 그대로 전달

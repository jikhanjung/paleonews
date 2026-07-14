#!/bin/bash
# deploy/preflight.sh — 배포 전 위험 표면 점검(배포·데이터 계약 = preflight 동사). 빌드 호스트(m710q) 전용.
# 기억 의존 0: git diff 로 위험 표면을 **항상** 표면화 + seed 냄새 lint + DEPLOY.md 델타 출력.
# 뻔한 부분을 결정론적으로 고정하고, go/no-go 판단은 사람/에이전트에 남긴다.
#
# Usage: deploy/preflight.sh [<since-ref>]    기본 since = 마지막 "Bump version" 커밋(직전 릴리스 경계).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

SINCE="${1:-}"
if [ -z "$SINCE" ]; then
    SINCE=$(git log --grep='^Bump version' -n 1 --format='%H' 2>/dev/null || true)
fi

if [ -n "$SINCE" ]; then
    echo "=== preflight: 변경 표면 ${SINCE:0:9}..HEAD (+ working tree) ==="
    CHANGED=$( { git diff --name-only "$SINCE" HEAD; git status --porcelain | awk '{print $2}'; } | sort -u | sed '/^$/d')
else
    echo "=== preflight: working tree (버전 bump 커밋 없음) ==="
    CHANGED=$(git status --porcelain | awk '{print $2}' | sort -u | sed '/^$/d')
fi

hits() { echo "$CHANGED" | grep -qE "$1"; }

echo "--- 위험 표면 ---"
RISK=0
hits 'paleonews/db\.py'                        && { echo "  🔴 db.py 변경 → 스키마/_migrate() 영향. 배포 전 pre_deploy 스냅샷 확인(prod). 가산 컬럼만 하위호환."; RISK=1; } || true
hits '\.env'                                   && { echo "  🔴 .env 관련 변경 → /srv/paleonews/.env 반영 확인(TAG·CLAUDE_CODE_OAUTH_TOKEN·TELEGRAM_*). git 커밋 금지."; RISK=1; } || true
hits '(^|/)config\.yaml'                        && { echo "  🟡 config.yaml(베이스 설정) 변경 → 이미지에 실려 나감. app_settings overlay 가 우선임에 주의."; RISK=1; } || true
hits '(docker-compose|Dockerfile|entrypoint)'  && { echo "  🟡 컨테이너/compose 변경 → git-free 배포가 이미지에서 자동 추출(별도 sync 불요), 단 재확인."; RISK=1; } || true
hits '(^|/)deploy/host/'                        && { echo "  🟡 host 스크립트 변경 → 이미지에 실려 다음 배포에서 자기 치유(self-heal). 부트스트랩 래퍼 바뀌었으면 sync_to_srv.sh 1회."; RISK=1; } || true
[ "$RISK" = "0" ] && echo "  🟢 위험 표면 변경 없음(코드/템플릿 전용 추정)."

echo "--- seed 냄새 lint (has_seed=false — 운영 데이터가 seed 로 새는가) ---"
# paleonews 는 시스템 시드 레인이 없다. 불변식은 seed 명령의 부재로 성립하므로,
# (a) seed_* CLI 서브파서의 존재 자체, (b) WHERE 없는 무가드 대량 DELETE 를 냄새로 플래그한다.
# 정상 상태 = 아무것도 안 잡힘(🟢). 잡히면 운영 데이터 footgun 후보.
SMELL=0
if grep -rnE 'add_parser\(\s*["'"'"']seed' paleonews/ 2>/dev/null; then
    echo "  🔴 위에 seed CLI 서브파서 존재 → has_seed=false 위반 후보. 시스템 시드가 아니면 은퇴/개명."
    SMELL=1
fi
# WHERE 없는 대량 삭제: DELETE FROM <table> 뒤에 WHERE 가 같은 문장에 없는 경우 + .all().delete().
if grep -rnE '\.all\(\)\.delete\(\)|DELETE\s+FROM\s+\w+\s*("|;|$)' paleonews/ 2>/dev/null | grep -vi 'where'; then
    echo "  🔴 위에 무가드 대량 삭제(WHERE 없음) → 운영 데이터 전멸 footgun 후보. 가드/은퇴 대상."
    SMELL=1
fi
[ "$SMELL" = "0" ] && echo "  🟢 seed_* CLI 없음 + 무가드 대량 삭제 없음(전 DELETE 가 WHERE 있음). 불변식 성립."

echo "--- DEPLOY.md (권위 운영 델타 노트) ---"
if [ -f DEPLOY.md ]; then
    sed -n '/^## 불변식/,$p' DEPLOY.md | sed 's/^/  /' | head -30
else
    echo "  🟡 DEPLOY.md 없음 — 릴리스별 운영 델타 노트를 두는 게 계약 권고."
fi

echo "=== preflight 끝 — go/no-go 는 사람/에이전트 판단 ==="

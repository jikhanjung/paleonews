#!/bin/bash
# /srv/paleonews/rollback.sh — 롤백 동사(계약). **코드 롤백과 DB 롤백을 분리한다.**
# Usage: /srv/paleonews/rollback.sh <이전 X.Y.Z> [--db=keep|restore] [--force]
#   --db=keep    (기본) 이전 이미지 태그로만 전환. 현재 DB 유지(운영 데이터 보존) — 삭제 아니라 전환.
#   --db=restore 서비스 정지 → 이전 이미지 전환 → pre_deploy 스냅샷 복원. 그 배포 창의 운영 쓰기는 유실.
#   --force      keep 가드(직전 배포에 스키마 변경 있으면 keep 차단)를 무시하고 강행.
#
# 기본이 keep 인 이유: rollback 이 배포 후 운영자 입력분(신규 기사·발송·사용자)까지 스냅샷 복원으로
# 지우면 rollback 자신이 불변식("파이프라인은 운영 데이터를 나르지도 지우지도 않는다")을 깬다.
# DB 복원은 명시적 opt-in. 기본값은 deploy.toml `rollback_db="keep"` 선언과 일치.
#
# keep 가드: 직전 배포가 스키마를 바꿨으면(db.py:_migrate 가 컬럼 추가) 이전 코드가 새 스키마와
# 어긋날 수 있어 keep 을 막고 restore/수동 판단으로 승격한다. 판정 = 최신 pre_deploy 스냅샷의
# `.mig` 스키마 지문(배포 전 스키마 sha256) vs 현재 라이브 DB 지문 비교. paleonews 마이그레이션은
# 가산 컬럼만이라 대개 하위호환이지만, parity 로 경고 후 --force 를 요구한다. 사이드카 없으면 미상.
set -euo pipefail

ROOT=/srv/paleonews
cd "$ROOT"

DB="$ROOT/data/paleonews.db"

PREV=""
DB_MODE=keep            # deploy.toml rollback_db 기본값과 일치
FORCE=0
for a in "$@"; do
    case "$a" in
        --db=keep)    DB_MODE=keep ;;
        --db=restore) DB_MODE=restore ;;
        --force)      FORCE=1 ;;
        --*)          echo "unknown flag: $a" >&2; exit 1 ;;
        *)            PREV="$a" ;;
    esac
done
if [ -z "$PREV" ]; then
    echo "Usage: $0 <이전 X.Y.Z> [--db=keep|restore] [--force]" >&2; exit 1
fi

schema_fingerprint() {
    python3 - "$1" <<'PY'
import sqlite3, hashlib, sys
try:
    c = sqlite3.connect(sys.argv[1])
    rows = c.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name").fetchall()
    print(hashlib.sha256("".join(r[0] for r in rows).encode()).hexdigest())
except Exception:
    pass
PY
}

FLAG="$ROOT/maintenance.flag"
echo "=== rollback → ${PREV} (db=${DB_MODE}) ==="
touch "$FLAG"
trap 'rm -f "$FLAG"' EXIT

# 최신 pre_deploy 스냅샷 = 직전 배포 1단계 되돌리기용(다단계는 스냅샷 명시).
SNAP=$(ls -1t "$ROOT"/backup/pre_deploy/paleonews_pre_deploy_*.sqlite3 2>/dev/null | head -n1 || true)

# --- keep 가드 ---
if [ "$DB_MODE" = keep ]; then
    CUR_FP=""
    [ -f "$DB" ] && CUR_FP=$(schema_fingerprint "$DB")
    PRE_FP=""
    [ -n "$SNAP" ] && [ -f "${SNAP}.mig" ] && PRE_FP=$(cat "${SNAP}.mig" 2>/dev/null || echo "")
    if [ -n "$CUR_FP" ] && [ -n "$PRE_FP" ] && [ "$CUR_FP" != "$PRE_FP" ]; then
        echo "  ⚠ 직전 배포가 스키마를 변경함(지문 ${PRE_FP:0:12}… → ${CUR_FP:0:12}…)."
        echo "    이전 이미지(${PREV}) 코드가 새 스키마와 어긋날 수 있어 keep 은 주의 →"
        if [ "$FORCE" = 1 ]; then
            echo "    (--force 지정 — 강행. paleonews 는 가산 컬럼만이라 대개 안전.)"
        else
            echo "    --db=restore (스냅샷으로 스키마째 되돌림) 또는 수동 판단 후 --force." >&2
            exit 1
        fi
    elif [ -z "$PRE_FP" ]; then
        echo "  (스키마 상태 미상 — .mig 사이드카 없음/구 스냅샷. 대개 무변경이라 keep 진행. 의심되면 --db=restore.)"
    else
        echo "  keep 안전(직전 배포 스키마 변경 없음)."
    fi
fi

# --- DB ---
if [ "$DB_MODE" = restore ]; then
    docker compose down
    if [ -n "$SNAP" ]; then
        echo "  restore DB ← ${SNAP} (컨테이너 정지 후 — SQLite WAL torn-copy 방지)"
        cp -p "$SNAP" "$DB"
        [ -f "${SNAP}-wal" ] && cp -p "${SNAP}-wal" "${DB}-wal" || rm -f "${DB}-wal"
        [ -f "${SNAP}-shm" ] && cp -p "${SNAP}-shm" "${DB}-shm" || rm -f "${DB}-shm"
    else
        echo "  (pre_deploy 스냅샷 없음 — DB 복원 건너뜀; dev 이거나 최초 배포)"
    fi
else
    echo "  db=keep — 현재 DB 유지(운영 데이터 보존). 이미지 태그만 전환."
fi

# --- 이미지 전환 ---
echo "  TAG → ${PREV}"
if grep -q '^TAG=' .env 2>/dev/null; then
    sed -i "s/^TAG=.*/TAG=${PREV}/" .env
else
    echo "TAG=${PREV}" >> .env
fi
docker pull "honestjung/paleonews:${PREV}"
docker compose up -d       # 전 서비스

echo "=== rolled back to ${PREV} (db=${DB_MODE}) — /srv/paleonews/smoke.sh ${PREV} 로 확인 권장 ==="

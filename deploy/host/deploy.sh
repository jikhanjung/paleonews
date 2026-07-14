#!/bin/bash
# /srv/paleonews/deploy.sh — paleonews 버전 스왑 배포 (공통 엔진).
# 직접 부르지 말고 환경별 래퍼로 호출(git-free — 이미지에서 host 파일 추출):
#   prod:      /srv/paleonews/deploy-prod.sh X.Y.Z   (DEPLOY_SNAPSHOT=1 — 배포 전 DB 스냅샷)
#   dev/test:  /srv/paleonews/deploy-dev.sh  X.Y.Z   (스냅샷 없음)
# 미설정 시 DEPLOY_SNAPSHOT 기본=1 (m710q 는 prod 단일 호스트라 안전측 기본).
#
# paleonews 는 Django 마이그레이션이 없다 — db.py:_migrate() 가 컨테이너 기동 시 자동(가산 컬럼만).
# 그래서 별도 migrate 스텝 없이 컨테이너를 올리면 스키마가 맞춰진다. rollback keep 가드용
# "스키마 지문"(.mig 사이드카)은 스냅샷 시점 스키마의 sha256 로 대신한다.
set -euo pipefail

VERSION=${1:-}
if [ -z "$VERSION" ]; then
    echo "Usage: $0 X.Y.Z"
    exit 1
fi

ROOT=/srv/paleonews
cd "$ROOT"

IMAGE="honestjung/paleonews:${VERSION}"
PORT=8100
DB="$ROOT/data/paleonews.db"
CONTAINER_DB=/app/data/paleonews.db
FLAG="$ROOT/maintenance.flag"

# 스냅샷 파일의 스키마 지문(정지 상태에서 계산) — rollback keep 가드가 소비.
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

echo "=== [1/7] Pulling ${IMAGE} ==="
docker pull "${IMAGE}"

echo ""
echo "=== [2/7] Updating .env (TAG=${VERSION}) ==="
if grep -q '^TAG=' .env 2>/dev/null; then
    sed -i "s/^TAG=.*/TAG=${VERSION}/" .env
else
    echo "TAG=${VERSION}" >> .env
fi

echo ""
echo "=== [3/7] Maintenance ON ==="
touch "$FLAG"
trap 'rm -f "$FLAG"' EXIT

echo ""
echo "=== [4/7] Stop old container + (prod) pre-deploy DB snapshot ==="
# DEPLOY_SNAPSHOT=1(prod, 기본)이면 writer 정지 직후 스냅샷. WAL/SHM 동반 보존(torn-copy 방지).
# DB 는 전용 디렉터리 $ROOT/data/ 에 있고 컨테이너엔 그 디렉터리가 /app/data 로 마운트된다.
if [ "${DEPLOY_SNAPSHOT:-1}" = "1" ] && [ -f "$DB" ]; then
    docker compose down
    SNAP_DIR="$ROOT/backup/pre_deploy"
    mkdir -p "$SNAP_DIR"
    TS=$(date -u +%Y%m%d_%H%M%S)
    SNAP="$SNAP_DIR/paleonews_pre_deploy_${VERSION}_${TS}.sqlite3"
    cp -p "$DB" "$SNAP"
    [ -f "${DB}-wal" ] && cp -p "${DB}-wal" "${SNAP}-wal" || true
    [ -f "${DB}-shm" ] && cp -p "${DB}-shm" "${SNAP}-shm" || true
    # 스키마 지문(정지 상태 = 일관). rollback keep 가드가 현재 지문과 비교해 스키마 변경을 감지.
    FP=$(schema_fingerprint "$SNAP")
    [ -n "$FP" ] && printf '%s\n' "$FP" > "${SNAP}.mig" || true
    echo "  snapshot: $SNAP ($(du -h "$SNAP" | cut -f1), schema: ${FP:0:12}...)"
    # retention: 최근 20개만 (.mig/-wal/-shm 사이드카 포함, hourly backup_db.py 12개와 별개 트랙)
    ls -1tr "$SNAP_DIR"/paleonews_pre_deploy_*.sqlite3 2>/dev/null \
        | head -n -20 \
        | while read -r f; do rm -f "$f" "$f-wal" "$f-shm" "$f.mig"; done
else
    docker compose down
    echo "  (DEPLOY_SNAPSHOT=${DEPLOY_SNAPSHOT:-1} 또는 DB 없음 — 스냅샷 건너뜀)"
fi

echo ""
echo "=== [5/7] Start new container (전 서비스) + wait for backend (/healthz) ==="
# up -d (서비스명 미지정) = compose 전 서비스. 컨테이너 기동 시 db.py:_migrate() 자동 실행.
docker compose up -d
for i in $(seq 1 60); do
    if curl -fsS -o /dev/null -m 2 "http://127.0.0.1:${PORT}/healthz" ; then
        echo "  backend up after ${i}s"
        break
    fi
    sleep 1
done

echo ""
echo "=== [6/7] Verify DB binding (host bind mount, not ephemeral image DB) + write probe ==="
# compose 는 host 디렉터리 $ROOT/data/ 를 /app/data 로 바인드한다(docker-compose.yml).
# config.yaml 의 db_path 가 이 마운트를 벗어나면 컨테이너가 이미지 내부 빈 DB 로 폴백 →
# 발송이 빈 데이터로 돈다(실데이터는 $ROOT/data 에 안전). 이 게이트가 오배선을 잡는다.
DB_PATH=$(docker compose exec -T paleonews \
    python3 -c "from paleonews.config import load_config; print(load_config().get('db_path'))" \
    2>/dev/null | tr -d '\r' | tail -n1)
case "$DB_PATH" in
    data/paleonews.db|/app/data/paleonews.db)
        echo "  OK: container db_path = ${DB_PATH} (host bind mount)" ;;
    *)
        echo "  ✗ FATAL: container db_path = '${DB_PATH:-<empty>}' — 기대 data/paleonews.db 아님."
        echo "    컨테이너가 마운트되지 않은 이미지 내부 DB 를 쓸 수 있다 → 발송이 빈 데이터로 돈다."
        echo "    실데이터는 ${DB} 에 안전. 고칠 곳: 이미지 config.yaml db_path / compose 마운트 확인."
        exit 1 ;;
esac

# 쓰기 프로브 — **실서비스 uid(root)**로 실제 DB 쓰기 검증. paleonews all 모드는 root 로 실행되므로
# (cron·/root/.claude 요구) 프로브도 컨테이너 기본 uid=root 로 돈다 = 서비스와 동일. 읽기 게이트만으론
# `:ro` 마운트/디스크 소진 같은 쓰기 실패를 못 잡는다 → CREATE/INSERT/DROP probe 로 실제 쓰기 경로 검증.
# (root 는 DAC 를 우회하므로 data 디렉터리가 jikhanjung 소유여도 쓰기 성공 = 정상.)
WRITE_OK=$(docker compose exec -T paleonews \
    python3 -c "import sqlite3; c=sqlite3.connect('${CONTAINER_DB}'); c.execute('CREATE TABLE IF NOT EXISTS _deploy_write_probe(x)'); c.execute('INSERT INTO _deploy_write_probe VALUES (1)'); c.commit(); c.execute('DROP TABLE _deploy_write_probe'); c.commit(); print('WRITE_OK')" \
    2>/dev/null | tr -d '\r' | tail -n1)
if [ "$WRITE_OK" = "WRITE_OK" ]; then
    echo "  OK: 서비스 uid(root) DB 쓰기 가능"
else
    echo "  ✗ FATAL: 서비스 uid(root) 로 DB 쓰기 실패 — :ro 마운트/디스크 소진 등."
    echo "    ${ROOT}/data 마운트가 읽기전용이거나 디스크가 찼는지 확인(df -h, docker-compose.yml 마운트)."
    exit 1
fi

echo ""
echo "=== [7/7] Smoke (healthz + 버전 일치 + 핵심 행 수) ==="
# smoke.sh 는 이미지에서 함께 추출됨(_extract_and_deploy.sh). 없으면 구버전 — 경고만.
if [ -x "$ROOT/smoke.sh" ]; then
    if ! "$ROOT/smoke.sh" "$VERSION"; then
        echo ""
        echo "!!! smoke 실패 — 컨테이너는 떴으나 검증 불일치(버전/DB/행수)."
        echo "!!! 점검 모드는 곧 해제됨(서비스 서빙). 조사 후 필요시 롤백:"
        echo "!!!   $ROOT/rollback.sh <이전 X.Y.Z>"
        exit 1
    fi
else
    echo "  (smoke.sh 없음 — 이미지 추출 실패? 건너뜀.)"
fi

echo ""
echo "=== Done: paleonews -> ${VERSION} (smoke OK) ==="
docker compose ps paleonews

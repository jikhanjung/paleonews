#!/bin/bash
# /srv/paleonews/smoke.sh — 배포 계약 `smoke` 동사
# Usage: /srv/paleonews/smoke.sh X.Y.Z
#
# /healthz 200 + 버전 일치 + DB 연결 + 핵심 행 수(counts) 존재를 결정론적으로 검증.
# 가볍게 유지 — 스테이크 낮으니 무거운 모니터링은 만들지 않는다.
# paleonews web 은 nginx 뒤 평문 admin UI(Django 식 SECURE_SSL_REDIRECT 없음)라
# fsis 의 X-Forwarded-Proto 트랩 헤더는 불필요 — 매핑 포트로 직접 찌른다.
set -euo pipefail

EXPECT_VERSION=${1:-}
if [ -z "$EXPECT_VERSION" ]; then
    echo "Usage: $0 X.Y.Z"
    exit 1
fi

URL="${SMOKE_URL:-http://127.0.0.1:8100/healthz}"

echo "=== smoke: GET $URL (expect $EXPECT_VERSION) ==="

BODY=$(curl -fsS -m 5 "$URL") || { echo "FAIL: /healthz 요청 실패 (연결/타임아웃/HTTP 오류)"; exit 1; }

echo "  response: $BODY"

# stdlib python3 로 JSON 검증 (호스트에 jq 의존 안 함)
EXPECT_VERSION="$EXPECT_VERSION" python3 - "$BODY" <<'PY'
import json, os, sys
body = sys.argv[1]
expect = os.environ["EXPECT_VERSION"]
try:
    d = json.loads(body)
except Exception as e:
    print(f"FAIL: JSON 파싱 불가 — {e}")
    sys.exit(1)

errs = []
if d.get("status") == "degraded":
    # hourly backup_db.py 의 PRAGMA integrity_check 실패 → DB 옆 센티넬. **배포 문제가 아니다.**
    print("FAIL: status=degraded — **운영 DB 손상 감지**(배포 자체 문제 아님, 롤백은 답이 아닐 수 있음)")
    print(f"  {d.get('integrity')}")
    print("  · 백업 로테이션 prune 은 이미 중단됨 — /srv/paleonews/backup/ 의 과거 스냅샷이 복구 후보")
    print("  · 증거 사본: /srv/paleonews/backup/paleonews_INTEGRITY_FAIL.corrupt")
    print("  · 확인: sqlite3 /srv/paleonews/data/paleonews.db 'PRAGMA integrity_check'")
    print("  · 복구 후 다음 정시 검사가 통과하면 센티넬 자동 해제(급하면 rm /srv/paleonews/data/INTEGRITY_FAIL)")
    sys.exit(1)
if d.get("status") != "ok":
    errs.append(f"status={d.get('status')!r} (기대 'ok', error={d.get('error')!r})")
if d.get("db") is not True:
    errs.append(f"db={d.get('db')!r} (기대 True)")
if d.get("version") != expect:
    errs.append(f"version={d.get('version')!r} (기대 {expect!r})")
# 도메인 불변식: counts 존재 + articles/feeds 가 정수(healthz 가 실제 DB 를 조회했는지).
counts = d.get("counts") or {}
articles = counts.get("articles")
feeds = counts.get("feeds")
if not isinstance(articles, int) or articles < 0:
    errs.append(f"counts.articles={articles!r} (기대 정수>=0)")
if not isinstance(feeds, int) or feeds < 0:
    errs.append(f"counts.feeds={feeds!r} (기대 정수>=0)")

if errs:
    print("FAIL:")
    for e in errs:
        print(f"  - {e}")
    sys.exit(1)
print(f"PASS: version={expect}, db=ok, articles={articles}, feeds={feeds}")
PY

echo "=== smoke OK ==="

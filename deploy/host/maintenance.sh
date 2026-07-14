#!/bin/bash
# /srv/paleonews/maintenance.sh — 점검 모드 토글 (fsis2026 동형).
# nginx 는 매 요청마다 `if (-f <flag>)` 를 평가하므로 flag 만 touch/rm 하면 reload 불필요.
# 배포 중 짧은 점검(short)은 deploy.sh 가 maintenance.flag 를 자동 토글한다 — 이 스크립트는
# 수동/예고 점검용.
set -euo pipefail

ROOT=/srv/paleonews
SHORT_FLAG="$ROOT/maintenance.flag"
PLANNED_FLAG="$ROOT/maintenance_planned.flag"
TEMPLATE="$ROOT/maintenance_planned.html.template"
OUTPUT="$ROOT/maintenance_planned.html"

usage() {
    cat <<EOF
Usage:
  $0 short                         짧은 점검 ON (자동 refresh 10s)
  $0 planned "<복귀시각>" "<사유>"    예고 점검 ON
  $0 off                           모든 점검 모드 OFF
  $0 status                        현재 상태

예:
  $0 planned "2026-07-15 06:00 KST" "DB 유지보수"
EOF
    exit 1
}

cmd=${1:-}
case "$cmd" in
    short)
        touch "$SHORT_FLAG"
        echo "짧은 점검 ON (auto refresh 10s) — flag: $SHORT_FLAG"
        ;;
    planned)
        until_at=${2:-}
        reason=${3:-}
        [ -z "$until_at" ] && usage
        [ -z "$reason" ] && usage
        python3 - "$TEMPLATE" "$OUTPUT" "$until_at" "$reason" <<'PY'
import sys, html
tpl, out, until_at, reason = sys.argv[1:]
src = open(tpl, encoding='utf-8').read()
src = src.replace('{{UNTIL_AT}}', html.escape(until_at))
src = src.replace('{{REASON}}', html.escape(reason))
open(out, 'w', encoding='utf-8').write(src)
PY
        touch "$PLANNED_FLAG"
        echo "예고 점검 ON"
        echo "  복귀 예정: $until_at"
        echo "  사유:      $reason"
        echo "  page:      $OUTPUT"
        ;;
    off)
        rm -f "$SHORT_FLAG" "$PLANNED_FLAG"
        echo "점검 모드 OFF"
        ;;
    status)
        echo "short maintenance:   $([ -f "$SHORT_FLAG" ] && echo ON || echo off)"
        echo "planned maintenance: $([ -f "$PLANNED_FLAG" ] && echo ON || echo off)"
        ;;
    *)
        usage
        ;;
esac

#!/bin/bash
# 이미 기록된 로그에서 자격증명을 소급 제거한다 (멱등, 제자리 수정).
#
# paleonews/log_redact.py 는 **앞으로** 나갈 로그를 막을 뿐이다. 그 전에 남은 것은
# 그대로 있으므로 한 번 훑어야 한다. 실측: 2026-08-17 기준 /srv/paleonews/logs 의
# 4개 파일에 Telegram 봇 토큰이 104,075건 남아 있었고, 파일 퍼미션은 rw-rw-r-- 였다.
#
# 사용: sudo scripts/redact_existing_logs.sh [로그디렉토리]
#       기본 디렉토리 /srv/paleonews/logs
#
# 주의: 이 스크립트는 로그를 고칠 뿐 **토큰을 무효화하지 못한다.**
#       세계 읽기 가능한 파일에 오래 노출됐다면 BotFather 에서 토큰을 재발급할 것.

set -euo pipefail

LOG_DIR="${1:-/srv/paleonews/logs}"
[ -d "$LOG_DIR" ] || { echo "디렉토리 없음: $LOG_DIR" >&2; exit 1; }

# log_redact.py 와 같은 패턴 — 봇 ID 는 남기고 토큰 본문만 가린다.
SED_EXPR='
s#(/bot[0-9]{6,}):[A-Za-z0-9_-]{20,}#\1:<redacted>#g
s#([?&](api[_-]?key|access[_-]?token|token|secret|key)=)[^&[:space:]"'"'"']+#\1<redacted>#gI
s#(Bearer[[:space:]]+)[A-Za-z0-9._-]{10,}#\1<redacted>#gI
'

total_before=0
total_after=0

shopt -s nullglob
for f in "$LOG_DIR"/*.log "$LOG_DIR"/*.log.[0-9]; do
    before=$(grep -cE '/bot[0-9]{6,}:[A-Za-z0-9_-]{20,}' "$f" 2>/dev/null || true)
    before=${before:-0}

    # 퍼미션·소유권을 보존하며 제자리 수정(rotate 중인 파일의 inode 를 바꾸지 않는다).
    tmp="$(mktemp)"
    sed -E "$SED_EXPR" "$f" > "$tmp"
    cat "$tmp" > "$f"
    rm -f "$tmp"

    after=$(grep -cE '/bot[0-9]{6,}:[A-Za-z0-9_-]{20,}' "$f" 2>/dev/null || true)
    after=${after:-0}

    printf '  %-24s %8s → %s\n' "$(basename "$f")" "$before" "$after"
    total_before=$((total_before + before))
    total_after=$((total_after + after))

    # 로그는 애초에 세계 읽기 대상이 아니다.
    chmod 640 "$f" 2>/dev/null || true
done

echo
echo "합계: $total_before → $total_after"
[ "$total_after" -eq 0 ] || { echo "일부가 남았다 — 패턴을 확인할 것" >&2; exit 1; }
echo "완료. 토큰 재발급은 별도로 할 것 — 이 스크립트는 노출을 되돌리지 못한다."

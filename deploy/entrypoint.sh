#!/bin/bash
set -e
umask 002

# ── 권한 모델 (배포·데이터 계약 gosu 스캐폴딩 + root escape hatch) ──────────────────
# fsis/cdGTS/fcmanager 는 gunicorn 단일 프로세스라 비-root gosu 드롭으로 착지했다.
# paleonews 는 "all" 모드(cron 데몬 + telegram bot + web)라 **root 가 실제 요구사항**이다:
#   - cron 데몬은 crontab 관리·작업 spawn 에 root 필요
#   - claude CLI 바이너리(/root/.local/bin/claude)와 캐시(/root/.claude 마운트)가 root HOME
# 따라서 계약의 "디렉터리 마운트 → 비-root 드롭" 스위치를 이식하되 **active path 는 root**로 둔다
# (fsis 의 "파일-마운트 인스턴스는 root 유지"와 동일 논리 = 정당한 parity 이식, gosu 는 dormant).
# /srv/paleonews/data 는 root 소유 유지 권장 → deploy.sh 쓰기 프로브(PROBE_UID=0)도 실서비스(root)와 일치.
mkdir -p /app/data /app/logs
TARGET_UID="${APP_RUN_UID:-}"
if [ -z "$TARGET_UID" ] && [ -d /app/data ]; then
    TARGET_UID=$(stat -c %u /app/data 2>/dev/null || echo "")
fi
if [ -n "$TARGET_UID" ] && [ "$TARGET_UID" != "0" ]; then
    # prod(m710q)의 /srv/paleonews/data 는 jikhanjung(uid≈1000) 소유가 정상 상태다. all 모드는
    # root 로 실행되고 root 는 DAC 를 우회해 쓸 수 있으므로 조치 불요(chown 하지 않는다 — 호스트
    # 소유권과 다투지 않기 위함). 이 로그는 정보성. gosu 비-root 전환은 dormant(cron·/root/.claude 요구).
    echo "entrypoint: /app/data uid=$TARGET_UID 소유 — 컨테이너는 root 로 실행(root 는 소유권 무관 쓰기 가능). 조치 불요."
fi

MODE="${1:-all}"
shift 2>/dev/null || true

case "$MODE" in
  all)
    # === 통합 모드: cron + bot + web 모두 실행 ===

    # 1) cron 설정 및 시작
    SCHEDULE="${PIPELINE_CRON:-0 23 * * *}"
    export -p | grep -Ev '(BASHOPTS|BASH_VERSINFO|EUID|PPID|SHELLOPTS|UID|_=)' > /app/env.sh
    echo "SHELL=/bin/bash" > /etc/cron.d/paleonews
    echo "$SCHEDULE root /bin/bash -c 'cd /app && source /app/env.sh && python -m paleonews run >> /proc/1/fd/1 2>&1'" >> /etc/cron.d/paleonews
    echo "" >> /etc/cron.d/paleonews
    chmod 0644 /etc/cron.d/paleonews
    crontab /etc/cron.d/paleonews
    cron
    echo "cron 시작: $SCHEDULE"

    # 2) Telegram bot 백그라운드 실행
    if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
      python -m paleonews bot &
      echo "Telegram bot 시작"
    fi

    # 3) Web UI 포그라운드 실행
    echo "Web UI 시작"
    exec python -m paleonews web --host 0.0.0.0 --port "${WEB_PORT_INTERNAL:-8000}"
    ;;
  cron)
    SCHEDULE="${PIPELINE_CRON:-0 23 * * *}"
    export -p | grep -Ev '(BASHOPTS|BASH_VERSINFO|EUID|PPID|SHELLOPTS|UID|_=)' > /app/env.sh
    echo "SHELL=/bin/bash" > /etc/cron.d/paleonews
    echo "$SCHEDULE root /bin/bash -c 'cd /app && source /app/env.sh && python -m paleonews run >> /proc/1/fd/1 2>&1'" >> /etc/cron.d/paleonews
    echo "" >> /etc/cron.d/paleonews
    chmod 0644 /etc/cron.d/paleonews
    crontab /etc/cron.d/paleonews
    echo "Pipeline cron started: $SCHEDULE"
    exec cron -f
    ;;
  run|fetch|filter|crawl|summarize|send|status|bot|web|users)
    exec python -m paleonews "$MODE" "$@"
    ;;
  *)
    echo "Unknown command: $MODE"
    exit 1
    ;;
esac

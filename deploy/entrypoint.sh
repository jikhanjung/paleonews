#!/bin/bash
set -e

MODE="${1:-all}"
shift 2>/dev/null || true

case "$MODE" in
  all)
    # === 통합 모드: cron + bot + web 모두 실행 ===

    # 1) cron 설정 및 시작
    SCHEDULE="${PIPELINE_CRON:-0 23 * * *}"
    printenv | grep -Ev '^(BASHOPTS|BASH_VERSINFO|EUID|PPID|SHELLOPTS|UID|_)=' > /app/env.sh
    sed -i 's/^/export /' /app/env.sh
    echo "$SCHEDULE bash -c 'source /app/env.sh && python -m paleonews run >> /proc/1/fd/1 2>&1'" > /etc/cron.d/paleonews
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
    printenv | grep -Ev '^(BASHOPTS|BASH_VERSINFO|EUID|PPID|SHELLOPTS|UID|_)=' > /app/env.sh
    sed -i 's/^/export /' /app/env.sh
    echo "$SCHEDULE bash -c 'source /app/env.sh && python -m paleonews run >> /proc/1/fd/1 2>&1'" > /etc/cron.d/paleonews
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

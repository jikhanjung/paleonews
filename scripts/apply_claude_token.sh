#!/usr/bin/env bash
#
# apply_claude_token.sh — Claude Max 구독 장기 토큰을 운영 컨테이너에 반영한다.
#
# 이 스크립트는 배포 디렉터리(/srv/paleonews)에 복사되어 그곳에서 실행된다
# (scripts/release.sh 가 함께 복사). cwd 의 .env / docker-compose.yml 을 대상으로 한다.
#
# 사용 전제:
#   1) 호스트에서 `claude setup-token` 을 실행해 장기 토큰을 발급받는다.
#      (브라우저 OAuth 로그인 → sk-ant-oat01-... 형태의 토큰 출력)
#   2) 그 토큰을 이 스크립트 인자로 넘긴다.
#
# 사용법:
#   ./apply_claude_token.sh sk-ant-oat01-XXXXXXXX...
#   # 또는
#   CLAUDE_NEW_TOKEN=sk-ant-oat01-... ./apply_claude_token.sh
#
# 동작:
#   - .env 백업 (.env.bak.<timestamp>)
#   - CLAUDE_CODE_OAUTH_TOKEN 추가/교체
#   - ANTHROPIC_API_KEY 주석 처리 (크레딧 종량제 폴백 차단)
#   - docker compose up -d 로 컨테이너 재생성 (env_file 재로딩)
#   - 구독 인증 + 실제 요약 1건으로 동작 검증
#
set -euo pipefail

cd "$(dirname "$0")"

TOKEN="${1:-${CLAUDE_NEW_TOKEN:-}}"
if [[ -z "$TOKEN" ]]; then
    echo "ERROR: 토큰이 없습니다." >&2
    echo "사용법: $0 <sk-ant-oat01-...토큰>" >&2
    echo "토큰 발급:  claude setup-token" >&2
    exit 1
fi
if [[ "$TOKEN" != sk-ant-oat* ]]; then
    echo "WARN: 토큰이 'sk-ant-oat'로 시작하지 않습니다. setup-token 출력이 맞는지 확인하세요." >&2
    echo "      그래도 진행하려면 5초 내 Ctrl-C 하지 마세요..." >&2
    sleep 5
fi

ENV_FILE=".env"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${ENV_FILE}.bak.${STAMP}"

cp -p "$ENV_FILE" "$BACKUP"
echo "[1/5] .env 백업 → $BACKUP"

# ANTHROPIC_API_KEY 주석 처리 (이미 주석이면 그대로)
if grep -qE '^[[:space:]]*ANTHROPIC_API_KEY=' "$ENV_FILE"; then
    sed -i -E 's|^([[:space:]]*ANTHROPIC_API_KEY=)|# (disabled by apply_claude_token.sh, 구독 billing 사용) \1|' "$ENV_FILE"
    echo "[2/5] ANTHROPIC_API_KEY 주석 처리"
else
    echo "[2/5] ANTHROPIC_API_KEY 활성 라인 없음 (건너뜀)"
fi

# CLAUDE_CODE_OAUTH_TOKEN 추가/교체
if grep -qE '^[[:space:]]*CLAUDE_CODE_OAUTH_TOKEN=' "$ENV_FILE"; then
    # 기존 라인 교체 (토큰에 # 가 없다고 가정, 구분자 다르게)
    sed -i -E "s#^[[:space:]]*CLAUDE_CODE_OAUTH_TOKEN=.*#CLAUDE_CODE_OAUTH_TOKEN=${TOKEN}#" "$ENV_FILE"
    echo "[3/5] CLAUDE_CODE_OAUTH_TOKEN 교체"
else
    printf '\n# --- Claude Max 구독 장기 토큰 (claude setup-token, %s 갱신) ---\nCLAUDE_CODE_OAUTH_TOKEN=%s\n' "$STAMP" "$TOKEN" >> "$ENV_FILE"
    echo "[3/5] CLAUDE_CODE_OAUTH_TOKEN 추가"
fi

echo "[4/5] 컨테이너 재생성 (docker compose up -d)..."
docker compose up -d

echo "[5/5] 검증..."
sleep 3
echo "  - 구독 인증 테스트:"
# claude 바이너리는 PATH 에서 검색 (0.2.8 슬림 이미지=/usr/local/bin, 구버전=/usr/bin)
if docker exec paleonews claude -p --model claude-sonnet-4-6 "한 단어로만 답: OK" >/tmp/_claude_test 2>&1; then
    echo "    ✅ CLI 응답: $(cat /tmp/_claude_test)"
else
    echo "    ❌ CLI 실패:"; sed 's/^/      /' /tmp/_claude_test
    echo "    → .env 를 백업($BACKUP)에서 복구하려면: cp $BACKUP $ENV_FILE && docker compose up -d" >&2
    exit 1
fi

echo "  - 요약 단계 1회 수동 실행:"
docker exec paleonews paleonews summarize 2>&1 | tail -5

echo
echo "완료. 정상 확인되면 발송까지 수동 실행하려면:"
echo "  docker exec paleonews paleonews send"
echo "또는 전체 파이프라인:"
echo "  docker exec paleonews paleonews run"

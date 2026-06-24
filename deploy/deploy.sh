#!/bin/bash
# 배포 디렉터리(/srv/paleonews)에서 실행된다. 레지스트리의 이미지를 pull 하고
# 단일 컨테이너를 재생성한다. 이미지 빌드/푸시는 scripts/release.sh 가 담당.
set -e

cd "$(dirname "$0")"

# .env 확인
if [ ! -f .env ]; then
    echo "오류: .env 파일이 없습니다."
    exit 1
fi

# 버전 태그 결정: 인자 > .env의 TAG > 오류
if [ -n "$1" ]; then
    TAG="$1"
elif grep -qP '^TAG=' .env 2>/dev/null; then
    TAG=$(grep -oP '^TAG=\K.*' .env)
else
    echo "사용법: $0 <버전>"
    echo "예시: $0 0.1.2"
    exit 1
fi

# .env의 TAG 업데이트
if grep -q '^TAG=' .env; then
    sed -i "s|^TAG=.*|TAG=$TAG|" .env
else
    echo "TAG=$TAG" >> .env
fi

# .env에서 설정 읽기
WEB_PORT=$(grep -oP '^WEB_PORT=\K.*' .env 2>/dev/null || echo "8080")
DATA_DIR=$(grep -oP '^DATA_DIR=\K.*' .env 2>/dev/null || echo "/srv/paleonews/data")
LOG_DIR=$(grep -oP '^LOG_DIR=\K.*' .env 2>/dev/null || echo "/srv/paleonews/logs")

echo "=== PaleoNews 배포 ==="
echo "이미지: honestjung/paleonews:$TAG"
echo "웹 포트: $WEB_PORT"
echo ""

# 데이터 디렉토리 확인
mkdir -p "$DATA_DIR" "$LOG_DIR"

# 이미지 pull
echo "--- 이미지 pull ---"
docker compose pull

# 기존 컨테이너 중지 및 재시작
echo ""
echo "--- 컨테이너 시작 ---"
docker compose down 2>/dev/null || true
docker compose up -d

echo ""
echo "--- 상태 ---"
docker compose ps

echo ""
echo "완료. 웹 UI: http://localhost:${WEB_PORT}"

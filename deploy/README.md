# PaleoNews Docker 배포

## 빠른 시작

```bash
# 1. 환경변수 설정
cp deploy/.env.example .env
# .env 파일에 API 키, 봇 토큰 입력

# 2. 봇 + 웹 UI 실행
docker compose -f deploy/docker-compose.yml up -d bot web

# 3. 파이프라인 수동 실행
docker compose -f deploy/docker-compose.yml run --rm pipeline

# 4. 웹 UI 접속
open http://localhost:8000
```

## 서비스 구성

| 서비스 | 설명 | 실행 방식 |
|--------|------|-----------|
| `pipeline` | RSS 수집→필터→크롤→요약→전송 | 수동/cron |
| `bot` | Telegram 봇 데몬 (대화, 구독 관리) | 상시 |
| `web` | 웹 관리 UI (사용자, 설정) | 상시 |

## cron 설정 (호스트)

```cron
0 8 * * * cd /path/to/paleonews && docker compose -f deploy/docker-compose.yml run --rm pipeline
```

## 데이터 영속성

- `paleonews-data` 볼륨: SQLite DB
- `paleonews-logs` 볼륨: 로그 파일

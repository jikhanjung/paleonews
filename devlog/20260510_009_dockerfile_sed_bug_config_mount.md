# Dockerfile sed 버그로 인한 fetcher 마비 + config.yaml 호스트 마운트 도입

**날짜**: 2026-05-10

## 증상

5/6일경부터 4일 연속 새 기사 0건. cron 자체는 매일 23:00 UTC에 정상 발화했으나 파이프라인 결과가 항상:

```
전체 기사:   628건
관련 기사:   276건
요약 완료:   276건
전송 완료:   276건
```

(고정 — fetcher가 아무것도 가져오지 않음)

로그에는 모든 피드에서 `Failed to parse feed ...: <unknown>:2:0: syntax error` 경고가 떴고, 경고의 "URL" 위치에 RSS URL 대신 **로그 파일 라인이 그대로** 들어가 있었음.

## 진단

1. 호스트에서 RSS 피드들을 직접 호출 → 정상 (science.org 39, sciencedaily 60, nature 75 등 280여 건 반환)
2. 컨테이너 안에서 `feedparser.parse(sources[0])` 직접 호출 → 정상 (39건 반환)
3. 그러나 `python -m paleonews fetch`는 0건
4. 차이 추적 → `cmd_fetch`는 `config["sources_file"]`로부터 source 경로를 읽음
5. 컨테이너 내 `config.yaml` 확인:
   ```yaml
   sources_file: "logs/paleonews.log"   # ← 잘못됨
   ```
6. 호스트 repo의 `config.yaml`은 정상 (`sources_file: "sources.txt"`)
7. git 이력에도 항상 `"sources.txt"` — 변경된 적 없음
8. 즉 이미지 빌드 시점에 누군가/무언가가 덮어씀

## 근본 원인

`deploy/Dockerfile` 19~20행의 sed 명령:

```dockerfile
sed -i 's|db_path:.*|db_path: "data/paleonews.db"|' config.yaml && \
sed -i 's|file:.*|file: "logs/paleonews.log"|' config.yaml
```

두 번째 sed의 패턴 `file:.*` 이 **앵커되지 않아** `sources_file: "sources.txt"`도 매치 (sources_file은 `file:`로 끝나는 문자열을 포함).

결과: 빌드 시 `sources_file`이 `logs/paleonews.log`로 덮어쓰여진 채 이미지가 만들어짐 → fetcher가 RSS 소스 파일 대신 로그 파일을 한 줄씩 읽어 feedparser에 raw string으로 전달 → 매 줄 XML 파싱 실패.

```bash
# 재현 검증
$ sed 's|file:.*|file: "logs/paleonews.log"|' config.yaml | grep sources_file
sources_file: "logs/paleonews.log"   # 의도치 않은 매칭
```

## 변경 사항

### 1. 즉시 복구 (호스트 마운트)

운영 서버에서 이미지 재빌드 없이 즉시 복구.

**`/srv/paleonews/config.yaml`** (신규) — 호스트 repo의 정상 config.yaml에서 `db_path`만 컨테이너용(`data/paleonews.db`)으로 조정한 사본 배치.

**`/srv/paleonews/docker-compose.yml`** — 볼륨 마운트 추가:

```yaml
volumes:
  - ${DATA_DIR:-/srv/paleonews/data}:/app/data
  - ${LOG_DIR:-/srv/paleonews/logs}:/app/logs
  - ./config.yaml:/app/config.yaml:ro      # ← 추가
```

`docker compose up -d` 재기동 직후:

```
$ docker exec paleonews python -m paleonews fetch
수집: 310건, 신규: 248건
```

4일치 누락분이 한 번에 들어옴.

### 2. 근본 수정 (이미지 0.2.3)

**`deploy/Dockerfile`** — sed 패턴에 `^` 앵커 추가:

```dockerfile
sed -i 's|^db_path:.*|db_path: "data/paleonews.db"|' config.yaml && \
sed -i 's|^  file:.*|  file: "logs/paleonews.log"|' config.yaml
```

`^db_path:` 와 `^  file:` (logging.file의 2-space 들여쓰기 포함)으로만 매치, `sources_file:`은 영향 없음.

**`pyproject.toml`** — `0.2.2` → `0.2.3`

빌드/푸시/배포:

```bash
docker build -f deploy/Dockerfile -t honestjung/paleonews:0.2.3 -t honestjung/paleonews:latest .
docker push honestjung/paleonews:0.2.3
docker push honestjung/paleonews:latest
sed -i 's|^TAG=.*|TAG=0.2.3|' /srv/paleonews/.env
cd /srv/paleonews && docker compose pull && docker compose up -d
```

### 3. 운영 패턴 변경: config.yaml 호스트 관리

이번 사고를 계기로 `config.yaml`을 환경별 호스트 설정으로 분리. 이미지 안의 config는 "기본값" 역할만, 운영 환경에서는 항상 호스트 마운트가 우선. 향후 키워드/필터/모델 변경 시 재빌드 불필요.

## 검증

배포 후 상태:

```
컨테이너:    honestjung/paleonews:0.2.3 (Up)
config:      sources_file: "sources.txt"  ✅
             db_path: "data/paleonews.db" ✅
DB 통계:     전체 876건 (+248 신규), 관련 276건
```

신규 248건은 다음 cron(2026-05-10 23:00 UTC = 2026-05-11 08:00 KST)에서 filter → crawl → summarize → send 단계를 통해 사용자에게 전송 예정.

## 교훈

- **Sed 패턴은 항상 앵커링**. `s|file:.*|...|` 같은 비앵커 패턴은 부분 문자열 매칭으로 의도치 않은 라인을 잡음. `^`, `$`, 단어 경계 활용.
- **빌드 시 변형 vs 컴포즈 마운트**: 환경별로 달라질 수 있는 설정은 빌드 단계에서 굳히지 말고 런타임 마운트로. 이미지는 immutable하게, 환경 차이는 mount/env로.
- **로그 인터리빙으로 진단 어려움**: telegram bot stderr와 cron 파이프라인 stdout이 같은 docker stdout으로 합쳐져 fetcher 경고 메시지 안에 다른 라인이 끼어 보임. 향후 별도 로그 채널 분리 검토 필요(별건 작업).

## 버전 이력

| 버전 | 내용 |
|------|------|
| 0.2.3 | Dockerfile sed regex 앵커링 (sources_file 덮어쓰기 버그 수정) |

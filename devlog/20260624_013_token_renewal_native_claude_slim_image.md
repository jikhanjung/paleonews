# 구독 토큰 만료 복구 + Docker 이미지 슬림화(네이티브 claude 바이너리) (0.2.8)

**날짜**: 2026-06-24

## 배경

6/21 아침부터 뉴스 발송이 중단됨. 증상이 까다로웠던 점은 `pipeline_runs.status`가
계속 `success`로 찍혔다는 것 — 단계별 독립 실행 구조라 요약이 전건 실패해도
파이프라인은 죽지 않고 넘어가, 겉으로는 정상처럼 보였다.

진단 결과 두 가지가 동시에 터져 있었다.

- 마운트된 Max 구독 OAuth 토큰(`/srv/paleonews/claude/.credentials.json`)이
  **2026-06-21 07:00 UTC에 만료**, refresh도 `401 Invalid authentication credentials`로
  거부 → 구독 경로 사망.
- 폴백 경로인 `ANTHROPIC_API_KEY`는 해당 계정 **크레딧 잔액 부족**으로 이미 막혀 있음.

즉 0.2.7([[20260619_012_claude_subscription_billing_fix]])에서 API 키 폴백을
차단해둔 상태라, 구독 토큰이 죽자 LLM 호출이 전부 실패했다.

타임라인이 정확히 일치:

| 시각 (UTC) | 사건 |
|-----------|------|
| 6/20 23:00 | 정상 요약·발송 (dispatches 418) |
| **6/21 07:00** | 구독 토큰 만료 |
| 6/21 23:00 | 요약 전건 실패 → 발송 0 |
| 6/22 23:00 | 동일 |

## 변경 사항

### 1. 구독 인증 복구 — 장기 토큰 방식

마운트된 대화형 `.credentials.json`은 세션에 묶이고 자동 갱신 시 호스트와
컨테이너가 서로의 토큰을 무효화할 수 있어 운영용으로 부적합. **`claude setup-token`이
발급하는 계정 단위 장기 토큰**(`sk-ant-oat01-…`)을 `CLAUDE_CODE_OAUTH_TOKEN`
환경변수로 주입하는 방식으로 전환.

- `apply_claude_token.sh`(`/srv/paleonews/`) 작성: `.env` 백업 → `ANTHROPIC_API_KEY`
  주석 처리(크레딧 폴백 차단) → `CLAUDE_CODE_OAUTH_TOKEN` 추가 → `docker compose up -d`
  (env_file는 `restart`로는 재로딩 안 되고 **재생성** 필요) → 인증+요약 검증.
- `llm.py`는 구독 모드(`bare=False`)에서 `ANTHROPIC_API_KEY`를 이미 제거하므로
  env의 OAuth 토큰이 우선 적용됨.
- 적용 후 요약 20건·텔레그램 발송 20건 성공으로 즉시 정상화.

### 2. Docker 이미지 멀티스테이지 슬림화 — `deploy/Dockerfile`

claude CLi 도입(0.2.5) 이후 이미지가 322MB → 1.13GB로 급증해 있었음. 원인 분석:

- 현재 Claude Code CLI는 **Node 앱이 아니라 단독 네이티브 ELF 바이너리**
  (`ldd` 의존성이 libc/librt/libpthread뿐, ~224MB). npm 패키지는 이 바이너리를
  감싸는 래퍼였고, `node`(120MB)+`npm`/`node_modules`+nodesource 잔재가 전부 사장.

3-스테이지로 재구성:

- `pybuild` — lxml 빌드 헤더(`libxml2-dev`/`libxslt1-dev`)는 여기서만 사용,
  `pip install --prefix=/install`로 격리 설치.
- `claudecli` — `curl -fsSL https://claude.ai/install.sh | bash`로 **네이티브
  바이너리만** 설치 (`/root/.local/share/claude/versions/<v>`, 런처
  `/root/.local/bin/claude`). 마운트되는 `/root/.claude`에는 아무것도 안 떨어짐.
- runtime — `/install`→`/usr/local`, `/root/.local` 복사 후
  `/usr/local/bin/claude` 심볼릭. 시스템 deps는 `cron ca-certificates libxml2 libxslt1.1`만.

entrypoint는 `python -m paleonews`(시스템 python, venv 미사용)를 쓰고 cron은
`export -p > /app/env.sh`로 env(PATH 포함)를 캡처하므로 `/usr/local/bin/claude`를
cron도 정상 인식.

**결과: 1.13GB → 615MB (약 46% 감소).** 네이티브 바이너리 224MB가 최대 단일
구성요소이고 나머지는 python:3.12-slim 베이스 + 파이썬 의존성.

### 3. 배포 자동화 + repo를 산출물 source of truth로

운영(`/srv/paleonews`)과 repo의 배포 산출물이 드리프트해 있었음 — repo
`deploy/docker-compose.yml`은 구버전 3-컨테이너, 실제 운영은 단일 `all` 컨테이너;
`deploy.sh`는 repo에 없고 호스트에만 존재.

- `deploy/docker-compose.yml`을 운영 정본(단일 컨테이너, config/claude 마운트)으로 교체.
- `deploy/deploy.sh`(호스트 pull+재생성), `scripts/apply_claude_token.sh`(토큰 갱신)를 repo에 포함.
- `scripts/release.sh` 추가: 빌드 → push → 배포 산출물을 `/srv/paleonews`로 복사 →
  그곳에서 `deploy.sh` 실행. 호스트 상태(`.env`/`config.yaml`/`claude`/`data`/`logs`)는
  복사 대상에서 제외. `--no-build`/`--no-deploy` 플래그 지원.
- `apply_claude_token.sh`의 검증 단계가 `/usr/bin/claude`를 하드코딩하던 것을
  PATH 검색(`claude`)으로 수정 — 0.2.8 슬림 이미지는 `/usr/local/bin/claude`.

### 4. 버전 bump — `pyproject.toml`

`0.2.7 → 0.2.8`.

## 검증

- 슬림 이미지 빌드 후: node/npm 부재, claude 2.1.187 on PATH, python import 및
  `python -m paleonews` 정상, `CLAUDE_CODE_OAUTH_TOKEN` 인증 경로 동작.
- 운영 배포(`deploy.sh 0.2.8`) 후 라이브 점검: 컨테이너 0.2.8 running, node 없음,
  요약 20건 성공.

## 운영 영향

- 발송 정상화. 매일 cron(23:00 UTC)도 동일 env의 `CLAUDE_CODE_OAUTH_TOKEN` 사용.
- 구독 토큰 만료 재발 대비: 장기 토큰(보통 1년 유효) 사용 + `apply_claude_token.sh`로
  재주입 절차 표준화. 참고: [[deploy-claude-code-provider]].
- 이미지 절반 크기 → pull/배포/디스크 비용 절감.

## 버전 이력

| 버전 | 내용 |
|------|------|
| 0.2.8 | 구독 OAuth 장기 토큰(`CLAUDE_CODE_OAUTH_TOKEN`) 전환으로 발송 복구, Docker 멀티스테이지 + 네이티브 claude 바이너리로 이미지 1.13GB→615MB |

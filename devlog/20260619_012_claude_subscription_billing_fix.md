# claude_code provider 구독 과금 수정 + 기본 모델 정렬 (0.2.7)

**날짜**: 2026-06-19

## 배경

운영 환경(단일 Docker `all` 모드, claude CLI + Max 구독)에서 요약/필터/챗 호출이
모두 `Credit balance is too low` 에러로 실패. 원인은 `claude_code` provider가
`claude -p`를 **상속받은 환경 그대로** 실행한 점.

- `bare=False`(구독/OAuth 모드)로 의도했으나, 환경에 `ANTHROPIC_API_KEY`가 남아
  있으면 CLI가 구독 대신 **API 크레딧 과금**으로 폴백.
- 해당 키의 크레딧 잔액이 비어 있어 모든 LLM 호출이 실패.

문서화된 의도는 `bare=false → OAuth 구독`, `bare=true → API 키` 였으나 구현이
이를 강제하지 않았음. 참고: [[deploy-claude-code-provider]].

## 변경 사항

### 1. 구독 과금 강제 — `paleonews/llm.py` (`a4126af`)

`ClaudeCodeClient`가 subprocess 실행 시 환경을 복사하고, `bare=False`일 때
`ANTHROPIC_API_KEY`를 제거:

```python
env = os.environ.copy()
if not self.bare:
    # Force OAuth/subscription billing — an ANTHROPIC_API_KEY in the
    # environment would otherwise make the CLI bill API credits.
    env.pop("ANTHROPIC_API_KEY", None)
result = subprocess.run(cmd, ..., env=env)
```

- `bare=True`(API 키 모드)는 키를 그대로 두어 기존 동작 유지.
- docstring에 구독/크레딧 과금 분기 명시.

### 2. 기본 요약 모델 정렬 — `config.yaml` (`f1a5ba8`)

```diff
 summarizer:
-  model: "claude-sonnet-4-20250514"
+  model: "claude-sonnet-4-6"
```

운영은 이미 `app_settings` overlay([[20260510_011_app_settings_overlay_model_picker 참고]])로
`claude-sonnet-4-6`를 쓰고 있었음. baked-in 기본값이 구버전에 머물러 있어,
새 이미지 빌드나 overlay 초기화 시 운영과 어긋나는 문제를 정렬.

### 3. 버전 bump — `pyproject.toml` (`346c602`)

`0.2.6 → 0.2.7`.

### 4. CLAUDE.md 문서 갱신 (`75819ae`, `57acff0`)

- Phase 5/6 상태 및 운영 배포 구조(단일 컨테이너 `all` 모드 = cron+bot+web,
  이미지 태그 = pyproject 버전, `deploy.sh <버전>`) 문서화.
- 순수 문서 변경, 코드 영향 없음.

## 운영 영향

- 운영 컨테이너 환경에서 `ANTHROPIC_API_KEY`를 빼지 않아도 됨 — 구독 모드에서는
  코드가 알아서 제거하므로 `Credit balance is too low` 재발 방지.
- `bare=True`로 명시적으로 API 키 과금을 원하는 경우는 영향 없음.
- 기본 모델이 운영값과 일치하므로 fresh 이미지/overlay 초기화 시에도 동일 모델 사용.

## 버전 이력

| 버전 | 내용 |
|------|------|
| 0.2.7 | claude_code 구독 과금 강제(API_KEY strip), 기본 요약 모델 `claude-sonnet-4-6` 정렬, CLAUDE.md 운영 배포 구조 문서화 |

# LLM 프로바이더 추상화: Anthropic/OpenAI 선택 지원

**날짜**: 2026-03-17

## 배경

기존에는 Claude API(Anthropic)만 사용하도록 하드코딩되어 있었음. OpenAI API도 사용할 수 있도록 설정으로 선택 가능하게 변경.

## 변경 사항

### 신규 파일: `paleonews/llm.py`
- `LLMClient` 추상 클래스 정의 — `chat(model, prompt, system, max_tokens) -> str`
- `AnthropicClient`: Anthropic Messages API 래핑
- `OpenAIClient`: OpenAI Chat Completions API 래핑
- `create_llm_client(config)`: `config.yaml`의 `llm.provider` 값에 따라 클라이언트 생성

### 수정: `paleonews/summarizer.py`
- `from anthropic import Anthropic` → `from .llm import LLMClient`
- `client.messages.create(...)` → `client.chat(...)` 호출로 변경

### 수정: `paleonews/filter.py`
- 동일하게 `Anthropic` 직접 의존 제거, `LLMClient` 인터페이스 사용

### 수정: `paleonews/__main__.py`
- `Anthropic()` 직접 생성 → `create_llm_client(config)` 팩토리 사용

### 수정: `config.yaml`
- `llm.provider` 설정 추가 (기본값: `"anthropic"`)

```yaml
llm:
  provider: "anthropic"    # anthropic 또는 openai
```

### 수정: `pyproject.toml`
- `openai` 패키지 의존성 추가

## 사용법

### Anthropic (기존 그대로)
```yaml
llm:
  provider: "anthropic"
```
`.env`에 `ANTHROPIC_API_KEY` 설정.

### OpenAI로 전환
```yaml
llm:
  provider: "openai"

filter:
  llm_filter:
    model: "gpt-4o-mini"

summarizer:
  model: "gpt-4o"
```
`.env`에 `OPENAI_API_KEY` 설정.

## 테스트
- 기존 41개 테스트 전부 통과 (LLM 호출 테스트는 없으므로 영향 없음)
- Anthropic 설정으로 전체 파이프라인(`paleonews run`) 정상 동작 확인

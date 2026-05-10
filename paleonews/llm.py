"""LLM provider abstraction — supports Anthropic SDK, OpenAI SDK, and Claude Code CLI."""

import logging
import shutil
import subprocess
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    @abstractmethod
    def chat(self, model: str, prompt: str, *, system: str = "", max_tokens: int = 512) -> str:
        ...


class AnthropicClient(LLMClient):
    def __init__(self):
        from anthropic import Anthropic
        self._client = Anthropic()

    def chat(self, model: str, prompt: str, *, system: str = "", max_tokens: int = 512) -> str:
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        return response.content[0].text.strip()


class OpenAIClient(LLMClient):
    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI()

    def chat(self, model: str, prompt: str, *, system: str = "", max_tokens: int = 512) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        return response.choices[0].message.content.strip()


class ClaudeCodeClient(LLMClient):
    """Invokes the `claude` CLI in non-interactive (`-p`) mode.

    Requires the Claude Code CLI to be installed and authenticated
    (either via ANTHROPIC_API_KEY env var with bare=True, or via
    `claude /login` for subscription auth). The CLI does not honor
    a max_tokens parameter, so it is ignored here.
    """

    def __init__(
        self,
        claude_path: str | None = None,
        bare: bool = False,
        timeout: int = 180,
        extra_args: list[str] | None = None,
    ):
        self.claude_path = claude_path or shutil.which("claude") or "claude"
        self.bare = bare
        self.timeout = timeout
        self.extra_args = list(extra_args or [])

    def chat(self, model: str, prompt: str, *, system: str = "", max_tokens: int = 512) -> str:
        cmd: list[str] = [self.claude_path, "-p", "--model", model]
        if self.bare:
            cmd.append("--bare")
        if system:
            cmd += ["--append-system-prompt", system]
        cmd += self.extra_args
        cmd.append(prompt)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"claude CLI timed out after {self.timeout}s"
            ) from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or "(no stderr)"
            raise RuntimeError(
                f"claude CLI failed (exit {e.returncode}): {stderr}"
            ) from e
        return result.stdout.strip()


def create_llm_client(config: dict) -> LLMClient:
    llm_config = config.get("llm", {})
    provider = llm_config.get("provider", "anthropic").lower()
    if provider == "openai":
        logger.info("Using OpenAI LLM provider")
        return OpenAIClient()
    if provider == "anthropic":
        logger.info("Using Anthropic LLM provider")
        return AnthropicClient()
    if provider in ("claude_code", "claude-code", "cli"):
        logger.info("Using Claude Code CLI provider")
        return ClaudeCodeClient(
            claude_path=llm_config.get("claude_path"),
            bare=llm_config.get("bare", False),
            timeout=llm_config.get("timeout", 180),
            extra_args=llm_config.get("extra_args"),
        )
    raise ValueError(f"Unknown LLM provider: {provider}")

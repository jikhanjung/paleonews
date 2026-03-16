"""LLM provider abstraction — supports Anthropic and OpenAI."""

import logging
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


def create_llm_client(config: dict) -> LLMClient:
    provider = config.get("llm", {}).get("provider", "anthropic").lower()
    if provider == "openai":
        logger.info("Using OpenAI LLM provider")
        return OpenAIClient()
    elif provider == "anthropic":
        logger.info("Using Anthropic LLM provider")
        return AnthropicClient()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

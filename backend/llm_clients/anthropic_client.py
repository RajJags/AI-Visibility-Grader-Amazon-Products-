"""Anthropic Claude client with exponential-backoff retry."""

import os
import anthropic
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .base import BaseLLMClient


class AnthropicClient(BaseLLMClient):
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )
        self.model = "claude-sonnet-4-20250514"

    @retry(
        retry=retry_if_exception_type(anthropic.RateLimitError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
    )
    async def query(self, prompt: str, system: str = "") -> str:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        response = await self._client.messages.create(**kwargs)
        return response.content[0].text if response.content else ""

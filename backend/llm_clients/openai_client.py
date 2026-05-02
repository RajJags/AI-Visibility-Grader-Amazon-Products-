"""OpenAI GPT-4o client with exponential-backoff retry."""

import os
from openai import AsyncOpenAI, RateLimitError, APIStatusError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .base import BaseLLMClient


class OpenAIClient(BaseLLMClient):
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = "gpt-4o"

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIStatusError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
    )
    async def query(self, prompt: str, system: str = "") -> str:
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            )
            return response.choices[0].message.content or ""
        except RateLimitError as e:
            body = getattr(e, "body", {}) or {}
            code = (body.get("error") or {}).get("code", "")
            if code == "insufficient_quota":
                raise RuntimeError(
                    "OpenAI quota exceeded — add billing at platform.openai.com"
                ) from e
            raise

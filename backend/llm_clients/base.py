"""Abstract base class for all LLM clients."""

from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    """All LLM clients implement a single async query method."""

    @abstractmethod
    async def query(self, prompt: str, system: str = "") -> str:
        """Send *prompt* to the model and return the text response."""
        ...

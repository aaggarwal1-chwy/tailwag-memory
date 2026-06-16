from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import math


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return one embedding vector for the supplied text."""


class MockOpenAIEmbeddingProvider(EmbeddingProvider):
    """Deterministic OpenAI-shaped embedding mock with no network calls."""

    def __init__(self, dimension: int = 64) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        counter = 0

        while len(values) < self.dimension:
            block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for byte in block:
                centered = (byte / 255.0) * 2.0 - 1.0
                values.append(centered)
                if len(values) == self.dimension:
                    break
            counter += 1

        magnitude = math.sqrt(sum(value * value for value in values))
        if magnitude == 0:
            return values
        return [round(value / magnitude, 8) for value in values]

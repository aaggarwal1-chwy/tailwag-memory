from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import math
from typing import Any


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return one embedding vector for the supplied text."""


class OpenAIConfigurationError(RuntimeError):
    """Raised when an OpenAI-backed provider is used without configuration."""


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-backed embedding provider used by production services."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        dimension: int = 64,
        client: Any | None = None,
    ) -> None:
        """Configure an OpenAI embedding provider."""

        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self._client = client

    def embed(self, text: str) -> list[float]:
        """Generate an embedding using the configured OpenAI model."""

        response = self._openai_client().embeddings.create(
            model=self.model,
            input=text,
            dimensions=self.dimension,
        )
        embedding = list(self._extract_embedding(response))
        if len(embedding) != self.dimension:
            raise OpenAIConfigurationError(
                f"OpenAI embedding returned {len(embedding)} dimensions; expected {self.dimension}."
            )
        return embedding

    def _openai_client(self) -> Any:
        """Return a cached OpenAI client or create one from the API key."""

        if self._client is not None:
            return self._client
        if not self.api_key:
            raise OpenAIConfigurationError("OPENAI_API_KEY is required for OpenAI embeddings.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAIConfigurationError("Install the openai package to use OpenAI embeddings.") from exc
        self._client = OpenAI(api_key=self.api_key)
        return self._client

    def _extract_embedding(self, response: Any) -> list[float]:
        """Extract the first embedding vector from an OpenAI response."""

        if isinstance(response, dict):
            return response["data"][0]["embedding"]
        return response.data[0].embedding


class MockOpenAIEmbeddingProvider(EmbeddingProvider):
    """Deterministic OpenAI-shaped embedding mock with no network calls."""

    def __init__(self, dimension: int = 64) -> None:
        """Configure the deterministic mock embedding dimension."""

        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        """Generate a deterministic normalized embedding for text."""

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

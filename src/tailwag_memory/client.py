from __future__ import annotations

from datetime import datetime

from .config import Settings, load_settings
from .db import Neo4jQueryRunner
from .embeddings import OpenAIEmbeddingProvider
from .ingestion import EpisodeIngestionService
from .memory_context import PersonMemoryContextService
from .memory_items import EpisodeMemoryExtractionService, OpenAIMemoryExtractionProvider
from .models import EpisodeInput, EpisodeMemoryExtractionResult, EpisodeRecordResult
from .retrieval import PersonContextRetrievalService
from .synthesis import OpenAIPersonContextProvider, PersonContextSynthesisService


class TailwagMemoryClient:
    """Coordinate high-level Tailwag memory operations."""

    def __init__(
        self,
        runner: Neo4jQueryRunner,
        settings: Settings,
    ) -> None:
        """Create a client from an existing query runner and settings."""
        self.runner = runner
        self.settings = settings
        self._embedding_provider: OpenAIEmbeddingProvider | None = None

    @classmethod
    def from_env(cls) -> "TailwagMemoryClient":
        """Create a client from environment-backed settings."""
        settings = load_settings()
        return cls(Neo4jQueryRunner(settings), settings)

    def close(self) -> None:
        """Close the underlying query runner."""
        self.runner.close()

    def __enter__(self) -> "TailwagMemoryClient":
        """Enter the client context manager."""
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Close the client when leaving a context manager."""
        self.close()

    def person_context(
        self,
        person_id: str,
        limit: int = 10,
        semantic_scope: str | None = None,
        *,
        current_text: str | None = None,
        now: datetime | None = None,
        memory_limit: int = 12,
        recent_episode_limit: int = 5,
    ) -> str:
        """Return combined durable and synthesized context for a person."""
        memory_context = PersonMemoryContextService(self.runner, self._embeddings()).markdown_for_person(
            person_id,
            current_text=current_text or semantic_scope,
            now=now,
            memory_limit=memory_limit,
            recent_episode_limit=recent_episode_limit,
        )
        embeddings = self._embeddings()
        retrieval = PersonContextRetrievalService(self.runner, embeddings)
        provider = OpenAIPersonContextProvider(
            api_key=self.settings.openai_api_key,
            model=self.settings.synthesis_model,
        )
        synthesized_context = PersonContextSynthesisService(retrieval, provider).context_for_person(
            person_id,
            limit=limit,
            semantic_scope=semantic_scope,
        )
        return "\n\n".join(part for part in [memory_context, synthesized_context] if part)

    def record_episode(self, episode: EpisodeInput, *, extract_memory: bool = True) -> EpisodeRecordResult:
        """Store an episode and optionally extract durable memory items."""
        episode_id = EpisodeIngestionService(self.runner, self._embeddings()).ingest(episode)
        if not extract_memory:
            return EpisodeRecordResult(episode_id=episode_id)
        extraction = self._memory_extraction_service().extract_for_episode(episode, speaker_only=False)
        return EpisodeRecordResult(
            episode_id=episode_id,
            memory_results=extraction.memory_results,
            memory_errors=extraction.memory_errors,
        )

    def extract_memory_for_episode(
        self,
        episode_id: str,
        person_id: str | None = None,
    ) -> EpisodeMemoryExtractionResult:
        """Extract durable memory items for a stored episode."""
        return self._memory_extraction_service().extract_for_stored_episode(
            episode_id,
            person_id=person_id,
            speaker_only=True,
        )

    def _embeddings(self) -> OpenAIEmbeddingProvider:
        """Return the lazily initialized embedding provider."""
        if self._embedding_provider is None:
            self._embedding_provider = OpenAIEmbeddingProvider(
                api_key=self.settings.openai_api_key,
                model=self.settings.embedding_model,
                dimension=self.settings.embedding_dimension,
            )
        return self._embedding_provider

    def _memory_extraction_service(self) -> EpisodeMemoryExtractionService:
        """Build a memory extraction service using client settings."""
        return EpisodeMemoryExtractionService(
            self.runner,
            self._embeddings(),
            OpenAIMemoryExtractionProvider(
                api_key=self.settings.openai_api_key,
                model=self.settings.synthesis_model,
            ),
        )

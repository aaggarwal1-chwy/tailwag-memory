from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from .config import Settings, load_settings
from .db import Neo4jQueryRunner
from .embeddings import OpenAIEmbeddingProvider
from .episode_normalization import normalize_robot_speaker_labels
from .ingestion import EpisodeIngestionService, PersonIngestionService
from .memory_context import PersonMemoryContextService
from .memory_items import (
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
    EpisodeMemoryExtractionService,
    MemoryConsolidationService,
    OpenAIMemoryConsolidationProvider,
    OpenAIMemoryExtractionProvider,
)
from .memory_item_service import MemoryItemService
from .models import (
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    EpisodeRecordResult,
    MemoryConsolidationResult,
    PersonInput,
    SearchQuery,
)
from .retrieval import EpisodeRetrievalService, PersonContextRetrievalService


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

    def upsert_person(self, person: PersonInput) -> str:
        """Create or update a person profile without generating embeddings."""
        return PersonIngestionService(self.runner).upsert(person)

    def archive_person(self, person_id: str) -> bool:
        """Archive a person profile while preserving historical graph data."""
        return PersonIngestionService(self.runner).archive(person_id)

    def rekey_person_by_email(self, email: str, new_person_id: str) -> bool:
        """Rekey one email-matched person to a canonical id without embeddings."""
        return PersonIngestionService(self.runner).rekey_by_email(email, new_person_id)

    def canonical_person_id_by_email(self, email: str) -> str | None:
        """Return one canonical Argos person id for an email when unambiguous."""
        return PersonIngestionService(self.runner).canonical_id_by_email(email)

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
        """Return deterministic durable and retrieved context for a person."""
        memory_context = PersonMemoryContextService(self.runner, self._embeddings()).markdown_for_person(
            person_id,
            current_text=current_text or semantic_scope,
            now=now,
            memory_limit=memory_limit,
            recent_episode_limit=recent_episode_limit,
        )
        retrieved_context = PersonContextRetrievalService(self.runner, self._embeddings()).markdown_for_person(
            person_id,
            limit=limit,
            semantic_scope=semantic_scope,
        )
        return "\n\n".join(part for part in [memory_context, retrieved_context] if part)

    def search_semantic_memory(
        self,
        *,
        text: str,
        person_id: str,
        building_code: str | None = None,
        limit: int = 5,
        now: datetime | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        """Return vector-ranked episode and memory-item matches for one person."""
        rendered_text = str(text or "").strip()
        rendered_person_id = str(person_id or "").strip()
        if not rendered_text or not rendered_person_id:
            return {"episodes": [], "memory_items": []}

        bounded_limit = _bounded_search_limit(limit)
        embeddings = self._embeddings()
        episode_results = EpisodeRetrievalService(self.runner, embeddings).hybrid_search(
            SearchQuery(
                text=rendered_text,
                person_id=rendered_person_id,
                building_code=_normalize_optional_text(building_code),
                limit=bounded_limit,
            )
        )
        memory_item_results = MemoryItemService(self.runner, embeddings).vector_search(
            person_id=rendered_person_id,
            text=rendered_text,
            limit=bounded_limit,
            now=now,
        )
        return {
            "episodes": [asdict(result) for result in episode_results],
            "memory_items": [asdict(result) for result in memory_item_results],
        }

    def record_episode(self, episode: EpisodeInput, *, extract_memory: bool = True) -> EpisodeRecordResult:
        """Store an episode and optionally extract durable memory items."""
        episode = normalize_robot_speaker_labels(episode)
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

    def consolidate_memory(
        self,
        *,
        person_id: str | None = None,
        all_people: bool = False,
        person_limit: int = 100,
        min_evidence_episodes: int = DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
        seed_limit: int = 25,
        neighbor_limit: int = 12,
        cluster_limit: int = 8,
        episode_text_limit: int = 1200,
    ) -> MemoryConsolidationResult:
        """Consolidate repeated episode evidence into per-person memory items."""
        service = self._memory_consolidation_service()
        if all_people:
            return service.consolidate_all(
                person_limit=person_limit,
                min_evidence_episodes=min_evidence_episodes,
                seed_limit=seed_limit,
                neighbor_limit=neighbor_limit,
                cluster_limit=cluster_limit,
                episode_text_limit=episode_text_limit,
            )
        rendered_person_id = str(person_id or "").strip()
        if not rendered_person_id:
            raise ValueError("person_id is required unless all_people is true")
        return MemoryConsolidationResult(
            person_results=[
                service.consolidate_person(
                    rendered_person_id,
                    min_evidence_episodes=min_evidence_episodes,
                    seed_limit=seed_limit,
                    neighbor_limit=neighbor_limit,
                    cluster_limit=cluster_limit,
                    episode_text_limit=episode_text_limit,
                )
            ]
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

    def _memory_consolidation_service(self) -> MemoryConsolidationService:
        """Build a memory consolidation service using client settings."""
        return MemoryConsolidationService(
            self.runner,
            self._embeddings(),
            OpenAIMemoryConsolidationProvider(
                api_key=self.settings.openai_api_key,
                model=self.settings.synthesis_model,
            ),
        )


def _normalize_optional_text(value: str | None) -> str | None:
    """Normalize optional string filters for semantic search."""
    rendered = str(value or "").strip()
    return rendered or None


def _bounded_search_limit(limit: int) -> int:
    """Return a positive semantic search limit."""
    try:
        return max(1, int(limit))
    except (TypeError, ValueError):
        return 5

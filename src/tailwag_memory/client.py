from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from .config import Settings, load_settings
from .db import Neo4jQueryRunner
from .embeddings import OpenAIEmbeddingProvider
from .episode_normalization import normalize_robot_speaker_labels
from .ingestion import EpisodeIngestionService, PersonIngestionService
from .biometrics import BiometricReferenceService
from .identity import DirectoryIdentityService
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
    BiometricEnrollmentResult,
    BiometricSearchResult,
    BiometricUpdateResult,
    DirectoryPersonRecord,
    DirectorySyncResult,
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    EpisodeRecordResult,
    IdentityResolutionResult,
    MemoryConsolidationResult,
    OwnerResolutionResult,
    PersonContextResult,
    PersonInput,
    PersonProfile,
    SearchQuery,
    VerifiedProfile,
)
from .ownership import TurnOwnerResolutionService
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
        """Return one caller-owned canonical person id for an email when unambiguous."""
        return PersonIngestionService(self.runner).canonical_id_by_email(email)

    def sync_directory_people(
        self,
        site_code: str,
        records: list[DirectoryPersonRecord] | list[dict[str, object]],
    ) -> DirectorySyncResult:
        """Store normalized employee-directory rows for a site."""
        return DirectoryIdentityService(self.runner).sync_directory_people(site_code, records)

    def sync_directory_from_snowflake(
        self,
        site_code: str,
        *,
        email_domain: str = "",
    ) -> DirectorySyncResult:
        """Load a site directory from Snowflake into Tailwag."""
        return DirectoryIdentityService(self.runner).sync_directory_from_snowflake(
            site_code,
            email_domain=email_domain,
        )

    def resolve_identity(
        self,
        *,
        shared_first_name: str,
        shared_last_name: str,
        shared_name: str = "",
        site_code: str = "",
    ) -> IdentityResolutionResult:
        """Resolve a spoken employee name against Tailwag-owned directory rows."""
        return DirectoryIdentityService(self.runner).resolve_identity(
            shared_first_name=shared_first_name,
            shared_last_name=shared_last_name,
            shared_name=shared_name,
            site_code=site_code,
        )

    def get_verified_profile(
        self,
        *,
        username: str,
        official_name: str,
        site_code: str = "",
    ) -> VerifiedProfile | None:
        """Return a verified directory profile for enrollment rehydration."""
        return DirectoryIdentityService(self.runner).get_verified_profile(
            username=username,
            official_name=official_name,
            site_code=site_code,
        )

    def person_profile(self, person_id: str) -> PersonProfile | None:
        """Return a prompt/runtime person profile."""
        return DirectoryIdentityService(self.runner).person_profile(person_id)

    def record_encounter(
        self,
        person_id: str,
        *,
        observed_at: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PersonProfile:
        """Update a person's last_seen and interaction count."""
        return DirectoryIdentityService(self.runner).record_encounter(
            person_id=person_id,
            observed_at=observed_at,
            metadata=dict(metadata or {}),
        )

    def enroll_face_reference(
        self,
        *,
        person_id: str,
        embedding: list[float],
        metadata: dict[str, object] | None = None,
        consent_status: str = "consented",
    ) -> BiometricEnrollmentResult:
        """Store one face reference vector for a person."""
        return self._biometrics().enroll_face_reference(
            person_id=person_id,
            embedding=embedding,
            metadata=dict(metadata or {}),
            consent_status=consent_status,
        )

    def search_face(
        self,
        *,
        embedding: list[float],
        limit: int = 2,
        site_code: str | None = None,
    ) -> BiometricSearchResult:
        """Search consented face references."""
        return self._biometrics().search_face(
            embedding=embedding,
            limit=limit,
            site_code=site_code,
        )

    def enroll_voice_reference(
        self,
        *,
        person_id: str,
        embedding: list[float],
        metadata: dict[str, object] | None = None,
        consent_status: str = "consented",
    ) -> BiometricEnrollmentResult:
        """Store one voice reference vector for a person."""
        return self._biometrics().enroll_voice_reference(
            person_id=person_id,
            embedding=embedding,
            metadata=dict(metadata or {}),
            consent_status=consent_status,
        )

    def search_voice(
        self,
        *,
        embedding: list[float],
        limit: int = 2,
        site_code: str | None = None,
    ) -> BiometricSearchResult:
        """Search consented voice references."""
        return self._biometrics().search_voice(
            embedding=embedding,
            limit=limit,
            site_code=site_code,
        )

    def has_voice_reference(self, person_id: str) -> bool:
        """Return whether a person has at least one active voice reference."""
        return self._biometrics().has_voice_reference(person_id)

    def observe_face_embedding(
        self,
        *,
        person_id: str,
        embedding: list[float],
        evidence: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> BiometricUpdateResult:
        """Offer one face observation for adaptive reference aggregation."""
        return self._biometrics().observe_face_embedding(
            person_id=person_id,
            embedding=embedding,
            evidence=dict(evidence or {}),
            metadata=dict(metadata or {}),
        )

    def observe_voice_embedding(
        self,
        *,
        person_id: str,
        embedding: list[float],
        evidence: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> BiometricUpdateResult:
        """Offer one voice observation for adaptive reference aggregation."""
        return self._biometrics().observe_voice_embedding(
            person_id=person_id,
            embedding=embedding,
            evidence=dict(evidence or {}),
            metadata=dict(metadata or {}),
        )

    def resolve_turn_owner(
        self,
        *,
        primary_face_candidate: object | None = None,
        visible_face_candidates: list[object] | tuple[object, ...] | None = None,
        voice_candidate: object | None = None,
        policy_context: dict[str, object] | None = None,
    ) -> OwnerResolutionResult:
        """Resolve final turn ownership from identity evidence."""
        return TurnOwnerResolutionService().resolve_turn_owner(
            primary_face_candidate=primary_face_candidate,
            visible_face_candidates=visible_face_candidates,
            voice_candidate=voice_candidate,
            policy_context=dict(policy_context or {}),
        )

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

    def person_context_structured(
        self,
        person_id: str,
        *,
        current_text: str | None = None,
    ) -> PersonContextResult:
        """Return structured prompt context for a person."""
        profile = self.person_profile(person_id)
        rendered = self.person_context(person_id, current_text=current_text)
        memory_lines, followup_lines, preferred_language = _parse_context(rendered)
        return PersonContextResult(
            person_id=str(person_id or "").strip(),
            directory_profile_lines=profile.directory_profile_lines if profile else (),
            memory_profile_lines=memory_lines,
            potential_followups=followup_lines,
            preferred_language=preferred_language,
        )

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

        try:
            bounded_limit = max(1, int(limit))
        except (TypeError, ValueError):
            bounded_limit = 5
        embeddings = self._embeddings()
        query_embedding = embeddings.embed(rendered_text)
        episode_results = EpisodeRetrievalService(self.runner, embeddings).hybrid_search_with_embedding(
            SearchQuery(
                text=rendered_text,
                person_id=rendered_person_id,
                building_code=str(building_code or "").strip() or None,
                limit=bounded_limit,
            ),
            query_embedding,
        )
        memory_item_results = MemoryItemService(self.runner, embeddings).vector_search_by_embedding(
            person_id=rendered_person_id,
            embedding=query_embedding,
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

    def _biometrics(self) -> BiometricReferenceService:
        """Build a biometric reference service using configured embedding models."""
        return BiometricReferenceService(
            self.runner,
            face_embedding_model=self.settings.face_embedding_model,
            voice_embedding_model=self.settings.voice_embedding_model,
        )


def _parse_context(value: object) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    profile: list[str] = []
    followups: list[str] = []
    preferred_language = "English"
    section = ""
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        if line.endswith(":") and not line.startswith("-"):
            section = line[:-1].strip().casefold()
            continue
        text = line[1:].strip() if line.startswith("-") else line
        text = " ".join(text.split()).lstrip("#-*[]>` ").strip()
        if not text:
            continue
        lowered = text.casefold()
        if lowered.startswith("preferred language"):
            _, _, language = text.partition(":")
            if language.strip():
                preferred_language = language.strip(" .")
        if section in {"potential follow-ups", "potential followups", "followups"}:
            followups.append(text)
        else:
            profile.append(text)
    return tuple(_dedupe(profile)), tuple(_dedupe(followups)), preferred_language


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result

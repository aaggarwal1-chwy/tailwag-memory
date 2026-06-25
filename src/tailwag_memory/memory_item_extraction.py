from __future__ import annotations

from typing import Any

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .episode_normalization import normalize_robot_speaker_labels
from .memory_item_helpers import _PRESERVE, _operation_metadata, normalize_memory_source
from .memory_item_protocols import MemoryExtractionProvider
from .memory_item_service import MemoryItemService
from .models import (
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    MemoryItemInput,
    MemoryItemResult,
    PersonInput,
    PersonMemoryExtractionResult,
    PlaceInput,
    utc_now_iso,
)


def _extract_memory_for_participant(
    *,
    runner: QueryRunner,
    embeddings: EmbeddingProvider,
    extraction_provider: MemoryExtractionProvider,
    episode: EpisodeInput,
    participant: PersonInput,
    source_ref: str | None = None,
) -> PersonMemoryExtractionResult:
    """Extract and apply memory operations for one participant."""
    memory_service = MemoryItemService(runner, embeddings)
    candidates = memory_service.candidate_items(
        person_id=participant.id,
        transcript=episode.transcript,
    )
    payload = extraction_provider.extract(
        person_id=participant.id,
        target_display_name=participant.display_name,
        transcript=episode.transcript,
        existing_memories=candidates,
        current_time=utc_now_iso(),
    )
    applied = _apply_memory_operations(
        memory_service,
        person_id=participant.id,
        operations=payload,
        source=participant.source,
        source_ref=source_ref or episode.id,
        observed_at=episode.end_time or episode.start_time,
        episode_id=episode.id,
        candidates=candidates,
    )
    return PersonMemoryExtractionResult(
        person_id=participant.id,
        update_requested=bool(isinstance(payload, dict) and payload.get("update")),
        created_memory_ids=applied["created"],
        updated_memory_ids=applied["updated"],
        archived_memory_ids=applied["archived"],
        skipped_ops=applied["skipped"],
    )


def _apply_memory_operations(
    memory_service: MemoryItemService,
    *,
    person_id: str,
    operations: dict[str, Any],
    source: str,
    source_ref: str,
    observed_at: str,
    episode_id: str,
    candidates: list[MemoryItemResult],
) -> dict[str, list[Any]]:
    """Apply extraction provider operations to memory items."""
    applied: dict[str, list[Any]] = {"created": [], "updated": [], "archived": [], "skipped": []}
    if not isinstance(operations, dict) or not operations.get("update"):
        return applied
    candidate_by_id = {item.memory_id: item for item in candidates}
    for raw in operations.get("ops", []) or []:
        if not isinstance(raw, dict):
            applied["skipped"].append({"reason": "invalid_op", "op": raw})
            continue
        op = str(raw.get("op") or "").strip().casefold()
        if op == "noop":
            continue
        if op == "create":
            try:
                metadata = _operation_metadata(raw, default={})
                memory_id = memory_service.upsert_item(
                    person_id=person_id,
                    item=MemoryItemInput(
                        kind=str(raw.get("kind") or ""),
                        key=str(raw.get("key") or ""),
                        summary=str(raw.get("summary") or ""),
                        source=normalize_memory_source(source),
                        source_ref=source_ref,
                        observed_at=str(raw.get("observed_at") or observed_at),
                        due_at=str(raw.get("due_at") or ""),
                        expires_at=str(raw.get("expires_at") or ""),
                        metadata=metadata,
                    ),
                    supported_by_episode_id=episode_id,
                )
                applied["created"].append(memory_id)
            except ValueError as exc:
                applied["skipped"].append({"reason": str(exc), "op": raw})
                continue
            continue
        memory_id = str(raw.get("memory_id") or "").strip()
        if not memory_id or memory_id not in candidate_by_id:
            applied["skipped"].append({"reason": "unknown_memory_id", "op": raw})
            continue
        if op == "archive":
            if memory_service.archive_item(memory_id):
                applied["archived"].append(memory_id)
            else:
                applied["skipped"].append({"reason": "archive_noop", "op": raw})
        elif op == "update":
            raw_due_at = str(raw.get("due_at") or "").strip()
            raw_expires_at = str(raw.get("expires_at") or "").strip()
            due_at = raw_due_at if raw_due_at else _PRESERVE
            expires_at = raw_expires_at if raw_expires_at else _PRESERVE
            try:
                metadata = _operation_metadata(raw, default=_PRESERVE)
                updated = memory_service.update_item(
                    memory_id,
                    summary=str(raw.get("summary") or ""),
                    source_ref=source_ref,
                    observed_at=str(raw.get("observed_at") or observed_at),
                    due_at=due_at,
                    expires_at=expires_at,
                    metadata=metadata,
                    supported_by_episode_id=episode_id,
                )
                if updated:
                    applied["updated"].append(memory_id)
                else:
                    applied["skipped"].append({"reason": "update_noop", "op": raw})
            except ValueError as exc:
                applied["skipped"].append({"reason": str(exc), "op": raw})
                continue
        else:
            applied["skipped"].append({"reason": "unknown_operation", "op": raw})
    return applied


class EpisodeMemoryExtractionService:
    """Coordinate memory extraction for episodes."""

    def __init__(
        self,
        runner: QueryRunner,
        embeddings: EmbeddingProvider,
        extraction_provider: MemoryExtractionProvider,
    ) -> None:
        """Store dependencies for episode memory extraction."""
        self.runner = runner
        self.embeddings = embeddings
        self.extraction_provider = extraction_provider

    def extract_for_episode(
        self,
        episode: EpisodeInput,
        *,
        person_id: str | None = None,
        speaker_only: bool = False,
    ) -> EpisodeMemoryExtractionResult:
        """Extract memory for selected participants in an episode."""
        episode = normalize_robot_speaker_labels(episode)
        participants = self._target_participants(episode, person_id=person_id, speaker_only=speaker_only)
        results: list[PersonMemoryExtractionResult] = []
        errors: list[dict[str, str]] = []
        for participant in participants:
            try:
                result = _extract_memory_for_participant(
                    runner=self.runner,
                    embeddings=self.embeddings,
                    extraction_provider=self.extraction_provider,
                    episode=episode,
                    participant=participant,
                )
            except Exception as exc:
                error = str(exc) or type(exc).__name__
                result = PersonMemoryExtractionResult(person_id=participant.id, error=error)
                errors.append({"person_id": participant.id, "error": error})
            results.append(result)
        return EpisodeMemoryExtractionResult(
            episode_id=episode.id,
            memory_results=results,
            memory_errors=errors,
        )

    def extract_for_stored_episode(
        self,
        episode_id: str,
        *,
        person_id: str | None = None,
        speaker_only: bool = True,
    ) -> EpisodeMemoryExtractionResult:
        """Load an episode by id and extract participant memories."""
        episode = self.load_episode(episode_id)
        return self.extract_for_episode(episode, person_id=person_id, speaker_only=speaker_only if person_id is None else False)

    def load_episode(self, episode_id: str) -> EpisodeInput:
        """Load an episode input model from stored graph data."""
        rendered = str(episode_id or "").strip()
        if not rendered:
            raise ValueError("episode_id is required")
        rows = self.runner.run(
            """
            MATCH (e:Episode {id: $episode_id})
            OPTIONAL MATCH (e)-[:OCCURRED_AT]->(place:Place)
            RETURN e.id AS id,
                   e.episode_type AS episode_type,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   e.transcript AS transcript,
                   e.retention_class AS retention_class,
                   place.building_code AS building_code,
                   place.room_id AS room_id
            """,
            {"episode_id": rendered},
        )
        if not rows:
            raise ValueError(f"episode not found: {rendered}")
        row = rows[0]
        participants = self._load_participants(rendered)
        return EpisodeInput(
            id=str(row.get("id") or rendered),
            episode_type=str(row.get("episode_type") or "conversation"),
            start_time=str(row.get("start_time") or ""),
            end_time=str(row.get("end_time") or "") or None,
            transcript=str(row.get("transcript") or ""),
            retention_class=str(row.get("retention_class") or "standard"),
            place=PlaceInput(
                building_code=str(row.get("building_code") or "UNKNOWN"),
                room_id=str(row.get("room_id") or "UNKNOWN"),
            ),
            participants=participants,
        )

    def _load_participants(self, episode_id: str) -> list[PersonInput]:
        """Load participants linked to an episode."""
        rows = self.runner.run(
            """
            MATCH (p:Person)-[r:PARTICIPATED_IN]->(:Episode {id: $episode_id})
            RETURN p.id AS id,
                   p.display_name AS display_name,
                   p.email AS email,
                   p.consent_status AS consent_status,
                   r.role AS role,
                   r.source AS source
            ORDER BY p.id
            """,
            {"episode_id": episode_id},
        )
        return [
            PersonInput(
                id=str(row.get("id") or ""),
                display_name=row.get("display_name"),
                email=row.get("email"),
                consent_status=row.get("consent_status"),
                role=str(row.get("role") or "participant"),
                source=str(row.get("source") or "caller"),
            )
            for row in rows
            if str(row.get("id") or "").strip()
        ]

    def _target_participants(
        self,
        episode: EpisodeInput,
        *,
        person_id: str | None,
        speaker_only: bool,
    ) -> list[PersonInput]:
        """Select participants eligible for memory extraction."""
        if person_id is not None:
            rendered = str(person_id or "").strip()
            matches = [participant for participant in episode.participants if participant.id == rendered]
            if not matches:
                raise ValueError(f"person {rendered!r} is not linked to episode {episode.id!r}")
            return matches
        if not speaker_only:
            return list(episode.participants)
        speakers = [participant for participant in episode.participants if participant.role == "speaker"]
        return speakers or list(episode.participants)

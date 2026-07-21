from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..db import QueryRunner
from ..models import (
    BiometricEnrollmentResult,
    BiometricSearchResult,
    BiometricUpdateResult,
)
from .reference_lifecycle import enroll_reference, observe_embedding
from .reference_search import search_references


DEFAULT_FACE_THRESHOLD = 0.60
DEFAULT_VOICE_THRESHOLD = 0.50
DEFAULT_MARGIN_THRESHOLD = 0.20
DEFAULT_FACE_UPDATE_THRESHOLD = 0.72
DEFAULT_VOICE_UPDATE_THRESHOLD = 0.55
DEFAULT_UPDATE_EVIDENCE_MARGIN = 0.20
DEFAULT_TARGET_SAMPLE_COUNT = 5
DEFAULT_FACE_MODEL = "facenet"
DEFAULT_VOICE_MODEL = "speechbrain_ecapa"


class BiometricReferenceService:
    """Store and search consented face and voice references."""

    def __init__(
        self,
        runner: QueryRunner,
        *,
        face_embedding_model: str = DEFAULT_FACE_MODEL,
        voice_embedding_model: str = DEFAULT_VOICE_MODEL,
    ) -> None:
        self.runner = runner
        self.face_embedding_model = (
            str(face_embedding_model or "").strip() or DEFAULT_FACE_MODEL
        )
        self.voice_embedding_model = (
            str(voice_embedding_model or "").strip() or DEFAULT_VOICE_MODEL
        )

    def enroll_face_reference(
        self,
        *,
        person_id: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
        consent_status: str = "consented",
    ) -> BiometricEnrollmentResult:
        return enroll_reference(
            self.runner,
            modality="face",
            person_id=person_id,
            embedding=embedding,
            metadata=metadata,
            consent_status=consent_status,
            model=self.face_embedding_model,
            target_sample_count=DEFAULT_TARGET_SAMPLE_COUNT,
        )

    def enroll_voice_reference(
        self,
        *,
        person_id: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
        consent_status: str = "consented",
    ) -> BiometricEnrollmentResult:
        return enroll_reference(
            self.runner,
            modality="voice",
            person_id=person_id,
            embedding=embedding,
            metadata=metadata,
            consent_status=consent_status,
            model=self.voice_embedding_model,
            target_sample_count=DEFAULT_TARGET_SAMPLE_COUNT,
        )

    def search_face(
        self,
        *,
        embedding: list[float],
        limit: int = 2,
        site_code: str | None = None,
    ) -> BiometricSearchResult:
        return search_references(
            self.runner,
            modality="face",
            embedding=embedding,
            limit=limit,
            site_code=site_code,
            threshold=DEFAULT_FACE_THRESHOLD,
            margin_threshold=DEFAULT_MARGIN_THRESHOLD,
        )

    def search_voice(
        self,
        *,
        embedding: list[float],
        limit: int = 2,
        site_code: str | None = None,
    ) -> BiometricSearchResult:
        return search_references(
            self.runner,
            modality="voice",
            embedding=embedding,
            limit=limit,
            site_code=site_code,
            threshold=DEFAULT_VOICE_THRESHOLD,
            margin_threshold=DEFAULT_MARGIN_THRESHOLD,
        )

    def has_voice_reference(self, person_id: str) -> bool:
        rendered = str(person_id or "").strip()
        if not rendered:
            return False
        rows = self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[:HAS_VOICE_REFERENCE]->(r:VoiceReference)
            WHERE coalesce(r.status, 'active') = 'active'
            RETURN r.id AS reference_id
            LIMIT 1
            """,
            {"person_id": rendered},
        )
        return bool(rows)

    def observe_face_embedding(
        self,
        *,
        person_id: str,
        embedding: list[float],
        evidence: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> BiometricUpdateResult:
        return observe_embedding(
            self.runner,
            modality="face",
            person_id=person_id,
            embedding=embedding,
            evidence=evidence,
            metadata=metadata,
            model=self.face_embedding_model,
            update_threshold=DEFAULT_FACE_UPDATE_THRESHOLD,
            evidence_margin=DEFAULT_UPDATE_EVIDENCE_MARGIN,
            target_sample_count_default=DEFAULT_TARGET_SAMPLE_COUNT,
        )

    def observe_voice_embedding(
        self,
        *,
        person_id: str,
        embedding: list[float],
        evidence: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> BiometricUpdateResult:
        return observe_embedding(
            self.runner,
            modality="voice",
            person_id=person_id,
            embedding=embedding,
            evidence=evidence,
            metadata=metadata,
            model=self.voice_embedding_model,
            update_threshold=DEFAULT_VOICE_UPDATE_THRESHOLD,
            evidence_margin=DEFAULT_UPDATE_EVIDENCE_MARGIN,
            target_sample_count_default=DEFAULT_TARGET_SAMPLE_COUNT,
        )


def result_to_dict(result: BiometricSearchResult) -> dict[str, Any]:
    """Return a plain dict for adapters that need JSON-like results."""
    return asdict(result)

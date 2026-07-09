from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any
from uuid import uuid4

from ..db import QueryRunner
from ..models import (
    BiometricCandidate,
    BiometricEnrollmentResult,
    BiometricSearchResult,
    PersonInput,
    utc_now_iso,
)
from ..ingestion import PersonIngestionService
from ..vector_queries import vector_search_clause


DEFAULT_FACE_THRESHOLD = 0.60
DEFAULT_VOICE_THRESHOLD = 0.40
DEFAULT_MARGIN_THRESHOLD = 0.20


class BiometricReferenceService:
    """Store and search consented face and voice references."""

    def __init__(self, runner: QueryRunner) -> None:
        self.runner = runner

    def enroll_face_reference(
        self,
        *,
        person_id: str,
        embedding: list[float],
        model: str,
        metadata: dict[str, Any] | None = None,
        consent_status: str = "consented",
    ) -> BiometricEnrollmentResult:
        return self._enroll_reference(
            modality="face",
            person_id=person_id,
            embedding=embedding,
            model=model,
            metadata=metadata,
            consent_status=consent_status,
        )

    def enroll_voice_reference(
        self,
        *,
        person_id: str,
        embedding: list[float],
        model: str,
        metadata: dict[str, Any] | None = None,
        consent_status: str = "consented",
    ) -> BiometricEnrollmentResult:
        return self._enroll_reference(
            modality="voice",
            person_id=person_id,
            embedding=embedding,
            model=model,
            metadata=metadata,
            consent_status=consent_status,
        )

    def search_face(
        self,
        *,
        embedding: list[float],
        model: str,
        limit: int = 2,
        site_code: str | None = None,
    ) -> BiometricSearchResult:
        return self._search(
            modality="face",
            embedding=embedding,
            model=model,
            limit=limit,
            site_code=site_code,
        )

    def search_voice(
        self,
        *,
        embedding: list[float],
        model: str,
        limit: int = 2,
        site_code: str | None = None,
    ) -> BiometricSearchResult:
        return self._search(
            modality="voice",
            embedding=embedding,
            model=model,
            limit=limit,
            site_code=site_code,
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

    def _enroll_reference(
        self,
        *,
        modality: str,
        person_id: str,
        embedding: list[float],
        model: str,
        metadata: dict[str, Any] | None,
        consent_status: str,
    ) -> BiometricEnrollmentResult:
        rendered_person_id = str(person_id or "").strip()
        if not rendered_person_id:
            raise ValueError("person_id is required")
        vector = [float(value) for value in embedding]
        if not vector:
            raise ValueError("embedding is required")
        rendered_consent = str(consent_status or "").strip() or "consented"
        if rendered_consent != "consented":
            return BiometricEnrollmentResult(
                saved=False,
                status="rejected",
                reason="consent_required",
                person_id=rendered_person_id,
            )
        meta = dict(metadata or {})
        PersonIngestionService(self.runner).upsert(
            PersonInput(
                id=rendered_person_id,
                display_name=(
                    _metadata_value(meta, "display_name")
                    or _metadata_value(meta, "name")
                    or _metadata_value(meta, "official_name")
                    or rendered_person_id
                ),
                official_name=_metadata_value(meta, "official_name") or None,
                email=(
                    _metadata_value(meta, "employee_email")
                    or _metadata_value(meta, "email")
                    or None
                ),
                consent_status=rendered_consent,
            )
        )
        now = utc_now_iso()
        directory_username = _metadata_value(meta, "username").lower()
        directory_site_code = _metadata_value(meta, "site_code")
        person_label = (
            _metadata_value(meta, "official_name")
            or _metadata_value(meta, "display_name")
            or _metadata_value(meta, "name")
            or rendered_person_id
        )
        reference_id = f"{modality}:{rendered_person_id}:{uuid4().hex}"
        label = "FaceReference" if modality == "face" else "VoiceReference"
        reference_display_name = f"{'Face' if modality == 'face' else 'Voice'} reference for {person_label}"
        rel = "HAS_FACE_REFERENCE" if modality == "face" else "HAS_VOICE_REFERENCE"
        self.runner.run(
            f"""
            MATCH (p:Person {{id: $person_id}})
            OPTIONAL MATCH (d:EmployeeDirectoryRecord {{site_code: $directory_site_code, username: $directory_username}})
            FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
              SET p.official_name = CASE WHEN d.official_name <> '' THEN d.official_name ELSE p.official_name END,
                  p.display_name = CASE WHEN d.official_name <> '' THEN d.official_name ELSE p.display_name END,
                  p.name = p.id,
                  p.email = CASE WHEN d.employee_email <> '' THEN d.employee_email ELSE p.email END
              MERGE (p)-[:HAS_DIRECTORY_RECORD]->(d)
            )
            WITH p
            CREATE (r:{label} {{id: $reference_id}})
            SET r.embedding = $embedding,
                r.display_name = $reference_display_name,
                r.name = $reference_display_name,
                r.model = $model,
                r.dimension = $dimension,
                r.metadata_json = $metadata_json,
                r.consent_status = $consent_status,
                r.status = 'active',
                r.created_at = $now,
                r.updated_at = $now
            MERGE (p)-[:{rel}]->(r)
            RETURN r.id AS reference_id
            """,
            {
                "person_id": rendered_person_id,
                "reference_id": reference_id,
                "reference_display_name": reference_display_name,
                "embedding": vector,
                "model": str(model or "").strip() or "unknown",
                "dimension": len(vector),
                "metadata_json": _metadata_json(meta),
                "consent_status": rendered_consent,
                "now": now,
                "directory_username": directory_username,
                "directory_site_code": directory_site_code,
            },
        )
        return BiometricEnrollmentResult(
            saved=True,
            status="saved",
            reason="saved",
            person_id=rendered_person_id,
            reference_id=reference_id,
        )

    def _search(
        self,
        *,
        modality: str,
        embedding: list[float],
        model: str,
        limit: int,
        site_code: str | None,
    ) -> BiometricSearchResult:
        vector = [float(value) for value in embedding]
        if not vector:
            return BiometricSearchResult(modality=modality, reason="no_embedding")
        bounded_limit = max(1, int(limit or 1))
        threshold = DEFAULT_FACE_THRESHOLD if modality == "face" else DEFAULT_VOICE_THRESHOLD
        index = "face_reference_embedding" if modality == "face" else "voice_reference_embedding"
        rel = "HAS_FACE_REFERENCE" if modality == "face" else "HAS_VOICE_REFERENCE"
        rows = self.runner.run(
            vector_search_clause(index, "ref", "candidate_limit")
            + f"""
            MATCH (person:Person)-[:{rel}]->(ref)
            OPTIONAL MATCH (person)-[:HAS_DIRECTORY_RECORD]->(directory:EmployeeDirectoryRecord)
            WHERE coalesce(ref.status, 'active') = 'active'
              AND coalesce(person.status, 'active') <> 'archived'
              AND coalesce(ref.consent_status, person.consent_status, '') = 'consented'
              AND ($site_code IS NULL OR directory IS NULL OR directory.site_code = $site_code)
            RETURN person.id AS person_id,
                   person.display_name AS display_name,
                   person.consent_status AS consent_status,
                   ref.id AS reference_id,
                   ref.model AS model,
                   ref.metadata_json AS metadata_json,
                   score AS score
            ORDER BY score DESC
            LIMIT $limit
            """,
            {
                "candidate_limit": max(bounded_limit * 5, 25),
                "limit": bounded_limit,
                "embedding": vector,
                "site_code": str(site_code or "").strip() or None,
                "model": str(model or "").strip(),
            },
        )
        candidates = [_candidate_from_row(row) for row in rows]
        top_score = candidates[0].score if candidates else 0.0
        runner_up_score = candidates[1].score if len(candidates) > 1 else 0.0
        margin = max(0.0, top_score - runner_up_score)
        if not candidates:
            status = "rejected"
            reason = "no_match"
        elif top_score < threshold:
            status = "rejected"
            reason = "below_threshold"
        elif margin < DEFAULT_MARGIN_THRESHOLD:
            status = "rejected"
            reason = "margin_too_small"
        else:
            status = "accepted"
            reason = "matched"
        return BiometricSearchResult(
            modality=modality,
            candidates=candidates,
            recognized=status == "accepted",
            status=status,
            reason=reason,
            threshold=threshold,
            margin_threshold=DEFAULT_MARGIN_THRESHOLD,
            top_score=top_score,
            runner_up_score=runner_up_score,
            margin=margin,
        )


def _candidate_from_row(row: dict[str, Any]) -> BiometricCandidate:
    metadata = _metadata_from_json(row.get("metadata_json"))
    return BiometricCandidate(
        person_id=str(row.get("person_id") or ""),
        display_name=str(row.get("display_name") or ""),
        score=float(row.get("score") or 0.0),
        consent_status=str(row.get("consent_status") or ""),
        reference_id=str(row.get("reference_id") or ""),
        model=str(row.get("model") or ""),
        metadata=dict(metadata),
    )


def result_to_dict(result: BiometricSearchResult) -> dict[str, Any]:
    """Return a plain dict for adapters that need JSON-like results."""
    return asdict(result)


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None and isinstance(metadata.get("metadata"), dict):
        value = metadata["metadata"].get(key)
    return str(value or "").strip()


def _metadata_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, sort_keys=True, default=str)


def _metadata_from_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(str(value))
    except Exception:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}

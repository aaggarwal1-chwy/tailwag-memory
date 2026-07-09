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
    BiometricUpdateResult,
    PersonInput,
    utc_now_iso,
)
from ..ingestion import PersonIngestionService
from ..vector_queries import vector_search_clause


DEFAULT_FACE_THRESHOLD = 0.60
DEFAULT_VOICE_THRESHOLD = 0.40
DEFAULT_MARGIN_THRESHOLD = 0.20
DEFAULT_FACE_UPDATE_THRESHOLD = 0.72
DEFAULT_VOICE_UPDATE_THRESHOLD = 0.55
DEFAULT_UPDATE_EVIDENCE_MARGIN = 0.20
DEFAULT_TARGET_SAMPLE_COUNT = 5


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

    def observe_face_embedding(
        self,
        *,
        person_id: str,
        embedding: list[float],
        model: str,
        evidence: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> BiometricUpdateResult:
        return self._observe_embedding(
            modality="face",
            person_id=person_id,
            embedding=embedding,
            model=model,
            evidence=evidence,
            metadata=metadata,
        )

    def observe_voice_embedding(
        self,
        *,
        person_id: str,
        embedding: list[float],
        model: str,
        evidence: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> BiometricUpdateResult:
        return self._observe_embedding(
            modality="voice",
            person_id=person_id,
            embedding=embedding,
            model=model,
            evidence=evidence,
            metadata=metadata,
        )

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
                r.sample_count = 1,
                r.accepted_update_count = 0,
                r.target_sample_count = $target_sample_count,
                r.aggregate_method = 'normalized_running_average',
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
                "target_sample_count": DEFAULT_TARGET_SAMPLE_COUNT,
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

    def _observe_embedding(
        self,
        *,
        modality: str,
        person_id: str,
        embedding: list[float],
        model: str,
        evidence: dict[str, Any],
        metadata: dict[str, Any] | None,
    ) -> BiometricUpdateResult:
        rendered_person_id = str(person_id or "").strip()
        if not rendered_person_id:
            raise ValueError("person_id is required")
        vector = _normalize_vector(embedding)
        if not vector:
            raise ValueError("embedding is required")
        evidence_payload = dict(evidence or {})
        if not _evidence_allows_update(modality, rendered_person_id, evidence_payload):
            return BiometricUpdateResult(
                accepted=False,
                status="rejected",
                reason="weak_evidence",
                person_id=rendered_person_id,
                modality=modality,
            )
        label = "FaceReference" if modality == "face" else "VoiceReference"
        rel = "HAS_FACE_REFERENCE" if modality == "face" else "HAS_VOICE_REFERENCE"
        rows = self.runner.run(
            f"""
            MATCH (p:Person {{id: $person_id}})-[:{rel}]->(r:{label})
            WHERE coalesce(p.status, 'active') <> 'archived'
              AND coalesce(r.status, 'active') = 'active'
              AND coalesce(r.consent_status, p.consent_status, '') = 'consented'
            RETURN r.id AS reference_id,
                   r.embedding AS embedding,
                   r.model AS model,
                   coalesce(r.sample_count, 1) AS sample_count,
                   coalesce(r.accepted_update_count, 0) AS accepted_update_count,
                   coalesce(r.target_sample_count, $default_target_sample_count) AS target_sample_count,
                   r.metadata_json AS metadata_json
            ORDER BY coalesce(r.sample_count, 1) DESC, r.updated_at DESC
            LIMIT 1
            """,
            {
                "person_id": rendered_person_id,
                "default_target_sample_count": DEFAULT_TARGET_SAMPLE_COUNT,
            },
        )
        if not rows:
            return BiometricUpdateResult(
                accepted=False,
                status="rejected",
                reason="missing_reference",
                person_id=rendered_person_id,
                modality=modality,
            )
        row = rows[0]
        reference_id = str(row.get("reference_id") or "")
        current = _normalize_vector(row.get("embedding") or [])
        reference_model = str(row.get("model") or "").strip()
        incoming_model = str(model or "").strip()
        sample_count = _safe_int(row.get("sample_count"), default=1)
        target_sample_count = _safe_int(
            row.get("target_sample_count"),
            default=DEFAULT_TARGET_SAMPLE_COUNT,
        )
        if reference_model and incoming_model and reference_model != incoming_model:
            return BiometricUpdateResult(
                accepted=False,
                status="rejected",
                reason="model_mismatch",
                person_id=rendered_person_id,
                reference_id=reference_id,
                modality=modality,
                sample_count=sample_count,
                target_sample_count=target_sample_count,
            )
        if not current or len(current) != len(vector):
            return BiometricUpdateResult(
                accepted=False,
                status="rejected",
                reason="dimension_mismatch",
                person_id=rendered_person_id,
                reference_id=reference_id,
                modality=modality,
                sample_count=sample_count,
                target_sample_count=target_sample_count,
            )
        if sample_count >= target_sample_count:
            return BiometricUpdateResult(
                accepted=False,
                status="complete",
                reason="sample_target_reached",
                person_id=rendered_person_id,
                reference_id=reference_id,
                modality=modality,
                sample_count=sample_count,
                target_sample_count=target_sample_count,
            )
        similarity = _cosine_similarity(current, vector)
        threshold = (
            DEFAULT_FACE_UPDATE_THRESHOLD
            if modality == "face"
            else DEFAULT_VOICE_UPDATE_THRESHOLD
        )
        if similarity < threshold:
            return BiometricUpdateResult(
                accepted=False,
                status="rejected",
                reason="below_similarity_threshold",
                person_id=rendered_person_id,
                reference_id=reference_id,
                modality=modality,
                sample_count=sample_count,
                target_sample_count=target_sample_count,
                similarity=similarity,
            )
        new_sample_count = sample_count + 1
        accepted_update_count = _safe_int(row.get("accepted_update_count")) + 1
        aggregate = _normalize_vector(
            [
                ((current_value * sample_count) + observed_value)
                / float(new_sample_count)
                for current_value, observed_value in zip(current, vector)
            ]
        )
        now = utc_now_iso()
        stored_metadata = _metadata_from_json(row.get("metadata_json"))
        stored_metadata["adaptive_last_update"] = {
            "observed_at": now,
            "similarity": similarity,
            "evidence": evidence_payload,
            "metadata": dict(metadata or {}),
            "model": str(model or "").strip() or "unknown",
        }
        self.runner.run(
            f"""
            MATCH (:Person {{id: $person_id}})-[:{rel}]->(r:{label} {{id: $reference_id}})
            SET r.embedding = $embedding,
                r.sample_count = $sample_count,
                r.accepted_update_count = $accepted_update_count,
                r.target_sample_count = $target_sample_count,
                r.aggregate_method = 'normalized_running_average',
                r.metadata_json = $metadata_json,
                r.updated_at = $updated_at
            RETURN r.id AS reference_id
            """,
            {
                "person_id": rendered_person_id,
                "reference_id": reference_id,
                "embedding": aggregate,
                "sample_count": new_sample_count,
                "accepted_update_count": accepted_update_count,
                "target_sample_count": target_sample_count,
                "metadata_json": _metadata_json(stored_metadata),
                "updated_at": now,
            },
        )
        return BiometricUpdateResult(
            accepted=True,
            status="updated",
            reason="updated",
            person_id=rendered_person_id,
            reference_id=reference_id,
            modality=modality,
            sample_count=new_sample_count,
            target_sample_count=target_sample_count,
            similarity=similarity,
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


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _normalize_vector(values: Any) -> list[float]:
    vector = [float(value) for value in (values or ())]
    norm = sum(value * value for value in vector) ** 0.5
    if norm <= 0.0:
        return []
    return [value / norm for value in vector]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _evidence_allows_update(modality: str, person_id: str, evidence: dict[str, Any]) -> bool:
    owner_id = str(evidence.get("owner_id") or "").strip()
    owner_source = str(evidence.get("owner_source") or "").strip()
    primary_face_person_id = str(evidence.get("primary_face_person_id") or "").strip()
    audio_speaker_id = str(evidence.get("audio_speaker_id") or "").strip()
    face_margin = _safe_float(
        evidence.get("face_margin") or evidence.get("face_score_margin")
    )
    voice_margin = _safe_float(
        evidence.get("voice_margin") or evidence.get("audio_score_margin")
    )
    unknown_count = _safe_int(evidence.get("unknown_count"))
    recognized_count = _safe_int(evidence.get("recognized_count"))
    if owner_id != person_id or unknown_count != 0:
        return False
    if modality == "face":
        return (
            owner_source == "audio_face_agree"
            and primary_face_person_id == person_id
            and audio_speaker_id == person_id
            and face_margin >= DEFAULT_UPDATE_EVIDENCE_MARGIN
            and voice_margin >= DEFAULT_UPDATE_EVIDENCE_MARGIN
        )
    if owner_source == "audio_face_agree":
        return (
            primary_face_person_id == person_id
            and audio_speaker_id == person_id
            and face_margin >= DEFAULT_UPDATE_EVIDENCE_MARGIN
            and voice_margin >= DEFAULT_UPDATE_EVIDENCE_MARGIN
        )
    return (
        owner_source == "face"
        and primary_face_person_id == person_id
        and recognized_count == 1
        and face_margin >= DEFAULT_UPDATE_EVIDENCE_MARGIN
    )

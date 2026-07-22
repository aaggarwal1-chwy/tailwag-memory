"""Enrollment and adaptive-update workflows for biometric references."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..db import QueryRunner
from ..ingestion import PersonIngestionService
from ..models import (
    BiometricEnrollmentResult,
    BiometricUpdateResult,
    PersonInput,
    utc_now_iso,
)
from .metadata import metadata_from_json, metadata_json, metadata_value


def enroll_reference(
    runner: QueryRunner,
    *,
    modality: str,
    person_id: str,
    embedding: list[float],
    metadata: dict[str, Any] | None,
    consent_status: str,
    model: str,
    target_sample_count: int,
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
    PersonIngestionService(runner).upsert(
        PersonInput(
            id=rendered_person_id,
            display_name=(
                metadata_value(meta, "display_name")
                or metadata_value(meta, "name")
                or metadata_value(meta, "official_name")
                or None
            ),
            official_name=metadata_value(meta, "official_name") or None,
            email=(
                metadata_value(meta, "employee_email")
                or metadata_value(meta, "email")
                or None
            ),
            consent_status=rendered_consent,
        )
    )
    now = utc_now_iso()
    directory_username = metadata_value(meta, "username").lower()
    directory_site_code = metadata_value(meta, "site_code")
    person_label = (
        metadata_value(meta, "official_name")
        or metadata_value(meta, "display_name")
        or metadata_value(meta, "name")
        or rendered_person_id
    )
    reference_id = f"{modality}:{rendered_person_id}:{uuid4().hex}"
    label = "FaceReference" if modality == "face" else "VoiceReference"
    reference_display_name = (
        f"{'Face' if modality == 'face' else 'Voice'} reference for {person_label}"
    )
    rel = "HAS_FACE_REFERENCE" if modality == "face" else "HAS_VOICE_REFERENCE"
    runner.run(
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
            "metadata_json": metadata_json(meta),
            "consent_status": rendered_consent,
            "target_sample_count": target_sample_count,
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


def observe_embedding(
    runner: QueryRunner,
    *,
    modality: str,
    person_id: str,
    embedding: list[float],
    evidence: dict[str, Any],
    metadata: dict[str, Any] | None,
    model: str,
    update_threshold: float,
    evidence_margin: float,
    target_sample_count_default: int,
) -> BiometricUpdateResult:
    rendered_person_id = str(person_id or "").strip()
    if not rendered_person_id:
        raise ValueError("person_id is required")
    vector = _normalize_vector(embedding)
    if not vector:
        raise ValueError("embedding is required")
    evidence_payload = dict(evidence or {})
    if not _evidence_allows_update(
        modality,
        rendered_person_id,
        evidence_payload,
        evidence_margin=evidence_margin,
    ):
        return BiometricUpdateResult(
            accepted=False,
            status="rejected",
            reason="weak_evidence",
            person_id=rendered_person_id,
            modality=modality,
        )

    label = "FaceReference" if modality == "face" else "VoiceReference"
    rel = "HAS_FACE_REFERENCE" if modality == "face" else "HAS_VOICE_REFERENCE"
    rows = runner.run(
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
            "default_target_sample_count": target_sample_count_default,
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
        default=target_sample_count_default,
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
    if similarity < update_threshold:
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
    stored_metadata = metadata_from_json(row.get("metadata_json"))
    stored_metadata["adaptive_last_update"] = {
        "observed_at": now,
        "similarity": similarity,
        "evidence": evidence_payload,
        "metadata": dict(metadata or {}),
        "model": str(model or "").strip() or "unknown",
    }
    runner.run(
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
            "metadata_json": metadata_json(stored_metadata),
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


def _evidence_allows_update(
    modality: str,
    person_id: str,
    evidence: dict[str, Any],
    *,
    evidence_margin: float,
) -> bool:
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
    if owner_id != person_id or unknown_count != 0:
        return False
    if modality == "face":
        return (
            owner_source == "audio_face_agree"
            and primary_face_person_id == person_id
            and audio_speaker_id == person_id
            and face_margin >= evidence_margin
            and voice_margin >= evidence_margin
        )
    if owner_source == "audio_face_agree":
        return (
            primary_face_person_id == person_id
            and audio_speaker_id == person_id
            and face_margin >= evidence_margin
            and voice_margin >= evidence_margin
        )
    return False

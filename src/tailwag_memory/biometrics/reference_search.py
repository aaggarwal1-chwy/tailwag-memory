"""Lookup and ranking workflows for biometric references."""

from __future__ import annotations

from typing import Any

from ..db import QueryRunner
from ..models import BiometricCandidate, BiometricSearchResult
from ..vector_queries import vector_search_clause
from .metadata import metadata_from_json


def search_references(
    runner: QueryRunner,
    *,
    modality: str,
    embedding: list[float],
    limit: int,
    site_code: str | None,
    threshold: float,
    margin_threshold: float,
) -> BiometricSearchResult:
    vector = [float(value) for value in embedding]
    if not vector:
        return BiometricSearchResult(modality=modality, reason="no_embedding")
    bounded_limit = max(1, int(limit or 1))
    index = (
        "face_reference_embedding"
        if modality == "face"
        else "voice_reference_embedding"
    )
    rel = "HAS_FACE_REFERENCE" if modality == "face" else "HAS_VOICE_REFERENCE"
    rows = runner.run(
        vector_search_clause(index, "ref", "candidate_limit")
        + f"""
        MATCH (person:Person)-[:{rel}]->(ref)
        WHERE coalesce(ref.status, 'active') = 'active'
          AND coalesce(person.status, 'active') <> 'archived'
          AND coalesce(ref.consent_status, person.consent_status, '') = 'consented'
        OPTIONAL MATCH (person)-[:HAS_DIRECTORY_RECORD]->(directory:EmployeeDirectoryRecord)
        WITH person, ref, score, directory
        WHERE $site_code IS NULL OR directory IS NULL OR directory.site_code = $site_code
        RETURN person.id AS person_id,
               person.display_name AS display_name,
               person.consent_status AS consent_status,
               ref.id AS reference_id,
               ref.model AS model,
               ref.metadata_json AS metadata_json,
               score AS neo4j_score
        ORDER BY neo4j_score DESC
        LIMIT $limit
        """,
        {
            "candidate_limit": max(bounded_limit * 5, 25),
            "limit": bounded_limit,
            "embedding": vector,
            "site_code": str(site_code or "").strip() or None,
        },
    )
    candidates = [_candidate_from_vector_row(row) for row in rows]
    top_score = candidates[0].score if candidates else 0.0
    runner_up_score = candidates[1].score if len(candidates) > 1 else 0.0
    margin = max(0.0, top_score - runner_up_score)
    if not candidates:
        status = "rejected"
        reason = "no_match"
    elif top_score < threshold:
        status = "rejected"
        reason = "below_threshold"
    elif margin < margin_threshold:
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
        margin_threshold=margin_threshold,
        top_score=top_score,
        runner_up_score=runner_up_score,
        margin=margin,
    )


def _candidate_from_row(row: dict[str, Any]) -> BiometricCandidate:
    metadata = metadata_from_json(row.get("metadata_json"))
    return BiometricCandidate(
        person_id=str(row.get("person_id") or ""),
        display_name=str(row.get("display_name") or ""),
        score=float(row.get("score") or 0.0),
        consent_status=str(row.get("consent_status") or ""),
        reference_id=str(row.get("reference_id") or ""),
        model=str(row.get("model") or ""),
        metadata=dict(metadata),
    )


def _candidate_from_vector_row(row: dict[str, Any]) -> BiometricCandidate:
    rendered = dict(row)
    rendered["score"] = _neo4j_cosine_score_to_raw(
        float(rendered.get("neo4j_score", rendered.get("score", 0.0)) or 0.0)
    )
    return _candidate_from_row(rendered)


def _neo4j_cosine_score_to_raw(score: float) -> float:
    """Convert Neo4j cosine vector index scores back to raw cosine similarity."""
    return (float(score) * 2.0) - 1.0

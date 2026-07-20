from __future__ import annotations

from dataclasses import asdict, is_dataclass
import os
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from tailwag_memory.api.auth import require_bearer_token
from tailwag_memory.api.dependencies import get_client
from tailwag_memory.api.schemas import (
    BiometricEnrollmentRequest,
    BiometricObservationRequest,
    BiometricSearchRequest,
    EpisodeRecordRequest,
    IdentityResolveRequest,
    PersonArchiveRequest,
    PersonContextRequest,
    PersonContextResponse,
    PersonProfileRequest,
    PersonRekeyByEmailRequest,
    PersonUpsertRequest,
    SemanticSearchRequest,
    TurnOwnerResolveRequest,
    VerifiedProfileRequest,
    VoiceReferenceExistsRequest,
)
from tailwag_memory.client import TailwagMemoryClient
from tailwag_memory.config import load_env_file
from tailwag_memory.models import EpisodeInput, PersonInput, utc_now_iso

ARGOS_MEMORY_REQUEST_PREFIX = "/argos/providers/memory/resources/memory/request"


def create_app() -> FastAPI:
    """Create the Tailwag FastAPI application."""
    docs_enabled = _api_docs_enabled()
    app = FastAPI(
        title="Tailwag Memory API",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "tailwag-memory"}

    @app.get(
        "/argos/providers/memory/resources/memory/health",
        dependencies=[Depends(require_bearer_token)],
    )
    def provider_health() -> dict[str, object]:
        return {"ok": True, "service": "tailwag-memory", "provider": "memory", "resource": "memory"}

    app.include_router(_memory_router())
    return app


def _api_docs_enabled() -> bool:
    """Return whether interactive API docs should be exposed."""
    load_env_file()
    return str(os.getenv("TAILWAG_API_DOCS_ENABLED") or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _memory_router() -> APIRouter:
    router = APIRouter(
        prefix=ARGOS_MEMORY_REQUEST_PREFIX,
        dependencies=[Depends(require_bearer_token)],
    )

    @router.post("/person_context", response_model=PersonContextResponse)
    def person_context(
        payload: PersonContextRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> PersonContextResponse:
        rendered = client.person_context(
            payload.person_id,
            limit=payload.limit,
            semantic_scope=payload.semantic_scope,
            current_text=payload.current_text,
            now=payload.now,
            memory_limit=payload.memory_limit,
        )
        return PersonContextResponse(
            person_id=payload.person_id,
            context_markdown=rendered,
            generated_at=utc_now_iso(),
        )

    @router.post("/episodes_record")
    def episodes(
        payload: EpisodeRecordRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        result = client.record_episode(
            EpisodeInput.from_dict(payload.episode.as_dict()),
            extract_memory=payload.extract_memory,
            enqueue_memory_extraction=payload.enqueue_memory_extraction,
        )
        return asdict(result)

    @router.post("/semantic_search")
    def semantic_search(
        payload: SemanticSearchRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, list[dict[str, object]]]:
        return client.search_semantic_memory(
            text=payload.text,
            person_id=payload.person_id,
            building_code=payload.building_code,
            limit=payload.limit,
            now=payload.now,
        )

    @router.post("/people_upsert")
    def upsert_person(
        payload: PersonUpsertRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, str]:
        person_id = client.upsert_person(PersonInput(**payload.person.as_kwargs()))
        return {"person_id": person_id}

    @router.post("/people_archive")
    def archive_person(
        payload: PersonArchiveRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, bool]:
        return {"archived": client.archive_person(payload.person_id)}

    @router.post("/people_rekey_by_email")
    def rekey_person_by_email(
        payload: PersonRekeyByEmailRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, bool]:
        return {"rekeyed": client.rekey_person_by_email(payload.email, payload.new_person_id)}

    @router.post("/people_profile")
    def person_profile(
        payload: PersonProfileRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object] | None:
        result = client.person_profile(payload.person_id)
        return _plain(result) if result is not None else None

    @router.post("/identity_resolve")
    def resolve_identity(
        payload: IdentityResolveRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        return _plain(
            client.resolve_identity(
                shared_first_name=payload.shared_first_name,
                shared_last_name=payload.shared_last_name,
                shared_name=payload.shared_name,
                site_code=payload.site_code,
            )
        )

    @router.post("/identity_verified_profile")
    def verified_profile(
        payload: VerifiedProfileRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object] | None:
        result = client.get_verified_profile(
            username=payload.username,
            official_name=payload.official_name,
            site_code=payload.site_code,
        )
        return _plain(result) if result is not None else None

    @router.post("/biometrics_face_search")
    def search_face(
        payload: BiometricSearchRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        _validate_embedding_dimension(
            payload.embedding,
            _settings_int(client, "face_embedding_dimension"),
            "face embedding",
        )
        return _biometric_search_response(
            client.search_face(
                embedding=payload.embedding,
                limit=payload.limit,
                site_code=payload.site_code,
            )
        )

    @router.post("/biometrics_voice_search")
    def search_voice(
        payload: BiometricSearchRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        _validate_embedding_dimension(
            payload.embedding,
            _settings_int(client, "voice_embedding_dimension"),
            "voice embedding",
        )
        return _biometric_search_response(
            client.search_voice(
                embedding=payload.embedding,
                limit=payload.limit,
                site_code=payload.site_code,
            )
        )

    @router.post("/biometrics_face_references")
    def enroll_face_reference(
        payload: BiometricEnrollmentRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        _validate_embedding_dimension(
            payload.embedding,
            _settings_int(client, "face_embedding_dimension"),
            "face embedding",
        )
        return _plain(
            client.enroll_face_reference(
                person_id=payload.person_id,
                embedding=payload.embedding,
                metadata=payload.metadata,
                consent_status=payload.consent_status,
            )
        )

    @router.post("/biometrics_voice_references")
    def enroll_voice_reference(
        payload: BiometricEnrollmentRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        _validate_embedding_dimension(
            payload.embedding,
            _settings_int(client, "voice_embedding_dimension"),
            "voice embedding",
        )
        return _plain(
            client.enroll_voice_reference(
                person_id=payload.person_id,
                embedding=payload.embedding,
                metadata=payload.metadata,
                consent_status=payload.consent_status,
            )
        )

    @router.post("/biometrics_face_observations")
    def observe_face_embedding(
        payload: BiometricObservationRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        _validate_embedding_dimension(
            payload.embedding,
            _settings_int(client, "face_embedding_dimension"),
            "face embedding",
        )
        return _plain(
            client.observe_face_embedding(
                person_id=payload.person_id,
                embedding=payload.embedding,
                evidence=payload.evidence,
                metadata=payload.metadata,
            )
        )

    @router.post("/biometrics_voice_observations")
    def observe_voice_embedding(
        payload: BiometricObservationRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        _validate_embedding_dimension(
            payload.embedding,
            _settings_int(client, "voice_embedding_dimension"),
            "voice embedding",
        )
        return _plain(
            client.observe_voice_embedding(
                person_id=payload.person_id,
                embedding=payload.embedding,
                evidence=payload.evidence,
                metadata=payload.metadata,
            )
        )

    @router.post("/biometrics_voice_references_exists")
    def has_voice_reference(
        payload: VoiceReferenceExistsRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, bool]:
        return {"has_voice_reference": client.has_voice_reference(payload.person_id)}

    @router.post("/turn_owner_resolve")
    def resolve_turn_owner(
        payload: TurnOwnerResolveRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        return _plain(
            client.resolve_turn_owner(
                primary_face_candidate=_payload_dict(payload.primary_face_candidate),
                visible_face_candidates=[
                    _payload_dict(candidate)
                    for candidate in payload.visible_face_candidates
                ],
                voice_candidate=_payload_dict(payload.voice_candidate),
                policy_context=payload.policy_context,
            )
        )

    return router


def _plain(value: Any) -> dict[str, Any]:
    """Return dataclass, Pydantic, or dict values as plain JSON-compatible dicts."""
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump())
    payload = getattr(value, "__dict__", None)
    return dict(payload) if isinstance(payload, dict) else {}


def _payload_dict(value: Any) -> dict[str, Any] | None:
    return _plain(value) if value is not None else None


def _settings_int(client: TailwagMemoryClient, name: str) -> int | None:
    settings = getattr(client, "settings", None)
    value = getattr(settings, name, None)
    try:
        rendered = int(value)
    except (TypeError, ValueError):
        return None
    return rendered if rendered > 0 else None


def _validate_embedding_dimension(
    embedding: list[float],
    expected_dimension: int | None,
    field_name: str,
) -> None:
    if expected_dimension is None:
        return
    if len(embedding) != expected_dimension:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{field_name} dimension must be {expected_dimension}; "
                f"received {len(embedding)}"
            ),
        )


def _biometric_search_response(result: Any) -> dict[str, Any]:
    payload = _plain(result)
    candidates = [
        _biometric_candidate_response(candidate)
        for candidate in (payload.get("candidates") or [])
    ]
    return {
        "modality": payload.get("modality", ""),
        "candidates": candidates,
        "recognized": bool(payload.get("recognized")),
        "status": str(payload.get("status") or "rejected"),
        "reason": str(payload.get("reason") or "no_match"),
        "threshold": float(payload.get("threshold") or 0.0),
        "margin_threshold": float(payload.get("margin_threshold") or 0.0),
        "top_score": float(payload.get("top_score") or 0.0),
        "runner_up_score": float(payload.get("runner_up_score") or 0.0),
        "margin": float(payload.get("margin") or 0.0),
    }


def _biometric_candidate_response(candidate: Any) -> dict[str, Any]:
    payload = _plain(candidate)
    return {
        "person_id": str(payload.get("person_id") or ""),
        "display_name": str(payload.get("display_name") or ""),
        "score": float(payload.get("score") or 0.0),
        "metadata": dict(payload.get("metadata") or {}),
    }

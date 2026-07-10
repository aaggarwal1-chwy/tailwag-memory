from __future__ import annotations

from dataclasses import asdict
import os

from fastapi import APIRouter, Depends, FastAPI

from tailwag_memory.api.auth import require_bearer_token
from tailwag_memory.api.dependencies import get_client
from tailwag_memory.api.schemas import (
    EpisodeRecordRequest,
    PersonArchiveRequest,
    PersonContextRequest,
    PersonContextResponse,
    PersonRekeyByEmailRequest,
    PersonUpsertRequest,
    SemanticSearchRequest,
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

    @router.post("/person-context", response_model=PersonContextResponse)
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
            recent_episode_limit=payload.recent_episode_limit,
        )
        return PersonContextResponse(
            person_id=payload.person_id,
            context_markdown=rendered,
            generated_at=utc_now_iso(),
        )

    @router.post("/episodes")
    def episodes(
        payload: EpisodeRecordRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, object]:
        result = client.record_episode(
            EpisodeInput.from_dict(payload.episode.as_dict()),
            extract_memory=payload.extract_memory,
        )
        return asdict(result)

    @router.post("/semantic-search")
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

    @router.post("/people")
    def upsert_person(
        payload: PersonUpsertRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, str]:
        person_id = client.upsert_person(PersonInput(**payload.person.as_kwargs()))
        return {"person_id": person_id}

    @router.post("/people/archive")
    def archive_person(
        payload: PersonArchiveRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, bool]:
        return {"archived": client.archive_person(payload.person_id)}

    @router.post("/people/rekey-by-email")
    def rekey_person_by_email(
        payload: PersonRekeyByEmailRequest,
        client: TailwagMemoryClient = Depends(get_client),
    ) -> dict[str, bool]:
        return {"rekeyed": client.rekey_person_by_email(payload.email, payload.new_person_id)}

    return router

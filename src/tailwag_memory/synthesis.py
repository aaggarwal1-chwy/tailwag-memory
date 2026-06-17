from __future__ import annotations

import json
from typing import Any, Protocol

from .embeddings import OpenAIConfigurationError
from .models import PersonContextItem
from .retrieval import PersonContextRetrievalService


UNKNOWN_PERSON_MESSAGE = "the database does not have a record of this person"


class PersonContextProvider(Protocol):
    def synthesize(
        self,
        *,
        person_id: str,
        display_name: str | None,
        items: list[PersonContextItem],
    ) -> str:
        ...


class OpenAIPersonContextProvider:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-5.5",
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client

    def synthesize(
        self,
        *,
        person_id: str,
        display_name: str | None,
        items: list[PersonContextItem],
    ) -> str:
        response = self._openai_client().responses.create(
            model=self.model,
            input=[
                {
                    "role": "developer",
                    "content": (
                        "You write one concise natural-language paragraph for a social agent "
                        "that is about to interact with a person. Use only the supplied evidence. "
                        "Mention a follow-up naturally only if the evidence suggests one. "
                        "Do not use bullet points, JSON, markdown, or headings."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "person_id": person_id,
                            "display_name": display_name,
                            "recent_items": [
                                {
                                    "id": item.item_id,
                                    "type": item.item_type,
                                    "text": item.text,
                                    "start_time": item.start_time,
                                    "end_time": item.end_time,
                                    "building_code": item.building_code,
                                    "room_id": item.room_id,
                                    "role": item.role,
                                    "source": item.source,
                                }
                                for item in items
                            ],
                        },
                        sort_keys=True,
                    ),
                },
            ],
        )
        return self._extract_text(response)

    def _openai_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise OpenAIConfigurationError("OPENAI_API_KEY is required for OpenAI synthesis.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAIConfigurationError("Install the openai package to use OpenAI synthesis.") from exc
        self._client = OpenAI(api_key=self.api_key)
        return self._client

    def _extract_text(self, response: Any) -> str:
        if isinstance(response, dict):
            output_text = response.get("output_text")
            if output_text:
                return str(output_text).strip()
            return str(response["output"][0]["content"][0]["text"]).strip()
        if getattr(response, "output_text", None):
            return str(response.output_text).strip()
        return str(response.output[0].content[0].text).strip()


class PersonContextSynthesisService:
    def __init__(
        self,
        retrieval: PersonContextRetrievalService,
        provider: PersonContextProvider,
    ) -> None:
        self.retrieval = retrieval
        self.provider = provider

    def context_for_person(
        self,
        person_id: str,
        limit: int = 10,
        semantic_scope: str | None = None,
    ) -> str:
        source = self.retrieval.source_for_person(person_id, limit=limit, semantic_scope=semantic_scope)
        if source is None:
            return UNKNOWN_PERSON_MESSAGE
        if not source.items:
            name = source.display_name or person_id
            scope = semantic_scope.strip() if semantic_scope is not None else None
            if scope:
                return f"The database has a record for {name}, but no episodes matched the semantic scope: {scope}."
            return f"The database has a record for {name}, but no recent related events or episodes are available."
        return self.provider.synthesize(
            person_id=source.person_id,
            display_name=source.display_name,
            items=source.items,
        )

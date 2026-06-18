from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Protocol

from .embeddings import OpenAIConfigurationError
from .models import PersonContextItem
from .retrieval import PersonContextRetrievalService


UNKNOWN_PERSON_MESSAGE = "the database does not have a record of this person"


class PersonContextProvider(Protocol):
    """Describe a provider that synthesizes person context."""

    def synthesize(
        self,
        *,
        person_id: str,
        display_name: str | None,
        items: list[PersonContextItem],
        current_time: str,
    ) -> str:
        """Synthesize context from retrieved person items."""
        ...


class OpenAIPersonContextProvider:
    """Synthesize person context through OpenAI responses."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-5.5",
        client: Any | None = None,
    ) -> None:
        """Create an OpenAI-backed person context provider."""
        self.api_key = api_key
        self.model = model
        self._client = client

    def synthesize(
        self,
        *,
        person_id: str,
        display_name: str | None,
        items: list[PersonContextItem],
        current_time: str,
    ) -> str:
        """Return synthesized context for retrieved person evidence."""
        response = self._openai_client().responses.create(
            model=self.model,
            input=[
                {
                    "role": "developer",
                    "content": (
                        "You write one concise natural-language paragraph for a social agent "
                        "that is about to interact with a person. Use only the supplied evidence. "
                        "Temporal grounding rules: Treat current_time as now. Resolve relative "
                        "time words such as today, tomorrow, yesterday, later this week, and this "
                        "afternoon relative to the evidence timestamp or transcript line timestamp, "
                        "not your assumptions. Before writing, classify each possible follow-up as "
                        "past, current, future, or ambiguous relative to current_time. Only recommend "
                        "future or current follow-ups. Do not suggest following up on meetings or "
                        "events whose resolved date/time is before current_time; describe them as "
                        "already happened unless evidence says otherwise. If timing is ambiguous, "
                        "avoid future-tense suggestions. Prefer transcript evidence over summaries "
                        "when assigning actions or questions to a person. "
                        "Do not use bullet points, JSON, markdown, or headings."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_time": current_time,
                            "person_id": person_id,
                            "display_name": display_name,
                            "recent_items": [self._item_payload(item) for item in items],
                        },
                        sort_keys=True,
                    ),
                },
            ],
        )
        return self._extract_text(response)

    def _item_payload(self, item: PersonContextItem) -> dict[str, Any]:
        """Serialize one retrieved item for synthesis."""
        return {
            "id": item.item_id,
            "type": item.item_type,
            "text": item.text,
            "temporal_note": self._temporal_note(item),
            "start_time": item.start_time,
            "end_time": item.end_time,
            "building_code": item.building_code,
            "room_id": item.room_id,
            "role": item.role,
            "source_type": item.source,
            "transcript_lines": [
                {
                    "timestamp": line.timestamp,
                    "speaker": line.speaker,
                    "text": line.text,
                }
                for line in item.transcript_lines
            ],
        }

    def _temporal_note(self, item: PersonContextItem) -> str:
        """Describe how to interpret relative dates in one item."""
        evidence_date = item.start_time[:10] if len(item.start_time) >= 10 else item.start_time
        if not evidence_date:
            return "This evidence has no timestamp. Treat relative time references as ambiguous."
        return (
            f'This evidence occurred on {evidence_date}. Interpret "today" in this item as '
            f"{evidence_date} unless a transcript line has its own timestamp."
        )

    def _openai_client(self) -> Any:
        """Return the configured OpenAI client."""
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
        """Extract response text from OpenAI response shapes."""
        if isinstance(response, dict):
            output_text = response.get("output_text")
            if output_text:
                return str(output_text).strip()
            return str(response["output"][0]["content"][0]["text"]).strip()
        if getattr(response, "output_text", None):
            return str(response.output_text).strip()
        return str(response.output[0].content[0].text).strip()


class PersonContextSynthesisService:
    """Retrieve and synthesize person context."""

    def __init__(
        self,
        retrieval: PersonContextRetrievalService,
        provider: PersonContextProvider,
    ) -> None:
        """Create a synthesis service from retrieval and provider parts."""
        self.retrieval = retrieval
        self.provider = provider

    def context_for_person(
        self,
        person_id: str,
        limit: int = 10,
        semantic_scope: str | None = None,
    ) -> str:
        """Return synthesized context for a person."""
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
            current_time=_current_time_iso(),
        )


def _current_time_iso() -> str:
    """Return the local current time as ISO-8601 text."""
    return datetime.now().astimezone().isoformat()

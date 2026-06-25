from __future__ import annotations

import json
from typing import Any

from .embeddings import OpenAIConfigurationError
from .memory_item_constants import (
    MEMORY_CONSOLIDATION_DEVELOPER_PROMPT,
    MEMORY_CONSOLIDATION_TEXT_FORMAT,
    MEMORY_EXTRACTION_DEVELOPER_PROMPT,
    MEMORY_EXTRACTION_TEXT_FORMAT,
)
from .models import MemoryItemResult


class _OpenAIMemoryProviderBase:
    """Share OpenAI Responses API plumbing for memory providers."""

    _operation_name = "operation"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-5.5",
        client: Any | None = None,
    ) -> None:
        """Store OpenAI client configuration."""
        self.api_key = api_key
        self.model = model
        self._client = client

    def _memory_payload(self, item: MemoryItemResult) -> dict[str, Any]:
        """Render a memory item for provider context."""
        payload: dict[str, Any] = {
            "memory_id": item.memory_id,
            "kind": item.kind,
            "key": item.key,
            "summary": item.summary,
        }
        if item.due_at:
            payload["due_at"] = item.due_at
        if item.expires_at:
            payload["expires_at"] = item.expires_at
        return payload

    def _openai_client(self) -> Any:
        """Return a configured OpenAI client."""
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise OpenAIConfigurationError(f"OPENAI_API_KEY is required for OpenAI memory {self._operation_name}.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAIConfigurationError(
                f"Install the openai package to use OpenAI memory {self._operation_name}."
            ) from exc
        self._client = OpenAI(api_key=self.api_key)
        return self._client

    def _extract_text(self, response: Any) -> str:
        """Extract response text from dict or SDK response shapes."""
        if isinstance(response, dict):
            output_text = response.get("output_text")
            if output_text:
                return str(output_text).strip()
            return str(response["output"][0]["content"][0]["text"]).strip()
        if getattr(response, "output_text", None):
            return str(response.output_text).strip()
        return str(response.output[0].content[0].text).strip()


class OpenAIMemoryExtractionProvider(_OpenAIMemoryProviderBase):
    """Extract memory operations with the OpenAI Responses API."""

    _operation_name = "extraction"

    def extract(
        self,
        *,
        person_id: str,
        target_display_name: str | None = None,
        transcript: str,
        existing_memories: list[MemoryItemResult],
        current_time: str,
    ) -> dict[str, Any]:
        """Return memory operations extracted from a transcript."""
        response = self._openai_client().responses.create(
            model=self.model,
            text=MEMORY_EXTRACTION_TEXT_FORMAT,
            input=[
                {
                    "role": "developer",
                    "content": MEMORY_EXTRACTION_DEVELOPER_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_time": current_time,
                            "person_id": person_id,
                            "target_display_name": target_display_name,
                            "existing_memories": [self._memory_payload(item) for item in existing_memories],
                            "transcript": transcript,
                        },
                        sort_keys=True,
                    ),
                },
            ],
        )
        text = self._extract_text(response)
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise ValueError("OpenAI memory extraction did not return valid JSON") from exc
        return payload if isinstance(payload, dict) else {"update": False, "ops": []}


class OpenAIMemoryConsolidationProvider(_OpenAIMemoryProviderBase):
    """Consolidate repeated episode evidence with the OpenAI Responses API."""

    _operation_name = "consolidation"

    def consolidate(
        self,
        *,
        person_id: str,
        existing_memories: list[MemoryItemResult],
        episode_clusters: list[list[dict[str, str]]],
        current_time: str,
        min_evidence_episodes: int,
    ) -> dict[str, Any]:
        """Return memory operations consolidated from repeated episode evidence."""
        response = self._openai_client().responses.create(
            model=self.model,
            text=MEMORY_CONSOLIDATION_TEXT_FORMAT,
            input=[
                {
                    "role": "developer",
                    "content": MEMORY_CONSOLIDATION_DEVELOPER_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_time": current_time,
                            "person_id": person_id,
                            "min_evidence_episodes": min_evidence_episodes,
                            "existing_memories": [self._memory_payload(item) for item in existing_memories],
                            "episode_clusters": episode_clusters,
                        },
                        sort_keys=True,
                    ),
                },
            ],
        )
        text = self._extract_text(response)
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise ValueError("OpenAI memory consolidation did not return valid JSON") from exc
        return payload if isinstance(payload, dict) else {"update": False, "ops": []}

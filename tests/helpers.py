from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tailwag_memory.config import Settings
from tailwag_memory.models import EpisodeInput, EpisodeMentionInput, PersonInput, PlaceInput


@dataclass
class RecordedQuery:
    query: str
    parameters: dict[str, Any]


class RecordingQueryRunner:
    def __init__(
        self,
        results: list[list[dict[str, Any]]] | None = None,
        *,
        settings: Any | None = None,
    ) -> None:
        self.settings = settings
        self.queries: list[RecordedQuery] = []
        self.results = results or []
        self.closed = False

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.queries.append(RecordedQuery(query=query, parameters=parameters or {}))
        if self.results:
            return self.results.pop(0)
        return []

    def close(self) -> None:
        self.closed = True


def test_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "neo4j_uri": "bolt://example.test:7687",
        "neo4j_user": "neo4j",
        "neo4j_password": "password",
        "embedding_dimension": 8,
        "openai_api_key": "test-key",
    }
    values.update(overrides)
    return Settings(**values)


class StubConsolidationProvider:
    def __init__(self, response: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.response = response or {"update": False, "ops": []}
        self.error = error
        self.calls: list[dict[str, object]] = []

    def consolidate(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class StubExtractionProvider:
    def __init__(
        self,
        response: dict[str, object] | None = None,
        errors_by_person: dict[str, Exception] | None = None,
    ) -> None:
        self.response = response or {"update": False, "ops": []}
        self.errors_by_person = errors_by_person or {}
        self.calls: list[dict[str, object]] = []

    def extract(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        error = self.errors_by_person.get(kwargs.get("person_id"))
        if error is not None:
            raise error
        return self.response


def provider_response(*ops: object, update: bool = True) -> dict[str, object]:
    return {"update": update, "ops": list(ops)}


def consolidation_op(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "op": "create",
        "kind": "fact",
        "key": "robot_memory_demos",
        "summary": "uses robot demos to understand memory systems",
        "supported_episode_ids": ["ep1", "ep2", "ep3", "ep4"],
        "metadata": {},
    }
    values.update(overrides)
    return values


def extraction_op(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "op": "create",
        "memory_id": "",
        "kind": "",
        "key": "",
        "summary": "",
        "observed_at": "",
        "due_at": "",
        "expires_at": "",
        "metadata": {},
    }
    values.update(overrides)
    return values


def test_episode(
    *,
    episode_id: str = "episode_1",
    transcript: str = "Jamie: I like robot demos.",
    start_time: str = "2026-06-18T10:00:00+00:00",
    end_time: str | None = None,
    building_code: str = "MAIN",
    room_id: str = "101",
    participants: list[PersonInput] | None = None,
    mentioned_people: list[EpisodeMentionInput] | None = None,
) -> EpisodeInput:
    return EpisodeInput(
        id=episode_id,
        episode_type="conversation",
        start_time=start_time,
        end_time=end_time,
        transcript=transcript,
        retention_class="standard",
        place=PlaceInput(building_code=building_code, room_id=room_id),
        participants=(
            participants
            if participants is not None
            else [PersonInput(id="person_jamie", display_name="Jamie", role="speaker")]
        ),
        mentioned_people=mentioned_people if mentioned_people is not None else [],
    )

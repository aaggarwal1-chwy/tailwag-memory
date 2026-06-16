from __future__ import annotations

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .ingestion import EpisodeIngestionService, EventIngestionService
from .models import EpisodeInput, EventInput, PersonInput, PlaceInput


def demo_episodes() -> list[EpisodeInput]:
    return [
        EpisodeInput(
            id="episode_demo_001",
            episode_type="conversation",
            start_time="2026-06-15T13:00:00+00:00",
            end_time="2026-06-15T13:03:00+00:00",
            summary="Jamie asked where the spare laptop chargers are kept.",
            transcript="Jamie: Do we have spare laptop chargers in this room? Assistant: They are usually near the front desk.",
            retention_class="standard",
            place=PlaceInput(building_code="MAIN", room_id="101"),
            participants=[
                PersonInput(
                    id="person_jamie",
                    display_name="Jamie",
                    consent_status="consented",
                    role="speaker",
                    source="demo",
                )
            ],
        ),
        EpisodeInput(
            id="episode_demo_002",
            episode_type="conversation",
            start_time="2026-06-15T14:00:00+00:00",
            end_time="2026-06-15T14:04:00+00:00",
            summary="Alex discussed projector setup for the afternoon review.",
            transcript="Alex: Can we test the projector before the review? Assistant: Yes, the HDMI cable is already connected.",
            retention_class="standard",
            place=PlaceInput(building_code="MAIN", room_id="101"),
            participants=[
                PersonInput(
                    id="person_alex",
                    display_name="Alex",
                    consent_status="consented",
                    role="speaker",
                    source="demo",
                )
            ],
        ),
    ]


def seed_demo(runner: QueryRunner, embeddings: EmbeddingProvider) -> None:
    episode_service = EpisodeIngestionService(runner, embeddings)
    for episode in demo_episodes():
        episode_service.ingest(episode)

    event_service = EventIngestionService(runner)
    for event in demo_events():
        event_service.ingest(event)


def demo_events() -> list[EventInput]:
    return [
        EventInput(
            id="event_demo_001",
            description="Room 101 was reserved for the afternoon design review.",
            start_time="2026-06-15T15:00:00+00:00",
            end_time="2026-06-15T16:00:00+00:00",
            place=PlaceInput(building_code="MAIN", room_id="101"),
            accepted_attendees=[],
        )
    ]

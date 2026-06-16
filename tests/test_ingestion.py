from tailwag_memory.db import RecordingQueryRunner
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
from tailwag_memory.ingestion import EpisodeIngestionService, EventIngestionService
from tailwag_memory.models import EpisodeInput, EventInput, PersonInput, PlaceInput
import unittest


def _episode() -> EpisodeInput:
    return EpisodeInput(
        id="episode_external_001",
        episode_type="conversation",
        start_time="2026-06-15T10:00:00+00:00",
        end_time="2026-06-15T10:05:00+00:00",
        summary="Jamie asked about spare laptop chargers.",
        transcript="Jamie: Are there spare laptop chargers?",
        retention_class="standard",
        place=PlaceInput(building_code="MAIN", room_id="101"),
        participants=[
            PersonInput(
                id="person_external_jamie",
                display_name="Jamie",
                email="jamie@example.com",
                consent_status="consented",
                face_embedding=[0.1] * 8,
                audio_embedding=[0.2] * 8,
                role="speaker",
                source="test",
            )
        ],
    )


class EpisodeIngestionServiceTest(unittest.TestCase):
    def test_ingest_writes_episode_place_and_participant(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeIngestionService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        episode_id = service.ingest(_episode())

        self.assertEqual(episode_id, "episode_external_001")
        self.assertEqual(len(runner.queries), 3)
        self.assertEqual(runner.queries[0].parameters["id"], "episode_external_001")
        self.assertEqual(runner.queries[1].parameters["building_code"], "MAIN")
        self.assertEqual(runner.queries[1].parameters["room_id"], "101")
        self.assertEqual(runner.queries[2].parameters["person_id"], "person_external_jamie")
        self.assertEqual(runner.queries[2].parameters["last_seen"], "2026-06-15T10:05:00+00:00")
        self.assertEqual(runner.queries[2].parameters["email"], "jamie@example.com")
        self.assertEqual(runner.queries[2].parameters["face_embedding"], [0.1] * 8)
        self.assertEqual(runner.queries[2].parameters["audio_embedding"], [0.2] * 8)
        self.assertIn("p.display_name = coalesce($display_name, p.display_name)", runner.queries[2].query)
        self.assertIn("p.email = coalesce($email, p.email)", runner.queries[2].query)
        self.assertIn("p.consent_status = coalesce($consent_status, p.consent_status)", runner.queries[2].query)

    def test_ingest_query_excludes_org_identity_and_confidence(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeIngestionService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        service.ingest(_episode())
        query_text = "\n".join(query.query for query in runner.queries)

        self.assertNotIn("org_id", query_text)
        self.assertNotIn("identity_status", query_text)
        self.assertNotIn("confidence", query_text)

    def test_ingest_uses_start_time_for_last_seen_when_end_time_is_missing(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeIngestionService(runner, MockOpenAIEmbeddingProvider(dimension=8))
        episode = _episode()
        episode = EpisodeInput(
            id=episode.id,
            episode_type=episode.episode_type,
            start_time=episode.start_time,
            end_time=None,
            summary=episode.summary,
            transcript=episode.transcript,
            retention_class=episode.retention_class,
            place=episode.place,
            participants=episode.participants,
        )

        service.ingest(episode)

        self.assertEqual(runner.queries[2].parameters["last_seen"], "2026-06-15T10:00:00+00:00")

    def test_ingest_allows_existing_person_reference_by_id_only(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeIngestionService(runner, MockOpenAIEmbeddingProvider(dimension=8))
        episode = EpisodeInput(
            id="episode_external_002",
            episode_type="conversation",
            start_time="2026-06-16T10:00:00+00:00",
            end_time="2026-06-16T10:05:00+00:00",
            summary="Jamie asked about the projector.",
            transcript="Jamie: Is the projector ready?",
            retention_class="standard",
            place=PlaceInput(building_code="MAIN", room_id="101"),
            participants=[PersonInput(id="person_external_jamie")],
        )

        service.ingest(episode)

        self.assertEqual(runner.queries[2].parameters["person_id"], "person_external_jamie")
        self.assertIsNone(runner.queries[2].parameters["display_name"])
        self.assertIsNone(runner.queries[2].parameters["email"])
        self.assertIsNone(runner.queries[2].parameters["consent_status"])
        self.assertIsNone(runner.queries[2].parameters["face_embedding"])
        self.assertIsNone(runner.queries[2].parameters["audio_embedding"])


class EventIngestionServiceTest(unittest.TestCase):
    def test_ingest_event_writes_event_and_place_without_people(self) -> None:
        runner = RecordingQueryRunner()
        service = EventIngestionService(runner)
        event = EventInput(
            id="event_external_001",
            description="Room 101 was reserved for a design review.",
            start_time="2026-06-16T15:00:00+00:00",
            end_time="2026-06-16T16:00:00+00:00",
            place=PlaceInput(building_code="MAIN", room_id="101"),
        )

        event_id = service.ingest(event)

        self.assertEqual(event_id, "event_external_001")
        self.assertEqual(len(runner.queries), 2)
        self.assertEqual(runner.queries[0].parameters["id"], "event_external_001")
        self.assertEqual(runner.queries[0].parameters["description"], "Room 101 was reserved for a design review.")
        self.assertEqual(runner.queries[1].parameters["building_code"], "MAIN")
        self.assertEqual(runner.queries[1].parameters["room_id"], "101")
        self.assertNotIn("Person", runner.queries[0].query + runner.queries[1].query)
        self.assertNotIn("PARTICIPATED_IN", runner.queries[0].query + runner.queries[1].query)


if __name__ == "__main__":
    unittest.main()

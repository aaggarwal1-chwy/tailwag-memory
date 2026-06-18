from tailwag_memory.db import RecordingQueryRunner
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
from tailwag_memory.ingestion import EpisodeIngestionService, EventIngestionService, _person_upsert_cypher
from tailwag_memory.models import EpisodeInput, EventAttendeeInput, EventInput, PersonInput, PlaceInput
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


class PersonUpsertCypherTest(unittest.TestCase):
    def test_person_upsert_helper_preserves_consent_and_last_seen_rules(self) -> None:
        participant_clause = _person_upsert_cypher("person", "id")
        attendee_clause = _person_upsert_cypher("attendee", "person_id")

        self.assertIn("MERGE (p:Person {id: person.id})", participant_clause)
        self.assertIn("MERGE (p:Person {id: attendee.person_id})", attendee_clause)
        self.assertIn("p.email = coalesce(person.email, p.email)", participant_clause)
        self.assertIn("p.email = coalesce(attendee.email, p.email)", attendee_clause)
        self.assertIn("person.consent_status <> 'consented'", participant_clause)
        self.assertIn("attendee.consent_status <> 'consented'", attendee_clause)
        self.assertIn("datetime(p.last_seen) < datetime($last_seen)", participant_clause)
        self.assertIn("datetime(p.last_seen) < datetime($last_seen)", attendee_clause)


class EpisodeIngestionServiceTest(unittest.TestCase):
    def test_ingest_writes_episode_place_and_participant(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeIngestionService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        episode_id = service.ingest(_episode())

        self.assertEqual(episode_id, "episode_external_001")
        self.assertEqual(len(runner.queries), 1)
        self.assertEqual(runner.queries[0].parameters["id"], "episode_external_001")
        self.assertEqual(runner.queries[0].parameters["building_code"], "MAIN")
        self.assertEqual(runner.queries[0].parameters["room_id"], "101")
        self.assertEqual(runner.queries[0].parameters["participant_ids"], ["person_external_jamie"])
        self.assertEqual(runner.queries[0].parameters["updated_at"], runner.queries[0].parameters["created_at"])
        participant = runner.queries[0].parameters["participants"][0]
        self.assertEqual(participant["id"], "person_external_jamie")
        self.assertEqual(participant["email"], "jamie@example.com")
        self.assertEqual(participant["face_embedding"], [0.1] * 8)
        self.assertEqual(participant["audio_embedding"], [0.2] * 8)
        self.assertEqual(runner.queries[0].parameters["last_seen"], "2026-06-15T10:05:00+00:00")
        self.assertIn("DELETE old_place", runner.queries[0].query)
        self.assertIn("DELETE old_rel", runner.queries[0].query)
        self.assertIn("UNWIND $participants AS person", runner.queries[0].query)
        self.assertIn("e.created_at = coalesce(e.created_at, $created_at)", runner.queries[0].query)
        self.assertIn("e.updated_at = $updated_at", runner.queries[0].query)
        self.assertIn("p.display_name = coalesce(person.display_name, p.display_name)", runner.queries[0].query)
        self.assertIn("datetime(p.last_seen) < datetime($last_seen)", runner.queries[0].query)
        self.assertIn("person.consent_status <> 'consented'", runner.queries[0].query)

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

        self.assertEqual(runner.queries[0].parameters["last_seen"], "2026-06-15T10:00:00+00:00")

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

        participant = runner.queries[0].parameters["participants"][0]
        self.assertEqual(participant["id"], "person_external_jamie")
        self.assertIsNone(participant["display_name"])
        self.assertIsNone(participant["email"])
        self.assertIsNone(participant["consent_status"])
        self.assertIsNone(participant["face_embedding"])
        self.assertIsNone(participant["audio_embedding"])


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
            accepted_attendees=[],
        )

        event_id = service.ingest(event)

        self.assertEqual(event_id, "event_external_001")
        self.assertEqual(len(runner.queries), 1)
        self.assertEqual(runner.queries[0].parameters["id"], "event_external_001")
        self.assertEqual(runner.queries[0].parameters["description"], "Room 101 was reserved for a design review.")
        self.assertEqual(runner.queries[0].parameters["building_code"], "MAIN")
        self.assertEqual(runner.queries[0].parameters["room_id"], "101")
        self.assertEqual(runner.queries[0].parameters["attendees"], [])
        self.assertEqual(runner.queries[0].parameters["attendee_ids"], [])
        self.assertEqual(runner.queries[0].parameters["updated_at"], runner.queries[0].parameters["created_at"])
        self.assertIn("e.created_at = coalesce(e.created_at, $created_at)", runner.queries[0].query)
        self.assertIn("e.updated_at = $updated_at", runner.queries[0].query)
        self.assertNotIn("PARTICIPATED_IN", runner.queries[0].query)

    def test_ingest_event_writes_accepted_attendees(self) -> None:
        runner = RecordingQueryRunner()
        service = EventIngestionService(runner)
        event = EventInput(
            id="event_external_002",
            description="Room 101 was reserved for a design review.",
            start_time="2026-06-16T15:00:00+00:00",
            end_time="2026-06-16T16:00:00+00:00",
            place=PlaceInput(building_code="MAIN", room_id="101"),
            accepted_attendees=[
                EventAttendeeInput(
                    person=PersonInput(
                        id="person_external_jamie",
                        display_name="Jamie",
                        email="jamie@example.com",
                        consent_status="consented",
                    ),
                    response_time="2026-06-15T18:00:00+00:00",
                    source="outlook",
                )
            ],
        )

        event_id = service.ingest(event)

        self.assertEqual(event_id, "event_external_002")
        self.assertEqual(len(runner.queries), 1)
        attendee = runner.queries[0].parameters["attendees"][0]
        self.assertEqual(attendee["person_id"], "person_external_jamie")
        self.assertEqual(attendee["display_name"], "Jamie")
        self.assertEqual(attendee["email"], "jamie@example.com")
        self.assertEqual(attendee["consent_status"], "consented")
        self.assertEqual(runner.queries[0].parameters["last_seen"], "2026-06-16T16:00:00+00:00")
        self.assertEqual(attendee["source"], "outlook")
        self.assertEqual(attendee["response"], "accepted")
        self.assertEqual(attendee["response_time"], "2026-06-15T18:00:00+00:00")
        self.assertIn("MERGE (p)-[r:ATTENDED]->(e)", runner.queries[0].query)
        self.assertIn("p.email = coalesce(attendee.email, p.email)", runner.queries[0].query)
        self.assertIn("attendee.consent_status <> 'consented'", runner.queries[0].query)

    def test_ingest_event_uses_start_time_for_attendee_last_seen_when_end_time_is_missing(self) -> None:
        runner = RecordingQueryRunner()
        service = EventIngestionService(runner)
        event = EventInput(
            id="event_external_003",
            description="Room 101 was reserved for a design review.",
            start_time="2026-06-16T15:00:00+00:00",
            end_time=None,
            place=PlaceInput(building_code="MAIN", room_id="101"),
            accepted_attendees=[
                EventAttendeeInput(
                    person=PersonInput(id="person_external_jamie"),
                    source="outlook",
                )
            ],
        )

        service.ingest(event)

        self.assertEqual(runner.queries[0].parameters["last_seen"], "2026-06-16T15:00:00+00:00")


if __name__ == "__main__":
    unittest.main()

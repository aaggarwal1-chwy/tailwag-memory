from tailwag_memory.db import RecordingQueryRunner
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
from tailwag_memory.ingestion import (
    EpisodeIngestionService,
    EventIngestionService,
    PersonIngestionService,
    _person_upsert_cypher,
)
from tailwag_memory.models import EpisodeInput, EventAttendeeInput, EventInput, PersonInput, PlaceInput
import unittest


def _episode() -> EpisodeInput:
    return EpisodeInput(
        id="episode_external_001",
        episode_type="conversation",
        start_time="2026-06-15T10:00:00+00:00",
        end_time="2026-06-15T10:05:00+00:00",
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
        self.assertIn("p.status = 'archived' THEN p.face_embedding", participant_clause)
        self.assertIn("p.status = 'archived' THEN p.audio_embedding", attendee_clause)
        self.assertIn("datetime(p.last_seen) < datetime($last_seen)", participant_clause)
        self.assertIn("datetime(p.last_seen) < datetime($last_seen)", attendee_clause)


class PersonIngestionServiceTest(unittest.TestCase):
    def test_upsert_writes_active_person_profile_and_biometrics(self) -> None:
        runner = RecordingQueryRunner()
        service = PersonIngestionService(runner)

        person_id = service.upsert(
            PersonInput(
                id="person_external_jamie",
                display_name="Jamie",
                email="jamie@example.com",
                consent_status="consented",
                face_embedding=[0.1] * 8,
                audio_embedding=[0.2] * 8,
            )
        )

        self.assertEqual(person_id, "person_external_jamie")
        self.assertEqual(len(runner.queries), 2)
        self.assertIn("MATCH (p:Person {email: $email})", runner.queries[0].query)
        self.assertEqual(runner.queries[0].parameters["incoming_id"], "person_external_jamie")
        query = runner.queries[1]
        self.assertEqual(query.parameters["person"]["id"], "person_external_jamie")
        self.assertEqual(query.parameters["person"]["display_name"], "Jamie")
        self.assertEqual(query.parameters["person"]["email"], "jamie@example.com")
        self.assertEqual(query.parameters["person"]["consent_status"], "consented")
        self.assertEqual(query.parameters["person"]["face_embedding"], [0.1] * 8)
        self.assertEqual(query.parameters["person"]["audio_embedding"], [0.2] * 8)
        self.assertEqual(query.parameters["created_at"], query.parameters["updated_at"])
        self.assertEqual(query.parameters["last_seen"], query.parameters["updated_at"])
        self.assertIn("WITH $person AS person", query.query)
        self.assertIn("MERGE (p:Person {id: person.id})", query.query)
        self.assertIn("p.created_at = coalesce(p.created_at, $created_at)", query.query)
        self.assertIn("p.updated_at = $updated_at", query.query)
        self.assertIn("p.last_seen = $last_seen", query.query)
        self.assertIn("p.status = 'active'", query.query)
        self.assertIn("p.archived_at = NULL", query.query)
        self.assertIn("person.consent_status <> 'consented'", query.query)
        self.assertNotIn("p.status = 'archived' THEN p.face_embedding", query.query)
        self.assertNotIn("p.status = 'archived' THEN p.audio_embedding", query.query)

    def test_upsert_query_excludes_org_identity_and_confidence(self) -> None:
        runner = RecordingQueryRunner()
        service = PersonIngestionService(runner)

        service.upsert(PersonInput(id="person_external_jamie"))
        query = runner.queries[0]
        text = query.query + repr(query.parameters)

        self.assertNotIn("org_id", text)
        self.assertNotIn("identity_status", text)
        self.assertNotIn("confidence", text)

    def test_upsert_stores_normalized_email_value_for_unique_identity_constraint(self) -> None:
        runner = RecordingQueryRunner()
        service = PersonIngestionService(runner)

        service.upsert(PersonInput(id="person_external_jamie", email=" Jamie.Example@Example.COM "))

        query = runner.queries[1]
        self.assertEqual(query.parameters["person"]["email"], "jamie.example@example.com")
        self.assertIn("p.email = coalesce(person.email, p.email)", query.query)

    def test_upsert_rekeys_slack_email_match_to_incoming_argos_id(self) -> None:
        runner = RecordingQueryRunner(results=[[{"person_id": "person_jamie"}], [{"person_id": "person_jamie"}]])
        service = PersonIngestionService(runner)

        person_id = service.upsert(PersonInput(id="person_jamie", email="jamie@example.com"))

        self.assertEqual(person_id, "person_jamie")
        resolve_query = runner.queries[0]
        self.assertEqual(resolve_query.parameters["email"], "jamie@example.com")
        self.assertEqual(resolve_query.parameters["incoming_id"], "person_jamie")
        self.assertIn("p.id STARTS WITH 'slack:'", resolve_query.query)
        self.assertIn("$incoming_id STARTS WITH 'person_'", resolve_query.query)
        self.assertIn("THEN $incoming_id", resolve_query.query)
        self.assertEqual(runner.queries[1].parameters["person"]["id"], "person_jamie")

    def test_archive_updates_lifecycle_and_clears_biometrics(self) -> None:
        runner = RecordingQueryRunner(results=[[{"person_id": "person_external_jamie"}]])
        service = PersonIngestionService(runner)

        archived = service.archive("person_external_jamie")

        self.assertTrue(archived)
        self.assertEqual(len(runner.queries), 1)
        query = runner.queries[0]
        self.assertEqual(query.parameters["person_id"], "person_external_jamie")
        self.assertEqual(query.parameters["archived_at"], query.parameters["updated_at"])
        self.assertIn("MATCH (p:Person {id: $person_id})", query.query)
        self.assertIn("p.status = 'archived'", query.query)
        self.assertIn("p.archived_at = $archived_at", query.query)
        self.assertIn("p.updated_at = $updated_at", query.query)
        self.assertIn("p.face_embedding = NULL", query.query)
        self.assertIn("p.audio_embedding = NULL", query.query)
        self.assertNotIn("DELETE", query.query)
        self.assertNotIn("DETACH", query.query)
        self.assertNotIn("p.display_name", query.query)
        self.assertNotIn("p.email", query.query)
        self.assertNotIn("p.consent_status", query.query)
        text = query.query + repr(query.parameters)
        self.assertNotIn("org_id", text)
        self.assertNotIn("identity_status", text)
        self.assertNotIn("confidence", text)

    def test_archive_returns_false_when_person_is_missing(self) -> None:
        runner = RecordingQueryRunner(results=[[]])
        service = PersonIngestionService(runner)

        archived = service.archive("person_missing")

        self.assertFalse(archived)

    def test_rekey_by_email_updates_one_person_to_canonical_id(self) -> None:
        runner = RecordingQueryRunner(results=[[{"person_id": "person_argos_jamie"}]])
        service = PersonIngestionService(runner)

        rekeyed = service.rekey_by_email(" jamie@example.com ", " person_argos_jamie ")

        self.assertTrue(rekeyed)
        self.assertEqual(len(runner.queries), 1)
        query = runner.queries[0]
        self.assertEqual(query.parameters["incoming_id"], "person_argos_jamie")
        self.assertIn("updated_at", query.parameters)
        self.assertEqual(query.parameters["email"], "jamie@example.com")
        self.assertIn("MATCH (p:Person {email: $email})", query.query)
        self.assertIn("WITH collect(p) AS matches", query.query)
        self.assertIn("WHERE size(matches) = 1", query.query)
        self.assertIn("OPTIONAL MATCH (target:Person {id: $incoming_id})", query.query)
        self.assertIn("p.id STARTS WITH 'slack:'", query.query)
        self.assertIn("$incoming_id STARTS WITH 'person_'", query.query)
        self.assertIn("SET p.id = CASE WHEN should_rekey THEN $incoming_id ELSE p.id END", query.query)
        self.assertIn("p.updated_at = CASE WHEN should_rekey THEN coalesce($updated_at, p.updated_at) ELSE p.updated_at END", query.query)
        self.assertIn("RETURN p.id AS person_id", query.query)
        text = query.query + repr(query.parameters)
        self.assertNotIn("face_embedding", text)
        self.assertNotIn("audio_embedding", text)
        self.assertNotIn("MERGE (canonical)", query.query)
        self.assertNotIn("DETACH DELETE", query.query)
        self.assertNotIn("org_id", text)
        self.assertNotIn("identity_status", text)
        self.assertNotIn("confidence", text)

    def test_rekey_by_email_returns_false_when_no_unique_safe_match(self) -> None:
        runner = RecordingQueryRunner(results=[[]])
        service = PersonIngestionService(runner)

        rekeyed = service.rekey_by_email("jamie@example.com", "person_argos_jamie")

        self.assertFalse(rekeyed)

    def test_rekey_by_email_rejects_blank_inputs(self) -> None:
        service = PersonIngestionService(RecordingQueryRunner())

        with self.assertRaisesRegex(ValueError, "email"):
            service.rekey_by_email("", "person_argos_jamie")
        with self.assertRaisesRegex(ValueError, "new_person_id"):
            service.rekey_by_email("jamie@example.com", " ")

    def test_canonical_id_by_email_returns_unambiguous_argos_person_id(self) -> None:
        runner = RecordingQueryRunner(results=[[{"person_id": "person_argos_jamie"}]])
        service = PersonIngestionService(runner)

        person_id = service.canonical_id_by_email(" jamie@example.com ")

        self.assertEqual(person_id, "person_argos_jamie")
        query = runner.queries[0]
        self.assertEqual(query.parameters["email"], "jamie@example.com")
        self.assertIn("p.email = $email", query.query)
        self.assertIn("p.id STARTS WITH 'person_'", query.query)
        self.assertIn("WHERE size(person_ids) = 1", query.query)

    def test_canonical_id_by_email_returns_none_when_unresolved(self) -> None:
        service = PersonIngestionService(RecordingQueryRunner(results=[[]]))

        self.assertIsNone(service.canonical_id_by_email("jamie@example.com"))
        self.assertIsNone(service.canonical_id_by_email(""))


class EpisodeIngestionServiceTest(unittest.TestCase):
    def test_ingest_writes_episode_place_and_participant(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeIngestionService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        episode_id = service.ingest(_episode())

        self.assertEqual(episode_id, "episode_external_001")
        self.assertEqual(len(runner.queries), 2)
        query = runner.queries[1]
        self.assertEqual(query.parameters["id"], "episode_external_001")
        self.assertEqual(query.parameters["building_code"], "MAIN")
        self.assertEqual(query.parameters["room_id"], "101")
        self.assertEqual(query.parameters["participant_ids"], ["person_external_jamie"])
        self.assertEqual(query.parameters["updated_at"], query.parameters["created_at"])
        participant = query.parameters["participants"][0]
        self.assertEqual(participant["id"], "person_external_jamie")
        self.assertEqual(participant["email"], "jamie@example.com")
        self.assertEqual(participant["face_embedding"], [0.1] * 8)
        self.assertEqual(participant["audio_embedding"], [0.2] * 8)
        self.assertEqual(query.parameters["last_seen"], "2026-06-15T10:05:00+00:00")
        self.assertIn("DELETE old_place", query.query)
        self.assertIn("DELETE old_rel", query.query)
        self.assertIn("UNWIND $participants AS person", query.query)
        self.assertIn("e.created_at = coalesce(e.created_at, $created_at)", query.query)
        self.assertIn("e.updated_at = $updated_at", query.query)
        self.assertIn("p.display_name = coalesce(person.display_name, p.display_name)", query.query)
        self.assertIn("datetime(p.last_seen) < datetime($last_seen)", query.query)
        self.assertIn("person.consent_status <> 'consented'", query.query)

    def test_ingest_episode_attaches_slack_participant_to_existing_email_person(self) -> None:
        runner = RecordingQueryRunner(results=[[{"person_id": "person_jamie"}]])
        service = EpisodeIngestionService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        service.ingest(
            EpisodeInput(
                id="episode_slack_001",
                episode_type="conversation",
                start_time="2026-06-15T10:00:00+00:00",
                end_time="2026-06-15T10:05:00+00:00",
                transcript="Jamie: Slack message.",
                retention_class="standard",
                place=PlaceInput(building_code="SLACK", room_id="C123"),
                participants=[
                    PersonInput(
                        id="slack:U1",
                        display_name="Jamie Slack",
                        email="jamie@example.com",
                        role="speaker",
                        source="slack",
                    )
                ],
            )
        )

        query = runner.queries[1]
        self.assertEqual(query.parameters["participant_ids"], ["person_jamie"])
        self.assertEqual(query.parameters["participants"][0]["id"], "person_jamie")
        self.assertEqual(query.parameters["participants"][0]["source"], "slack")

    def test_ingest_normalizes_robot_user_label_before_storage_and_embeddings(self) -> None:
        class RecordingEmbeddingProvider:
            def __init__(self) -> None:
                self.texts = []

            def embed(self, text: str) -> list[float]:
                self.texts.append(text)
                return [float(len(self.texts))] * 8

        runner = RecordingQueryRunner()
        embeddings = RecordingEmbeddingProvider()
        service = EpisodeIngestionService(runner, embeddings)
        episode = EpisodeInput(
            id="episode_external_001",
            episode_type="conversation",
            start_time="2026-06-15T10:00:00+00:00",
            end_time="2026-06-15T10:05:00+00:00",
            transcript="User: I like robot demos.\nAssistant: Noted.",
            retention_class="standard",
            place=PlaceInput(building_code="ARGOS", room_id="realtime"),
            participants=[
                PersonInput(
                    id="person_jamie",
                    display_name="Jamie",
                    role="speaker",
                    source="live_chat",
                )
            ],
        )

        service.ingest(episode)

        query = runner.queries[0]
        self.assertEqual(query.parameters["transcript"], "Jamie: I like robot demos.\nAssistant: Noted.")
        self.assertEqual(
            embeddings.texts,
            [
                "Jamie: I like robot demos.\nAssistant: Noted.",
            ],
        )
        self.assertNotIn("summary", query.parameters)
        self.assertNotIn("summary_embedding", query.parameters)

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
            transcript=episode.transcript,
            retention_class=episode.retention_class,
            place=episode.place,
            participants=episode.participants,
        )

        service.ingest(episode)

        self.assertEqual(runner.queries[-1].parameters["last_seen"], "2026-06-15T10:00:00+00:00")

    def test_ingest_allows_existing_person_reference_by_id_only(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeIngestionService(runner, MockOpenAIEmbeddingProvider(dimension=8))
        episode = EpisodeInput(
            id="episode_external_002",
            episode_type="conversation",
            start_time="2026-06-16T10:00:00+00:00",
            end_time="2026-06-16T10:05:00+00:00",
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
        self.assertEqual(len(runner.queries), 2)
        query = runner.queries[1]
        attendee = query.parameters["attendees"][0]
        self.assertEqual(attendee["person_id"], "person_external_jamie")
        self.assertEqual(attendee["display_name"], "Jamie")
        self.assertEqual(attendee["email"], "jamie@example.com")
        self.assertEqual(attendee["consent_status"], "consented")
        self.assertEqual(query.parameters["last_seen"], "2026-06-16T16:00:00+00:00")
        self.assertEqual(attendee["source"], "outlook")
        self.assertEqual(attendee["response"], "accepted")
        self.assertEqual(attendee["response_time"], "2026-06-15T18:00:00+00:00")
        self.assertIn("MERGE (p)-[r:ATTENDED]->(e)", query.query)
        self.assertIn("p.email = coalesce(attendee.email, p.email)", query.query)
        self.assertIn("attendee.consent_status <> 'consented'", query.query)

    def test_ingest_event_attaches_attendee_to_existing_email_person(self) -> None:
        runner = RecordingQueryRunner(results=[[{"person_id": "person_jamie"}]])
        service = EventIngestionService(runner)

        service.ingest(
            EventInput(
                id="event_external_004",
                description="Design review.",
                start_time="2026-06-16T15:00:00+00:00",
                end_time="2026-06-16T16:00:00+00:00",
                place=PlaceInput(building_code="MAIN", room_id="101"),
                accepted_attendees=[
                    EventAttendeeInput(
                        person=PersonInput(
                            id="slack:U1",
                            display_name="Jamie Slack",
                            email="jamie@example.com",
                        ),
                        source="slack",
                    )
                ],
            )
        )

        query = runner.queries[1]
        self.assertEqual(query.parameters["attendee_ids"], ["person_jamie"])
        self.assertEqual(query.parameters["attendees"][0]["person_id"], "person_jamie")

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

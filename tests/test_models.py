from tailwag_memory.models import EpisodeInput, EventInput, MemoryItemMergeResult, PersonMemoryConsolidationResult
import unittest


class EpisodeInputTest(unittest.TestCase):
    def test_episode_input_from_dict_uses_caller_owned_ids(self) -> None:
        episode = EpisodeInput.from_dict(
            {
                "id": "episode_external_123",
                "episode_type": "conversation",
                "start_time": "2026-06-15T10:00:00+00:00",
                "end_time": None,
                "summary": "Jamie asked about chargers.",
                "transcript": "Jamie: Any chargers?",
                "retention_class": "standard",
                "place": {"building_code": "MAIN", "room_id": "101"},
                "participants": [
                    {
                        "id": "person_external_456",
                        "display_name": "Jamie",
                        "email": "jamie@example.com",
                        "consent_status": "consented",
                        "face_embedding": [0.1, 0.2],
                        "audio_embedding": [0.3, 0.4],
                    }
                ],
            }
        )

        self.assertEqual(episode.id, "episode_external_123")
        self.assertEqual(episode.participants[0].id, "person_external_456")
        self.assertEqual(episode.place.building_code, "MAIN")
        self.assertEqual(episode.place.room_id, "101")
        self.assertEqual(episode.participants[0].role, "participant")
        self.assertEqual(episode.participants[0].source, "caller")
        self.assertEqual(episode.participants[0].email, "jamie@example.com")
        self.assertEqual(episode.participants[0].face_embedding, [0.1, 0.2])
        self.assertEqual(episode.participants[0].audio_embedding, [0.3, 0.4])

    def test_episode_input_allows_existing_person_reference_by_id_only(self) -> None:
        episode = EpisodeInput.from_dict(
            {
                "id": "episode_external_124",
                "episode_type": "conversation",
                "start_time": "2026-06-16T10:00:00+00:00",
                "summary": "Jamie asked about the projector.",
                "transcript": "Jamie: Is the projector ready?",
                "retention_class": "standard",
                "place": {"building_code": "MAIN", "room_id": "101"},
                "participants": [{"id": "person_external_456"}],
            }
        )

        person = episode.participants[0]
        self.assertEqual(person.id, "person_external_456")
        self.assertIsNone(person.display_name)
        self.assertIsNone(person.email)
        self.assertIsNone(person.consent_status)
        self.assertEqual(person.role, "participant")
        self.assertEqual(person.source, "caller")


class EventInputTest(unittest.TestCase):
    def test_event_input_requires_accepted_attendees_field(self) -> None:
        with self.assertRaises(KeyError):
            EventInput.from_dict(
                {
                    "id": "event_external_001",
                    "description": "Room 101 was reserved for a design review.",
                    "start_time": "2026-06-16T15:00:00+00:00",
                    "end_time": "2026-06-16T16:00:00+00:00",
                    "place": {"building_code": "MAIN", "room_id": "101"},
                }
            )

    def test_event_input_from_dict_links_to_place_without_people(self) -> None:
        event = EventInput.from_dict(
            {
                "id": "event_external_001",
                "description": "Room 101 was reserved for a design review.",
                "start_time": "2026-06-16T15:00:00+00:00",
                "end_time": "2026-06-16T16:00:00+00:00",
                "place": {"building_code": "MAIN", "room_id": "101"},
                "accepted_attendees": [],
            }
        )

        self.assertEqual(event.id, "event_external_001")
        self.assertEqual(event.description, "Room 101 was reserved for a design review.")
        self.assertEqual(event.place.building_code, "MAIN")
        self.assertEqual(event.place.room_id, "101")
        self.assertEqual(event.accepted_attendees, [])

    def test_event_input_from_dict_accepts_attendees(self) -> None:
        event = EventInput.from_dict(
            {
                "id": "event_external_002",
                "description": "Room 101 was reserved for a design review.",
                "start_time": "2026-06-16T15:00:00+00:00",
                "end_time": "2026-06-16T16:00:00+00:00",
                "place": {"building_code": "MAIN", "room_id": "101"},
                "accepted_attendees": [
                    {
                        "person": {
                            "id": "person_external_jamie",
                            "display_name": "Jamie",
                            "email": "jamie@example.com",
                        },
                        "response_time": "2026-06-15T18:00:00+00:00",
                        "source": "outlook",
                    }
                ],
            }
        )

        attendee = event.accepted_attendees[0]
        self.assertEqual(attendee.person.id, "person_external_jamie")
        self.assertEqual(attendee.person.display_name, "Jamie")
        self.assertEqual(attendee.person.email, "jamie@example.com")
        self.assertEqual(attendee.person.role, "attendee")
        self.assertEqual(attendee.person.source, "outlook")
        self.assertEqual(attendee.source, "outlook")
        self.assertEqual(attendee.response, "accepted")
        self.assertEqual(attendee.response_time, "2026-06-15T18:00:00+00:00")


class MemoryModelTest(unittest.TestCase):
    def test_memory_merge_result_defaults_are_independent(self) -> None:
        first = MemoryItemMergeResult(person_id="person_jamie", merged_memory_id="mem_family")
        second = MemoryItemMergeResult(person_id="person_casey", merged_memory_id="mem_family")

        first.superseded_memory_ids.append("mem_old")
        first.skipped_source_memory_ids.append("mem_skip")

        self.assertEqual(second.superseded_memory_ids, [])
        self.assertEqual(second.skipped_source_memory_ids, [])

    def test_consolidation_result_tracks_superseded_memory_ids(self) -> None:
        result = PersonMemoryConsolidationResult(person_id="person_jamie")

        self.assertEqual(result.superseded_memory_ids, [])


if __name__ == "__main__":
    unittest.main()

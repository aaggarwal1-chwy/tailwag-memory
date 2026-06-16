from tailwag_memory.models import EpisodeInput, EventInput
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
    def test_event_input_from_dict_links_to_place_without_people(self) -> None:
        event = EventInput.from_dict(
            {
                "id": "event_external_001",
                "description": "Room 101 was reserved for a design review.",
                "start_time": "2026-06-16T15:00:00+00:00",
                "end_time": "2026-06-16T16:00:00+00:00",
                "place": {"building_code": "MAIN", "room_id": "101"},
            }
        )

        self.assertEqual(event.id, "event_external_001")
        self.assertEqual(event.description, "Room 101 was reserved for a design review.")
        self.assertEqual(event.place.building_code, "MAIN")
        self.assertEqual(event.place.room_id, "101")


if __name__ == "__main__":
    unittest.main()
